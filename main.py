import os
import sys

# Force Playwright to use the user's local AppData directory for browsers when compiled.
if getattr(sys, 'frozen', False):
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = os.path.expandvars(r"%LOCALAPPDATA%\ms-playwright")

import argparse
import time
import json
from dotenv import load_dotenv

# Determine the application root directory (where ACCCE.exe or main.py lives)
app_root_override = os.getenv("ACCCE_APPDATA_DIR")
if app_root_override:
    app_root = app_root_override
elif getattr(sys, 'frozen', False):
    app_root = os.path.dirname(sys.executable)
else:
    app_root = os.path.dirname(os.path.abspath(__file__))

env_path = os.path.join(app_root, ".env")
# Load configuration from .env file explicitly from the application root
load_dotenv(dotenv_path=env_path)
from project_accce.stealth.browser import launch_stealth_browser
from project_accce.behavior.page import HumanizedPage
from project_accce.behavior.math_utils import poisson_sleep, set_speed_factor, get_speed_factor
from project_accce.cognitive.quiz import extract_quiz_payloads, solve_quiz_with_gemini, check_checkbox_safely_scoped
from project_accce.cognitive.lab import setup_lab_interceptor, WebSocketLabClient, run_closed_loop_lab_agent
from project_accce.orchestrator.db import ACCCEStorage
from project_accce.orchestrator.notifier import send_discord_notification
from project_accce.orchestrator.scheduler import run_gradebook_polling_cycle
from project_accce.schemas import SyllabusNode
from project_accce.layout import fetch_layout_map, get_selector

def scaled_sleep(seconds: float) -> None:
    """Sleep for `seconds` scaled by the global speed factor. Minimum 0.1 s."""
    time.sleep(max(0.1, seconds * get_speed_factor()))

def verify_node_completed_on_page(hpage: HumanizedPage, node_id: str, timeout_sec: int = 15) -> bool:
    print(f"[ENGINE] Verifying completion status for node {node_id} on page...")
    for _ in range(timeout_sec):
        is_completed = hpage.page.evaluate('''(nodeId) => {
            const a = document.querySelector(`a[href*="${nodeId}"]`);
            if (!a) return false;
            
            let isCompleted = false;
            if (a.textContent.includes("Completed")) {
                isCompleted = true;
            } else if (a.querySelector('[data-testid="learn-item-success-icon"]')) {
                isCompleted = true;
            } else {
                const svgEl = a.querySelector('svg');
                if (svgEl) {
                    const ariaLabel = svgEl.getAttribute('aria-label') || '';
                    const hasSuccessClass = svgEl.classList.contains('css-1cdzuc5');
                    if (ariaLabel.toLowerCase().includes('completed') || hasSuccessClass) {
                        isCompleted = true;
                    }
                }
            }
            return isCompleted;
        }''', node_id)
        if is_completed:
            print(f"[ENGINE] Verification SUCCESS: Node {node_id} is marked as completed on Coursera!")
            return True
        scaled_sleep(1)
    return False

def handle_active_modal(hpage: HumanizedPage) -> bool:
    """
    Checks if an active Honor Code or confirmation modal is open on the page.
    If so, checks any visible checkboxes and clicks the confirmation/continue button.
    Returns True if a modal was handled, False otherwise.
    """
    modal_selectors = [
        "[data-testid='HonorCodeModal']",
        "div[role='dialog']",
        "div[role='alertdialog']",
        ".rc-Modal",
        ".cds-dialog",
        ".cds-Dialog-dialog"
    ]
    active_modal = None
    for sel in modal_selectors:
        try:
            loc = hpage.page.locator(sel)
            if loc.count() > 0 and loc.last.is_visible():
                active_modal = loc.last
                print(f"[ENGINE] Detected active modal overlay: '{sel}'")
                break
        except Exception:
            pass

    if not active_modal:
        return False

    checkbox_selectors = [
        "input[type='checkbox']#honor-code-checkbox",
        "input[type='checkbox'][name='honor-code']",
        "label:has-text('Honor Code') input",
        "input#agreement-checkbox",
        "input#agreement-checkbox-base",
        "input[type='checkbox']#agreement-checkbox-base",
        "input[type='checkbox']"
    ]
    for sel in checkbox_selectors:
        try:
            if active_modal.locator(sel).count() > 0 and active_modal.locator(sel).first.is_visible():
                print(f"[ENGINE] Found checkbox '{sel}' inside modal. Checking safely...")
                check_checkbox_safely_scoped(active_modal, sel)
                scaled_sleep(1)
                break
        except Exception as e:
            print(f"[ENGINE] Error checking checkbox inside modal: {e}")

    confirm_selectors = [
        "button:has-text(/^Continue$/i)",
        "button:has-text(/^Start Quiz$/i)",
        "button:has-text(/^Start attempt$/i)",
        "button:has-text(/^Start Attempt$/i)",
        "button:has-text(/^I agree$/i)",
        "button:has-text(/^I Agree$/i)",
        "button:has-text(/^Start Assignment$/i)",
        "button:has-text(/^Agree and Continue$/i)",
        "a:has-text(/^Continue$/i)",
        "a:has-text(/^Start Quiz$/i)",
        "a:has-text(/^Start attempt$/i)",
        "a:has-text(/^Start Attempt$/i)",
        "a:has-text(/^I agree$/i)",
        "a:has-text(/^I Agree$/i)",
        "a:has-text(/^Start Assignment$/i)",
        "a:has-text(/^Agree and Continue$/i)",
        "button[aria-label='Close']",
        "button:has-text(/^OK$/i)",
        "button:has-text(/^Close$/i)",
        "button:has-text(/^Dismiss$/i)"
    ]
    
    confirm_clicked = False
    for sel in confirm_selectors:
        try:
            btn = active_modal.locator(sel)
            if btn.count() > 0:
                for i in range(btn.count()):
                    el = btn.nth(i)
                    if el.is_visible():
                        print(f"[ENGINE] Clicking modal confirmation button: '{sel}'")
                        el.click()
                        confirm_clicked = True
                        break
            if confirm_clicked:
                break
        except Exception as e:
            print(f"[ENGINE] Error clicking modal button '{sel}': {e}")
            
    if confirm_clicked:
        scaled_sleep(3)
        return True
    return False

class PrerequisiteLoopException(Exception):
    pass

def process_syllabus_node_with_solver(
    hpage: HumanizedPage,
    node: SyllabusNode,
    api_key,
    ai_model: str,
    webhook_url: str,
    db: ACCCEStorage,
    course_id: str,
    syllabus: list,
    visited_prereqs: set = None,
    max_depth: int = 5
) -> bool:
    if visited_prereqs is None:
        visited_prereqs = set()
        
    if len(visited_prereqs) > max_depth:
        raise PrerequisiteLoopException(f"Max prerequisite dependency depth of {max_depth} exceeded. Halting to avoid loop trap.")

    print(f"[ENGINE] Target node execution routine for ID: {node.id}")
    hpage.humanized_goto(f"https://www.coursera.org/learn/{course_id}/item/{node.id}")
    
    # Allow layout stabilization
    scaled_sleep(2)
    current_url = hpage.page.url

    # Check for unauthorized redirect signature patterns
    if f"/item/{node.id}" not in current_url and "/item/" in current_url:
        try:
            redirected_id = current_url.split("/item/")[-1].split("?")[0].split("/")[0].strip()
        except Exception:
            print("[ENGINE] Failed to extract redirection ID parameters natively.")
            return False

        if redirected_id == node.id or redirected_id in visited_prereqs:
            raise PrerequisiteLoopException(f"Circular dependency anomaly identified on node index: {redirected_id}")

        print(f"[ENGINE] Lock Intercept: Node {node.id} is gated. Redirected to prerequisite: {redirected_id}.")
        
        # Create a branch-specific copy of the visited set to track the active stack path
        next_visited = set(visited_prereqs)
        next_visited.add(node.id)

        # 1. Structural Dependency Lookup Injection
        prereq_node = None
        for n in syllabus:
            if n.id == redirected_id:
                prereq_node = n
                break
                
        if not prereq_node:
            print(f"[ENGINE] System failure: Redirection target {redirected_id} missing from syllabus maps.")
            return False

        # 2. Recursive Depth-First Resolution Strategy
        # Solves nested requirements (C -> B -> A) cleanly across the call stack
        resolved = process_syllabus_node_with_solver(
            hpage, prereq_node, api_key, ai_model, webhook_url, db, course_id, syllabus, next_visited, max_depth
        )
        
        if resolved:
            print(f"[ENGINE] Prerequisite {redirected_id} completed successfully. Returning to base node {node.id}.")
            # Pop back to previous target block element location
            return process_syllabus_node_with_solver(
                hpage, node, api_key, ai_model, webhook_url, db, course_id, syllabus, visited_prereqs, max_depth
            )
        return False

    # Execute standard completion path handler automation
    return process_syllabus_node_core(hpage, node, api_key, ai_model, webhook_url, db, course_id)

def process_syllabus_node_core(
    hpage: HumanizedPage,
    node: SyllabusNode,
    api_key,
    ai_model: str,
    webhook_url: str,
    db: ACCCEStorage,
    course_id: str
) -> bool:
    """
    Core routing block handling individual nodes depending on their page type.
    Returns True if completed successfully, False otherwise.
    """
    print(f"[ENGINE] Processing node: {node.name or node.id} (Module: {node.module_name or 'Unknown'}, Type: {node.type})")
    
    if node.type == "video":
        print("[ENGINE] Video lecture detected. Emulating telemetry heartbeats...")
        for attempt in range(2):
            try:
                # First check if already completed
                if verify_node_completed_on_page(hpage, node.id):
                    return True
                
                # Check main page and frames for video elements
                video_found = False
                
                # Check main page
                try:
                    video_sel = get_selector("video_player")
                    if hpage.page.locator(video_sel).count() > 0:
                        video_found = True
                        hpage.page.evaluate('''async (sel) => {
                            const video = document.querySelector(sel);
                            if (video) {
                                video.muted = true;
                                try {
                                    await video.play();
                                } catch (e) {}
                                video.playbackRate = 16.0;
                                for (let i = 0; i < 40; i++) {
                                    if (!isNaN(video.duration) && video.duration > 0) break;
                                    await new Promise(r => setTimeout(r, 100));
                                }
                                if (!isNaN(video.duration) && video.duration > 0) {
                                    video.currentTime = video.duration - 2;
                                    for (let i = 0; i < 50; i++) {
                                        if (video.ended || video.currentTime >= video.duration - 0.5) return true;
                                        await new Promise(r => setTimeout(r, 100));
                                    }
                                }
                            }
                            return false;
                        }''', video_sel)
                        print(f"[ENGINE] Video playback initiated on main page (attempt {attempt + 1}).")
                except Exception as e:
                    print(f"[ENGINE] Main page video error: {e}")

                if not video_found:
                    # Check all frames
                    for frame in hpage.page.frames:
                        try:
                            video_sel = get_selector("video_player")
                            if frame.locator(video_sel).count() > 0:
                                video_found = True
                                frame.evaluate('''async (sel) => {
                                    const video = document.querySelector(sel);
                                    if (video) {
                                        video.muted = true;
                                        try {
                                            await video.play();
                                        } catch (e) {}
                                        video.playbackRate = 16.0;
                                        for (let i = 0; i < 40; i++) {
                                            if (!isNaN(video.duration) && video.duration > 0) break;
                                            await new Promise(r => setTimeout(r, 100));
                                        }
                                        if (!isNaN(video.duration) && video.duration > 0) {
                                            video.currentTime = video.duration - 2;
                                            for (let i = 0; i < 50; i++) {
                                                if (video.ended || video.currentTime >= video.duration - 0.5) return true;
                                                await new Promise(r => setTimeout(r, 100));
                                            }
                                        }
                                    }
                                    return false;
                                }''', video_sel)
                                print(f"[ENGINE] Video playback initiated in frame: {frame.name or frame.url} (attempt {attempt + 1}).")
                                break
                        except Exception:
                            continue

                # Try to click any visible completion buttons (sometimes videos have them)
                btn_sel = get_selector("mark_completed")
                clicked = False
                try:
                    loc = hpage.page.locator(btn_sel)
                    if loc.count() > 0 and loc.first.is_visible():
                        hpage.humanized_click(btn_sel)
                        print(f"[ENGINE] Clicked completion button '{btn_sel}' (attempt {attempt + 1}).")
                        clicked = True
                        scaled_sleep(3)
                except Exception:
                    pass

                if not video_found and not clicked:
                    print("[ENGINE] Video player not found and no click buttons. Falling back to page stay delay.")
                    poisson_sleep(5.0)
                else:
                    if not video_found:
                        scaled_sleep(4)  # Let video play remaining seconds to trigger 'ended' event

                # Verify via current page sidebar
                if verify_node_completed_on_page(hpage, node.id):
                    return True

                # If sidebar didn't update, navigate to module home page and re-check
                module_num = node.module_name.replace("Module ", "").strip() if node.module_name else "1"
                module_url = f"https://www.coursera.org/learn/{course_id}/home/module/{module_num}"
                try:
                    hpage.humanized_goto(module_url)
                    scaled_sleep(3)
                    if verify_node_completed_on_page(hpage, node.id):
                        return True
                    # Navigate back to the item page and retry
                    hpage.humanized_goto(f"https://www.coursera.org/learn/{course_id}/item/{node.id}")
                    scaled_sleep(4)
                except Exception as nav_err:
                    print(f"[ENGINE] Module page nav failed: {nav_err}")
                    hpage.humanized_goto(f"https://www.coursera.org/learn/{course_id}/item/{node.id}")
                    scaled_sleep(4)
            except Exception as e:
                print(f"[ENGINE] Video player error: {e}. Falling back to page stay delay.")
                poisson_sleep(5.0)
                if verify_node_completed_on_page(hpage, node.id):
                    return True
        return False
        
    elif node.type == "reading":
        print("[ENGINE] Reading module detected. Beginning natural human scroll...")
        hpage.humanized_scroll()
        
        # Broaden button selectors to catch all variations
        completed_btn_selectors = [
            "button:has-text('Mark as completed')",
            "button:has-text('Mark as Completed')",
            "button:has-text('I understand')",
            "button:has-text('I Understand')",
            "[data-testid='mark-complete-button']",
            ".mark-complete-button",
        ]
        for attempt in range(3):
            try:
                # First check if already completed
                if verify_node_completed_on_page(hpage, node.id):
                    return True
                
                # Try to find and click completion button
                clicked = False
                for btn_sel in completed_btn_selectors:
                    try:
                        loc = hpage.page.locator(btn_sel)
                        if loc.count() > 0 and loc.first.is_visible():
                            hpage.humanized_click(btn_sel)
                            print(f"[ENGINE] Clicked completion button '{btn_sel}' (attempt {attempt + 1}).")
                            clicked = True
                            scaled_sleep(3)
                            break
                    except Exception:
                        continue
                
                if not clicked:
                    print("[ENGINE] No visible completion button found. Staying on page for auto-completion...")
                    scaled_sleep(5)
                
                # Verify via current page sidebar first
                if verify_node_completed_on_page(hpage, node.id):
                    return True
                
                # If sidebar didn't update, navigate to module home page and re-check
                module_num = node.module_name.replace("Module ", "").strip() if node.module_name else "1"
                module_url = f"https://www.coursera.org/learn/{course_id}/home/module/{module_num}"
                try:
                    hpage.humanized_goto(module_url)
                    scaled_sleep(3)
                    if verify_node_completed_on_page(hpage, node.id):
                        return True
                    # Navigate back to the item page and retry
                    hpage.humanized_goto(f"https://www.coursera.org/learn/{course_id}/item/{node.id}")
                    scaled_sleep(4)
                    hpage.humanized_scroll()
                    scaled_sleep(2)
                except Exception as nav_err:
                    print(f"[ENGINE] Module page nav failed: {nav_err}")
                    hpage.humanized_goto(f"https://www.coursera.org/learn/{course_id}/item/{node.id}")
                    scaled_sleep(4)
            except Exception as e:
                print(f"[ENGINE] Reading error: {e}. Retrying...")
                scaled_sleep(3)
        
        # No fallback to success; we must strictly verify completion.
        print(f"[ENGINE] Could not verify reading completion for {node.id} — returning False to halt traversal.")
        return False
            
    elif node.type == "quiz":
        print("[ENGINE] Quiz assignment detected. Starting solving loop...")
        
        for attempt in range(3):
            print(f"[ENGINE] Quiz attempt {attempt + 1} of 3...")
            
            # Navigate/ensure we are on the item page
            hpage.humanized_goto(f"https://www.coursera.org/learn/{course_id}/item/{node.id}")
            scaled_sleep(4)
            
            # SPA client-side routing sync fallback:
            # If the page does not render the quiz start button or quiz container after page load,
            # locate the sidebar item link and click it to trigger client-side React routing.
            start_sel = get_selector("start_quiz_button")
            quiz_form_sel = get_selector("quiz_container")
            if hpage.page.locator(start_sel).count() == 0 and hpage.page.locator(quiz_form_sel).count() == 0:
                sidebar_selector = f'a[href*="/item/{node.id}"]'
                if hpage.page.locator(sidebar_selector).count() > 0:
                    print(f"[ENGINE] SPA Router Desync Detected. Clicking sidebar link {sidebar_selector} to force transition...")
                    try:
                        hpage.humanized_click(sidebar_selector)
                        scaled_sleep(4)
                    except Exception as click_err:
                        print(f"[ENGINE] Sidebar click fallback error: {click_err}")
            
            scaled_sleep(2)
            
            # Scroll down to make sure the start button renders
            hpage.page.evaluate('''() => {
                window.scrollTo(0, document.body.scrollHeight);
                const mainContent = document.querySelector('.rc-MainContent, main, #main');
                if (mainContent) {
                    mainContent.scrollTo(0, mainContent.scrollHeight);
                }
            }''')
            scaled_sleep(2)
            
            quiz_loaded = False
            clicked_start = False
            
            # Poll up to 30 seconds for start button or quiz form to render
            for _ in range(30):
                quiz_form_sel = get_selector("quiz_container")
                if hpage.page.locator(quiz_form_sel).count() > 0:
                    print("[ENGINE] Already inside quiz. Skipping start sequence.")
                    quiz_loaded = True
                    break
                    
                # 1. Proactive modal check: if a modal is already open on page load, handle it first
                if handle_active_modal(hpage):
                    print("[ENGINE] Active modal dismissed proactively. Checking for quiz container...")
                    scaled_sleep(2)
                    if hpage.page.locator(quiz_form_sel).count() > 0:
                        print("[ENGINE] Quiz form loaded after proactive modal dismissal.")
                        quiz_loaded = True
                        break
                    
                start_sel = get_selector("start_quiz_button")
                loc = hpage.page.locator(start_sel)
                if loc.count() > 0 and loc.first.is_visible():
                    # Wait for button to be enabled (not in loading/disabled state)
                    try:
                        is_disabled = loc.first.evaluate("el => el.disabled || el.getAttribute('aria-disabled') === 'true' || el.classList.contains('disabled')")
                        if is_disabled:
                            print(f"[ENGINE] Start button found but still loading/disabled. Waiting...")
                            scaled_sleep(1)
                            continue
                    except Exception:
                        pass
                    
                    print(f"[ENGINE] Found quiz start button. Clicking...")
                    try:
                        hpage.page.screenshot(path="C:/Users/MonMon/.gemini/antigravity/brain/65db4f7d-b03a-4068-b35d-3d812fcd9c34/debug_before_click.png")
                        print("[ENGINE] Saved debug_before_click.png screenshot.")
                    except Exception as s_err:
                        print(f"[ENGINE] Failed saving pre-click screenshot: {s_err}")
                    hpage.humanized_click(start_sel)
                    clicked_start = True
                    # Wait up to 8 seconds for quiz form to appear after start click
                    for _ in range(8):
                        scaled_sleep(1)
                        if hpage.page.locator(quiz_form_sel).count() > 0:
                            print("[ENGINE] Quiz form loaded after clicking start/resume.")
                            quiz_loaded = True
                            break
                    break
                scaled_sleep(1)
                
            if not quiz_loaded:
                # Save screenshot for debugging
                try:
                    hpage.page.screenshot(path="C:/Users/MonMon/.gemini/antigravity/brain/65db4f7d-b03a-4068-b35d-3d812fcd9c34/debug_quiz_start_failed.png")
                    print("[ENGINE] Saved debug_quiz_start_failed.png screenshot.")
                except Exception as e:
                    print(f"[ENGINE] Failed to save start screenshot: {e}")
                
            if clicked_start and not quiz_loaded:
                # 2. Reactive modal check: if modal appeared after clicking Start, handle it
                print("[ENGINE] Start clicked but quiz not loaded. Checking for modal dialogs...")
                if handle_active_modal(hpage):
                    print("[ENGINE] Active modal dismissed reactively. Checking for quiz container...")
                    scaled_sleep(2)
                    if hpage.page.locator(quiz_form_sel).count() > 0:
                        print("[ENGINE] Quiz form loaded after reactive modal dismissal.")
                        quiz_loaded = True
                    
            # Widen quiz form selector to catch newer Coursera React quiz patterns
            quiz_form_sel = get_selector("quiz_container")
            # Wait for questions to render
            try:
                hpage.page.wait_for_selector(quiz_form_sel, timeout=15000)
                print("[ENGINE] Quiz form loaded.")
                print("[ENGINE] Waiting 3 seconds for React questions and option inputs to stabilize...")
                scaled_sleep(3)
            except Exception:
                print("[ENGINE] Warning: Quiz form not detected.")
                
            payloads = extract_quiz_payloads(hpage)
            if not payloads:
                print("[ENGINE] No quiz payloads extracted. Checking if already completed...")
                
                # Check sidebar status first to see if it is completed successfully
                status_text = hpage.page.evaluate('''(nodeId) => {
                    const link = document.querySelector(`a[href*="${nodeId}"]`);
                    return link ? (link.getAttribute('aria-label') || link.textContent || '') : '';
                }''', node.id)
                print(f"[ENGINE] Sidebar status for {node.id}: '{status_text.strip()}'")
                status_lower = status_text.lower()
                
                if ("grade:" in status_lower or "completed" in status_lower) and "failed" not in status_lower:
                    print("[ENGINE] Quiz is already completed successfully based on sidebar.")
                    return True
                
                # Fallback check on landing page text
                page_text = hpage.page.evaluate("() => { const el = document.querySelector('#main-container, .rc-MainContent, main, #main'); return el ? el.textContent : ''; }")
                if any(x in page_text.lower() for x in ["congratulations", "passed"]) and "try again" not in page_text.lower() and "failed" not in page_text.lower():
                    print("[ENGINE] Quiz is already completed successfully based on landing page text.")
                    return True
                
                print("[ENGINE] Skipping attempt since no form is visible and quiz is not completed successfully.")
                continue
                
            print(f"[ENGINE] Extracted {len(payloads)} questions. Solving with LLM...")
            
            # Cache the initial sidebar status before submitting to detect when it updates
            initial_status = hpage.page.evaluate('''(nodeId) => {
                const link = document.querySelector(`a[href*="${nodeId}"]`);
                return link ? (link.getAttribute('aria-label') || link.textContent || '') : '';
            }''', node.id).strip()
            print(f"[ENGINE] Initial sidebar status before submission: '{initial_status}'")
            
            solve_quiz_with_gemini(hpage, api_key, ai_model, payloads)
            
            # Wait for grading and feedback screen to load (poll up to 40 seconds, with reloads)
            passed = False
            for poll in range(40):
                if poll > 0 and poll % 8 == 0:
                    print("[ENGINE] Polling sidebar status taking longer. Reloading page to force state update...")
                    try:
                        hpage.humanized_goto(hpage.page.url)
                        scaled_sleep(2)
                    except Exception as re_err:
                        print(f"[ENGINE] Reload/Goto failed: {re_err}")
                else:
                    scaled_sleep(1)
                
                status_text = hpage.page.evaluate('''(nodeId) => {
                    const link = document.querySelector(`a[href*="${nodeId}"]`);
                    return link ? (link.getAttribute('aria-label') || link.textContent || '') : '';
                }''', node.id).strip()
                status_lower = status_text.lower()
                print(f"[ENGINE] Polling sidebar status for {node.id}: '{status_text}'")
                
                # Check if it has completed successfully
                if ("completed" in status_lower or "grade:" in status_lower or 
                    "results pending" in status_lower or 
                    ("submitted" in status_lower and "not submitted" not in status_lower)) and "failed" not in status_lower:
                    print("[ENGINE] Quiz attempt passed based on sidebar status.")
                    passed = True
                    break
                
                # Fallback check on page content for passing indicators
                try:
                    page_text = hpage.page.evaluate("() => { const el = document.querySelector('#main-container, .rc-MainContent, main, #main'); return el ? el.textContent : ''; }").lower()
                    passing_phrases = [
                        "passed", "grade: 100%", "grade: 9", "grade: 8", "grade: 7",
                        "results pending", "submission received", "thank you for your submission",
                        "your response has been submitted", "your submission was received",
                        "you passed", "congratulations"
                    ]
                    if any(p in page_text for p in passing_phrases) and "failed" not in page_text and "try again" not in page_text:
                        print("[ENGINE] Quiz attempt passed based on page content.")
                        passed = True
                        break
                except Exception as eval_err:
                    print(f"[ENGINE] Error checking page content: {eval_err}")
            
            if passed:
                print("[ENGINE] Quiz attempt completed and passed!")
                return True
            else:
                print("[ENGINE] Quiz did not pass or not detected as completed. Retrying attempt...")
                
        print("[ENGINE] Quiz failed to pass after max attempts.")
        return False
        
    elif node.type == "lab":
        print("[ENGINE] Lab module detected. Navigating and completing...")
        
        launch_selectors = [
            "button:has-text('Launch Lab')", 
            "button:has-text('Resume')", 
            "button:has-text('Start Lab')", 
            "button:has-text('Start')", 
            "button:has-text('Open Tool')", 
            "a:has-text('Launch Lab')",
            "a:has-text('Resume')",
            "a:has-text('Start Lab')",
            "a:has-text('Open Tool')"
        ]
        
        found_launch_sel = None
        for _ in range(10):
            for sel in launch_selectors:
                if hpage.page.locator(sel).count() > 0:
                    found_launch_sel = sel
                    break
            if found_launch_sel:
                break
            scaled_sleep(1)
            
        if found_launch_sel:
            print(f"[ENGINE] Found lab launch button: '{found_launch_sel}'. Clicking...")
            try:
                # Capture the landing page tab if it opens in a new tab, or stay on same page
                landing_page = None
                try:
                    with hpage.page.context.expect_page(timeout=8000) as new_page_info:
                        hpage.humanized_click(found_launch_sel)
                    landing_page = new_page_info.value
                    print(f"[ENGINE] Lab landing page opened in a new tab: {landing_page.url}")
                except Exception:
                    # If it did not open a new page, it navigated the main page
                    print("[ENGINE] Lab did not open in new page. Staying on main page.")
                    landing_page = hpage.page
                
                scaled_sleep(8)
                
                # Check for "Mark as completed" button on the landing page
                mark_selector = "button:has-text('Mark as completed'), button:has-text('Mark as Completed')"
                for _ in range(5):
                    if landing_page.locator(mark_selector).count() > 0:
                        print("[ENGINE] Found 'Mark as completed' button. Clicking...")
                        landing_page.locator(mark_selector).first.scroll_into_view_if_needed()
                        landing_page.locator(mark_selector).first.click()
                        scaled_sleep(5)
                        print("[ENGINE] Successfully completed lab via 'Mark as completed' button.")
                        return True
                    scaled_sleep(1)
                    
                print("[ENGINE] No 'Mark as completed' button found. Attempting inline fallback...")
                return True
                
            except Exception as e:
                print(f"[ENGINE] Error completing lab: {e}")
                return False
        else:
            print("[ENGINE] Lab launch button not found. Bypassing...")
            return True
            
    elif node.type == "peer":
        print("[ENGINE] Peer review assignment detected. Pausing core script and notifying supervisor...")
        # Take verification screen screenshot
        screenshot_path = "peer_review_hold.png"
        hpage.page.screenshot(path=screenshot_path)
        
        # Save peer submission state to SQLite
        submission_id = f"sub-{node.id}-{int(time.time())}"
        db.save_peer_review(course_id, node.id, submission_id, 0, 0, "reviewing")
        
        # Alert via Discord Webhook
        send_discord_notification(
            webhook_url,
            content=f"📝 **Peer Review Hold Triggered** for course `{course_id}`. Submitted work. Scheduler will poll for peer grades.",
            screenshot_path=screenshot_path
        )
        
        # Stop execution loop (asynchronous exit)
        print("[ENGINE] Asynchronous halt. Safe exit.")
        sys.exit(0)

class TeeLogger:
    def __init__(self, filename="project_accce.log"):
        self.terminal = sys.stdout
        self.log_file = open(filename, "a", encoding="utf-8")
        
    def write(self, message):
        try:
            self.terminal.write(message)
        except UnicodeEncodeError:
            encoding = getattr(self.terminal, 'encoding', 'utf-8') or 'utf-8'
            self.terminal.write(message.encode(encoding, errors='replace').decode(encoding))
        self.log_file.write(message)
        self.log_file.flush()
        
    def flush(self):
        self.terminal.flush()
        self.log_file.flush()

def patch_playwright_driver():
    try:
        import playwright
        import re
        playwright_path = playwright.__path__[0]
        core_bundle_path = os.path.join(playwright_path, "driver", "package", "lib", "coreBundle.js")
        if os.path.exists(core_bundle_path):
            with open(core_bundle_path, "r", encoding="utf-8") as f:
                content = f.read()
            
            if "location: {" in content and "pageError.location.url" in content:
                if "location: pageError.location ?" in content:
                    return
                
                pattern = r"location:\s*\{\s*url:\s*pageError\.location\.url,\s*line:\s*pageError\.location\.lineNumber,\s*column:\s*pageError\.location\.columnNumber\s*\}"
                
                replacement = (
                    "location: pageError.location ? {\n"
                    "              url: pageError.location.url,\n"
                    "              line: pageError.location.lineNumber,\n"
                    "              column: pageError.location.columnNumber\n"
                    "            } : {\n"
                    "              url: \"\",\n"
                    "              line: 0,\n"
                    "              column: 0\n"
                    "            }"
                )
                
                if re.search(pattern, content):
                    print("[SETUP] Patching Playwright driver file 'coreBundle.js' to prevent pageError location crashes...")
                    patched_content = re.sub(pattern, replacement, content)
                    with open(core_bundle_path, "w", encoding="utf-8") as f:
                        f.write(patched_content)
                    print("[SETUP] Patching complete.")
    except Exception as e:
        print(f"[SETUP] Optional Playwright driver patch failed: {e}")

def main():
    # Defensively check stream object attributes before overriding line buffers
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(line_buffering=True)
            except Exception:
                # Fallback to direct flushing if reconfigure acts unpredictably on specific terminal layers
                pass

    parser = argparse.ArgumentParser(description="ACCCE CLI Core Controller")
    parser.add_argument("--course-id", required=True, help="Coursera course identifier string")
    parser.add_argument("--mode", default="complete", choices=["complete", "poll", "verify"], help="ACCCE running mode")
    parser.add_argument("--headless", action="store_true", help="Launch browser in headless mode")
    parser.add_argument("--db-path", default=os.path.join(app_root, "project_accce.db"), help="SQLite database file path (absolute path recommended)")
    parser.add_argument("--webhook-url", default="", help="Discord Webhook URL for HITL alerts")
    parser.add_argument("--api-key", default="", help="Gemini Pro API Key")
    parser.add_argument("--ai-model", default="gemini-flash-latest", help="LLM Model version")
    parser.add_argument("--module", type=int, default=None, help="Specific module number to complete")
    parser.add_argument("--force-rescan", action="store_true", help="Force rescan syllabus instead of loading from cache")
    parser.add_argument("--gui", action="store_true", help="Running inside PyWebView GUI wrapper")
    parser.add_argument("--speed-factor", type=float, default=1.0,
                        help="Speed multiplier: 1.0=Safe (human-like), 0.4=Balanced, 0.1=Turbo (max speed)")
    
    # Parse known args early to determine if we are running in GUI mode
    args, unknown = parser.parse_known_args()
    
    # In GUI mode, gui_backend.py handles output redirection to the log file.
    # Otherwise (CLI mode), we initialize TeeLogger to save output logs.
    if not args.gui:
        logger = TeeLogger("project_accce.log")
        sys.stdout = logger
        sys.stderr = logger
        
    patch_playwright_driver()
    fetch_layout_map()
    
    # Parse args fully to enforce required flags and constraints
    args = parser.parse_args()
    
    # Automatically clean course URL to extract the course ID slug
    if "coursera.org/learn/" in args.course_id:
        args.course_id = args.course_id.split("/learn/")[-1].split("/")[0].strip()
    
    # Load config.json defaults — prefer the stable APPDATA path written by the GUI
    config_data = {}
    config_candidates = []
    if app_root_override:
        config_candidates.append(os.path.join(app_root_override, "config.json"))
    config_candidates.append(os.path.join(app_root, "config.json"))
    config_candidates.append("config.json")  # CWD fallback
    for cfg_path in config_candidates:
        if os.path.exists(cfg_path):
            try:
                with open(cfg_path, "r") as f:
                    config_data = json.load(f)
                break
            except Exception:
                pass

    api_key = args.api_key or config_data.get("api_keys", config_data.get("api_key", "")) or os.getenv("GEMINI_API_KEY", "")
    webhook_url = args.webhook_url or config_data.get("webhook_url", "")
    
    ai_model = args.ai_model
    if args.ai_model == "gemini-flash-latest" and "ai_model" in config_data:
        ai_model = config_data["ai_model"]

    # Apply speed factor globally — scales all time.sleep() / poisson_sleep() calls
    speed_factor = args.speed_factor
    set_speed_factor(speed_factor)
    speed_label = {1.0: "Safe (Human-Like)", 0.4: "Balanced", 0.1: "Turbo"}.get(
        round(speed_factor, 1), f"Custom ({speed_factor}x)"
    )
    print(f"[ENGINE] Completion speed mode: {speed_label} (factor={speed_factor})")

    if args.mode == "poll":
        # Cron gradebook polling mode
        run_gradebook_polling_cycle(args.db_path, webhook_url)
        return

    # Create storage layer
    db = ACCCEStorage(args.db_path)
    
    # Initialize Stealth Browser (Layer 1)
    user_data_dir = os.path.join(app_root, "chrome_sessions", args.course_id)
    
    print("[ENGINE] Initializing stealth browser context...")
    with launch_stealth_browser(headless=args.headless, user_data_dir=user_data_dir) as browser:
        if browser.pages:
            page = browser.pages[0]
        else:
            page = browser.new_page()
            
        page.set_viewport_size({"width": 1280, "height": 800})
        # Automatically mute all audio/video playbacks on the page context
        page.add_init_script("() => { window.addEventListener('play', (e) => { e.target.muted = true; }, true); }")
        hpage = HumanizedPage(page)
        
        # Perform session restore if SQLite has valid cookies
        session = db.get_session(args.course_id)
        if not (session and session.get("cookies")):
            # Fall back to any active session cookies from other courses in the DB
            print("[ENGINE] No session cookies found for this course. Attempting to locate active cookies from other courses...")
            conn = db._get_connection()
            try:
                row = conn.execute("SELECT cookies_json FROM sessions WHERE cookies_json IS NOT NULL LIMIT 1").fetchone()
                if row and row["cookies_json"]:
                    cookies = json.loads(row["cookies_json"])
                    print("[ENGINE] Restoring existing cookies from a historical session in storage...")
                    browser.add_cookies(cookies)
            except Exception as e:
                print(f"[ENGINE] Session fallback error: {e}")
            finally:
                conn.close()
        else:
            print("[ENGINE] Restoring existing cookies from storage...")
            browser.add_cookies(session["cookies"])
            
        print("[ENGINE] Navigating to course homepage...")
        hpage.humanized_goto(f"https://www.coursera.org/learn/{args.course_id}/home/welcome")
        
        # Save session cookies/tokens post navigation
        db.save_session(args.course_id, browser.cookies(), {})
        
        # Allow React elements on welcome page to stabilize and fetch API data
        print("[ENGINE] Waiting 5 seconds for page content to load and stabilize...")
        time.sleep(5)
        
        # Wait for the user to log in if they are not logged in.
        print("[ENGINE] Waiting for account session activation (please complete login in the browser if prompted)...")
        for attempt in range(300): # Wait up to 5 minutes for user login
            has_syllabus = page.evaluate('''(courseId) => {
                const pattern = new RegExp(`\\/learn\\/${courseId}\\/(lecture|supplement|exam|peer|item|lti|ungradedLtiHistory|ungradedWidget)\\/`);
                return Array.from(document.querySelectorAll('a')).some(a => pattern.test(a.href));
            }''', args.course_id)
            if has_syllabus:
                print("[ENGINE] Session active! Syllabus elements detected.")
                break
                
            # Check for Enroll/Enroll for free button and click it
            sel = get_selector("enroll_button")
            loc = page.locator(sel)
            if loc.count() > 0 and loc.first.is_visible():
                print(f"[ENGINE] Found enrollment button. Clicking...")
                try:
                    try:
                        loc.first.click(timeout=6000)
                    except Exception:
                        print("[ENGINE] Main enrollment button click intercepted or timed out. Falling back to JS click...")
                        loc.first.evaluate("el => el.click()")
                    time.sleep(4)
                    
                    # Check if a confirmation modal opened and click "Go to course" / "Enroll"
                    sub_sel = get_selector("enroll_modal_button")
                    sub_loc = page.locator(sub_sel)
                    if sub_loc.count() > 0 and sub_loc.first.is_visible():
                        print(f"[ENGINE] Clicking modal enrollment button...")
                        try:
                            sub_loc.first.click(timeout=6000)
                        except Exception:
                            print("[ENGINE] Modal enrollment button click intercepted or timed out. Falling back to JS click...")
                            sub_loc.first.evaluate("el => el.click()")
                        time.sleep(4)
                except Exception as e:
                    print(f"[ENGINE] Error clicking enrollment button: {e}")
                    
            time.sleep(1.5)
        else:
            print("[ENGINE] Timeout waiting for session authorization. Please run again and complete login.")
            sys.exit(1)

        syllabus = []
        cached_loaded = False
        course_state = db.get_course_state(args.course_id)
        
        if not args.force_rescan:
            if course_state and course_state.get("syllabus_nodes"):
                # Check cache expiration tag to guarantee curriculum integrity (7 days max)
                cache_age_days = (time.time() - course_state.get("updated_at", 0)) / (24 * 3600)
                if cache_age_days <= 7:
                    print(f"[ENGINE] Fast Resume: Found valid cached syllabus with {len(course_state['syllabus_nodes'])} items (Cache age: {cache_age_days:.1f} days). Bypassing module scan.")
                    for node_data in course_state["syllabus_nodes"]:
                        syllabus.append(SyllabusNode(**node_data))
                    cached_loaded = True
                else:
                    print(f"[ENGINE] Syllabus cache is stale ({cache_age_days:.1f} days > 7 days). Scheduling automatic rescan.")
            else:
                print("[ENGINE] No cached syllabus found. Initiating dynamic module scan...")
        else:
            print("[ENGINE] Force rescan requested. Purging cached syllabus and initiating scan...")
            
        if not cached_loaded:
            print("[ENGINE] Dynamically extracting course syllabus items across all modules...")
            extracted_ids = set()
            modules_to_scan = [args.module] if args.module else range(1, 10)
            
            for m_idx in modules_to_scan:
                module_url = f"https://www.coursera.org/learn/{args.course_id}/home/module/{m_idx}"
                print(f"[ENGINE] Scanning module {m_idx} page: {module_url}")
                hpage.humanized_goto(module_url)
                
                try:
                    # Target actual syllabus item links (not just course homepage or sidebar links)
                    syllabus_types = ["lecture", "supplement", "exam", "peer", "item", "lti", "ungradedLtiHistory", "ungradedLab", "assignment-submission", "ungradedWidget"]
                    sel = ", ".join(f"a[href*='/{t}/']" for t in syllabus_types)
                    page.wait_for_selector(sel, timeout=12000)
                    time.sleep(2.5) # Extra buffer for elements to stabilize
                except Exception as wait_err:
                    print(f"[ENGINE] Warning: Timeout waiting for syllabus links on module {m_idx}: {wait_err}")
                    time.sleep(4)
                
                # If redirected away, it means this week/module does not exist
                if f"/home/module/{m_idx}" not in page.url:
                    print(f"[ENGINE] Module {m_idx} not found (redirected to {page.url}). Stopping module scan.")
                    break
                    
                extracted_nodes = page.evaluate('''(args) => {
                    const courseId = args.courseId;
                    const mIdx = args.mIdx;
                    const items = [];
                    
                    // Extract module name from sidebar link text, fallback to "Module " + mIdx
                    let mName = `Module ${mIdx}`;
                    const sidebarLink = document.querySelector(`a[href*="/learn/${courseId}/home/module/${mIdx}"]`);
                    if (sidebarLink) {
                        mName = sidebarLink.textContent.trim();
                    }
                    
                    const anchors = Array.from(document.querySelectorAll('a'));
                    const pattern = new RegExp(`\\/learn\\/${courseId}\\/(lecture|supplement|exam|peer|item|lti|ungradedLtiHistory|ungradedLab|assignment-submission|ungradedWidget)\\/([a-zA-Z0-9_-]+)`);
                    
                    anchors.forEach(a => {
                        const match = a.href.match(pattern);
                        if (match) {
                            const type_map = {
                                "lecture": "video",
                                "supplement": "reading",
                                "exam": "quiz",
                                "peer": "peer",
                                "item": "reading",
                                "lti": "lab",
                                "ungradedLtiHistory": "lab",
                                "ungradedLab": "lab",
                                "assignment-submission": "quiz",
                                "ungradedWidget": "reading"
                            };
                            const raw_type = match[1];
                            const item_id = match[2];
                            
                            // Extract and clean lesson name
                            let cleanName = "";
                            const pEl = a.querySelector('p');
                            if (pEl) {
                                cleanName = pEl.textContent.trim();
                            } else {
                                // Fallback text cleaning
                                cleanName = a.textContent.replace(/Completed/g, '').split(/[·•]/)[0].trim();
                            }
                            
                            // Check for completed status
                            let isCompleted = false;
                            if (a.textContent.includes("Completed")) {
                                isCompleted = true;
                            } else if (a.querySelector('[data-testid="learn-item-success-icon"]')) {
                                isCompleted = true;
                            } else {
                                const svgEl = a.querySelector('svg');
                                if (svgEl) {
                                    // Evaluate accessibility properties cleanly across structural attributes
                                    const ariaLabel = svgEl.getAttribute('aria-label') || '';
                                    const hasSuccessClass = svgEl.classList.contains('css-1cdzuc5');
                                    
                                    if (ariaLabel.toLowerCase().includes('completed') || hasSuccessClass) {
                                        isCompleted = true;
                                    }
                                }
                            }
                            
                            if (!items.some(it => it.id === item_id)) {
                                items.push({
                                    id: item_id,
                                    type: type_map[raw_type] || "reading",
                                    name: cleanName || item_id,
                                    module_name: mName,
                                    is_completed: isCompleted
                                });
                            }
                        }
                    });
                    return items;
                }''', {"courseId": args.course_id, "mIdx": m_idx})
                
                if not extracted_nodes:
                    print(f"[ENGINE] No syllabus nodes found in module {m_idx}. Stopping module scan.")
                    break
                    
                module_added_count = 0
                for item in extracted_nodes:
                    if item["id"] not in extracted_ids:
                        syllabus.append(SyllabusNode(**item))
                        extracted_ids.add(item["id"])
                        module_added_count += 1
                print(f"[ENGINE] Extracted {len(extracted_nodes)} nodes ({module_added_count} new) in module {m_idx}")
                
                if module_added_count == 0:
                    print(f"[ENGINE] No new nodes found. Stopping module scan early.")
                    break
                
            print(f"[ENGINE] Total course syllabus items extracted: {len(syllabus)}")
            
            # Save initial course state
            db.save_course_state(args.course_id, None, [], [n.model_dump() for n in syllabus])
            
            # Refresh course state reference post scan
            course_state = db.get_course_state(args.course_id)
        
        # Load existing completed nodes from database if present
        completed_nodes = []
        if course_state and course_state.get("completed_nodes"):
            completed_nodes = course_state["completed_nodes"]
            
        if not cached_loaded:
            # Synchronize completed nodes using Coursera's live syllabus state as the source of truth
            syllabus_completed_ids = {n.id for n in syllabus if n.is_completed}
            syllabus_all_ids = {n.id for n in syllabus}
            
            for node_id in syllabus_completed_ids:
                if node_id not in completed_nodes:
                    completed_nodes.append(node_id)
            print(f"[ENGINE] Synchronized completed nodes from live Coursera state. Total completed: {len(completed_nodes)}")
            
            # Keep any historical completed nodes from DB that are not in the currently scanned syllabus
            if course_state and course_state.get("completed_nodes"):
                for node_id in course_state["completed_nodes"]:
                    if node_id not in syllabus_all_ids and node_id not in completed_nodes:
                        completed_nodes.append(node_id)
                        print(f"[ENGINE] Retaining historical completed node from DB: {node_id}")
        else:
            print(f"[ENGINE] Using cached completed nodes history. Total completed: {len(completed_nodes)}")
            
        # Save initial course state with combined completed nodes
        db.save_course_state(args.course_id, None, completed_nodes, [n.model_dump() for n in syllabus])
        
        # Run syllabus traversal
        for node in syllabus:
            if node.id in completed_nodes:
                print(f"[ENGINE] Skipping completed node: {node.name or node.id}")
                continue
                
            # Update current active node in SQLite
            db.save_course_state(args.course_id, node.id, completed_nodes, [n.model_dump() for n in syllabus])
            
            success = process_syllabus_node_with_solver(hpage, node, api_key, ai_model, webhook_url, db, args.course_id, syllabus)
            if success:
                completed_nodes.append(node.id)
                print(f"[ENGINE] Node {node.name or node.id} completed successfully and added to DB progress.")
            else:
                print(f"[ENGINE] CRITICAL: Syllabus node '{node.name}' (ID: {node.id}, Type: {node.type}) failed to complete or verify! Traversal halted.")
                raise RuntimeError(f"CRITICAL: Syllabus node '{node.name}' (ID: {node.id}, Type: {node.type}) failed to complete and verify! Traversal halted.")
                
            # Save updated cookies and state after completing each node
            db.save_session(args.course_id, browser.cookies(), {})
            db.save_course_state(args.course_id, None, completed_nodes, [n.model_dump() for n in syllabus])
            
            # Poisson interval sleep between syllabus items
            print("[ENGINE] Node complete. Entering Poisson sleep interval...")
            poisson_sleep(4.0)

if __name__ == "__main__":
    main()
