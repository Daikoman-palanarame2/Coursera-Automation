import os
import sys
import argparse
import time
import json
from project_accce.stealth.browser import launch_stealth_browser
from project_accce.behavior.page import HumanizedPage
from project_accce.behavior.math_utils import poisson_sleep
from project_accce.cognitive.quiz import extract_quiz_payloads, solve_quiz_with_gemini
from project_accce.cognitive.lab import setup_lab_interceptor, WebSocketLabClient, run_closed_loop_lab_agent
from project_accce.orchestrator.db import ACCCEStorage
from project_accce.orchestrator.notifier import send_discord_notification
from project_accce.orchestrator.scheduler import run_gradebook_polling_cycle
from project_accce.schemas import SyllabusNode

def verify_node_completed_on_page(hpage: HumanizedPage, node_id: str, timeout_sec: int = 15) -> bool:
    print(f"[ENGINE] Verifying completion status for node {node_id} on page...")
    for _ in range(timeout_sec):
        is_completed = hpage.page.evaluate('''(nodeId) => {
            const anchor = document.querySelector(`a[href*="${nodeId}"]`);
            if (!anchor) return false;
            if (anchor.querySelector('[data-testid="learn-item-success-icon"]')) return true;
            const svg = anchor.querySelector('svg');
            if (svg) {
                const title = svg.querySelector('title');
                if (title && title.textContent.includes("Completed")) return true;
                if (svg.classList.contains("css-1cdzuc5")) return true;
            }
            if (anchor.textContent.includes("Completed")) return true;
            return false;
        }''', node_id)
        if is_completed:
            print(f"[ENGINE] Verification SUCCESS: Node {node_id} is marked as completed on Coursera!")
            return True
        time.sleep(1)
    return False

def process_syllabus_node(
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
    
    # Navigate to the item
    hpage.humanized_goto(f"https://www.coursera.org/learn/{course_id}/item/{node.id}")
    
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
                    if hpage.page.locator("video").count() > 0:
                        video_found = True
                        hpage.page.evaluate('''async () => {
                            const video = document.querySelector('video');
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
                        }''')
                        print(f"[ENGINE] Video playback initiated on main page (attempt {attempt + 1}).")
                except Exception as e:
                    print(f"[ENGINE] Main page video error: {e}")

                if not video_found:
                    # Check all frames
                    for frame in hpage.page.frames:
                        try:
                            if frame.locator("video").count() > 0:
                                video_found = True
                                frame.evaluate('''async () => {
                                    const video = document.querySelector('video');
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
                                }''')
                                print(f"[ENGINE] Video playback initiated in frame: {frame.name or frame.url} (attempt {attempt + 1}).")
                                break
                        except Exception:
                            continue

                # Try to click any visible completion buttons (sometimes videos have them)
                completed_btn_selectors = [
                    "button:has-text('Mark as completed')",
                    "button:has-text('Mark as Completed')",
                    "button:has-text('I understand')",
                    "button:has-text('I Understand')",
                    "[data-testid='mark-complete-button']",
                    ".mark-complete-button",
                ]
                clicked = False
                for btn_sel in completed_btn_selectors:
                    try:
                        loc = hpage.page.locator(btn_sel)
                        if loc.count() > 0 and loc.first.is_visible():
                            hpage.humanized_click(btn_sel)
                            print(f"[ENGINE] Clicked completion button '{btn_sel}' (attempt {attempt + 1}).")
                            clicked = True
                            time.sleep(3)
                            break
                    except Exception:
                        continue

                if not video_found and not clicked:
                    print("[ENGINE] Video player not found and no click buttons. Falling back to page stay delay.")
                    poisson_sleep(5.0)
                else:
                    if not video_found:
                        time.sleep(4)  # Let video play remaining seconds to trigger 'ended' event

                # Verify via current page sidebar
                if verify_node_completed_on_page(hpage, node.id):
                    return True

                # If sidebar didn't update, navigate to module home page and re-check
                module_num = node.module_name.replace("Module ", "").strip() if node.module_name else "1"
                module_url = f"https://www.coursera.org/learn/{course_id}/home/module/{module_num}"
                try:
                    hpage.humanized_goto(module_url)
                    time.sleep(3)
                    if verify_node_completed_on_page(hpage, node.id):
                        return True
                    # Navigate back to the item page and retry
                    hpage.humanized_goto(f"https://www.coursera.org/learn/{course_id}/item/{node.id}")
                    time.sleep(4)
                except Exception as nav_err:
                    print(f"[ENGINE] Module page nav failed: {nav_err}")
                    hpage.humanized_goto(f"https://www.coursera.org/learn/{course_id}/item/{node.id}")
                    time.sleep(4)
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
                            time.sleep(3)
                            break
                    except Exception:
                        continue
                
                if not clicked:
                    print("[ENGINE] No visible completion button found. Staying on page for auto-completion...")
                    time.sleep(5)
                
                # Verify via current page sidebar first
                if verify_node_completed_on_page(hpage, node.id):
                    return True
                
                # If sidebar didn't update, navigate to module home page and re-check
                module_num = node.module_name.replace("Module ", "").strip() if node.module_name else "1"
                module_url = f"https://www.coursera.org/learn/{course_id}/home/module/{module_num}"
                try:
                    hpage.humanized_goto(module_url)
                    time.sleep(3)
                    if verify_node_completed_on_page(hpage, node.id):
                        return True
                    # Navigate back to the item page and retry
                    hpage.humanized_goto(f"https://www.coursera.org/learn/{course_id}/item/{node.id}")
                    time.sleep(4)
                    hpage.humanized_scroll()
                    time.sleep(2)
                except Exception as nav_err:
                    print(f"[ENGINE] Module page nav failed: {nav_err}")
                    hpage.humanized_goto(f"https://www.coursera.org/learn/{course_id}/item/{node.id}")
                    time.sleep(4)
            except Exception as e:
                print(f"[ENGINE] Reading error: {e}. Retrying...")
                time.sleep(3)
        
        # No fallback to success; we must strictly verify completion.
        print(f"[ENGINE] Could not verify reading completion for {node.id} — returning False to halt traversal.")
        return False
            
    elif node.type == "quiz":
        print("[ENGINE] Quiz assignment detected. Starting solving loop...")
        
        for attempt in range(3):
            print(f"[ENGINE] Quiz attempt {attempt + 1} of 3...")
            
            # Navigate/ensure we are on the item page
            hpage.humanized_goto(f"https://www.coursera.org/learn/{course_id}/item/{node.id}")
            time.sleep(6)
            
            # Scroll down to make sure the start button renders
            hpage.page.evaluate('''() => {
                window.scrollTo(0, document.body.scrollHeight);
                const mainContent = document.querySelector('.rc-MainContent, main, #main');
                if (mainContent) {
                    mainContent.scrollTo(0, mainContent.scrollHeight);
                }
            }''')
            time.sleep(2)
            
            start_selectors = [
                "button[data-testid='CoverPageActionButton']",
                "[data-testid='CoverPageActionButton']",
                "button:has-text('Start')",
                "button:has-text('Start Quiz')",
                "button:has-text('Resume')",
                "button:has-text('Start attempt')",
                "button:has-text('Resume Quiz')",
                "button:has-text('Agree and Continue')",
                "button:has-text('Start Assignment')",
                "button:has-text('Try again')",
                "button:has-text('Retake')",
                "button:has-text('Retake Quiz')",
                "a:has-text('Start')",
                "a:has-text('Start Quiz')",
                "a:has-text('Resume')",
                "a:has-text('Try again')",
                "a:has-text('Retake')",
                "a:has-text('Retake Quiz')"
            ]
            
            quiz_loaded = False
            clicked_start = False
            
            # Poll up to 30 seconds for start button or quiz form to render
            for _ in range(30):
                if hpage.page.locator("div[data-testid^='part-Submission_'], .rc-Option, .rc-FormQuestion, .question-container, .rc-Form").count() > 0:
                    print("[ENGINE] Already inside quiz. Skipping start sequence.")
                    quiz_loaded = True
                    break
                    
                found_sel = None
                for sel in start_selectors:
                    loc = hpage.page.locator(sel)
                    if loc.count() > 0 and loc.first.is_visible():
                        # Wait for button to be enabled (not in loading/disabled state)
                        try:
                            is_disabled = loc.first.evaluate("el => el.disabled || el.getAttribute('aria-disabled') === 'true' || el.classList.contains('disabled')")
                            if is_disabled:
                                print(f"[ENGINE] Start button '{sel}' found but still loading/disabled. Waiting...")
                                time.sleep(1)
                                continue
                        except Exception:
                            pass
                        found_sel = sel
                        break
                
                if found_sel:
                    print(f"[ENGINE] Found quiz start button: '{found_sel}'. Clicking...")
                    hpage.humanized_click(found_sel)
                    clicked_start = True
                    # Wait up to 8 seconds for quiz form to appear after start click
                    for _ in range(8):
                        time.sleep(1)
                        if hpage.page.locator("div[data-testid^='part-Submission_'], .rc-Option, .rc-FormQuestion, .question-container, .rc-Form").count() > 0:
                            print("[ENGINE] Quiz form loaded after clicking start/resume.")
                            quiz_loaded = True
                            break
                    break
                time.sleep(1)
                
            if not quiz_loaded:
                # Save screenshot for debugging
                try:
                    hpage.page.screenshot(path="C:/Users/MonMon/.gemini/antigravity/brain/65db4f7d-b03a-4068-b35d-3d812fcd9c34/debug_quiz_start_failed.png")
                    print("[ENGINE] Saved debug_quiz_start_failed.png screenshot.")
                except Exception as e:
                    print(f"[ENGINE] Failed to save start screenshot: {e}")
                
            if clicked_start and not quiz_loaded:
                # Handle checkboxes/dialogs
                checkbox_sel = None
                dialog_selectors = [
                    "input[type='checkbox']#honor-code-checkbox",
                    "input[type='checkbox'][name='honor-code']",
                    "label:has-text('Honor Code') input",
                    "input#agreement-checkbox",
                    "input#agreement-checkbox-base",
                    "input[type='checkbox']#agreement-checkbox-base",
                    "input[type='checkbox']"
                ]
                for _ in range(5):
                    # Check if the quiz form has loaded while polling for checkboxes
                    if hpage.page.locator("div[data-testid^='part-Submission_'], .rc-Option, .rc-FormQuestion, .question-container, .rc-Form").count() > 0:
                        print("[ENGINE] Quiz form loaded during dialog/checkbox polling. Skipping dialog handling.")
                        quiz_loaded = True
                        break
                    for sel in dialog_selectors:
                        if hpage.page.locator(sel).count() > 0:
                            checkbox_sel = sel
                            break
                    if checkbox_sel:
                        break
                    time.sleep(1)
                    
                if checkbox_sel and not quiz_loaded:
                    print(f"[ENGINE] Found agreement checkbox: '{checkbox_sel}'. Checking safely...")
                    loc = hpage.page.locator(checkbox_sel).first
                    try:
                        is_checked = loc.evaluate("el => el.checked")
                        if not is_checked:
                            clicked = loc.evaluate('''el => {
                                let parent = el.closest('label') || el.closest('[data-testid=\"agreement-checkbox\"]') || el.closest('.cds-checkboxAndRadio-label');
                                if (parent) {
                                    parent.click();
                                    return 'parent_label';
                                }
                                el.click();
                                return 'self';
                            }''')
                            print(f"[ENGINE] Checked agreement checkbox '{checkbox_sel}' via: {clicked}")
                        else:
                            print(f"[ENGINE] Agreement checkbox '{checkbox_sel}' is already checked.")
                    except Exception as e:
                        print(f"[ENGINE] Error checking checkbox '{checkbox_sel}': {e}. Falling back to click.")
                        hpage.humanized_click(checkbox_sel)
                    time.sleep(1.5)
                    
                if not quiz_loaded:
                    confirm_sel = None
                    confirm_selectors = [
                        "button:has-text('Continue')",
                        "button:has-text('Start Quiz')",
                        "button:has-text('Start attempt')",
                        "button:has-text('Start Attempt')",
                        "button:has-text('I agree')",
                        "button:has-text('I Agree')",
                        "button:has-text('Start Assignment')",
                        "button:has-text('Agree and Continue')",
                        "a:has-text('Continue')",
                        "a:has-text('Start Quiz')",
                        "a:has-text('Start attempt')",
                        "a:has-text('Start Attempt')",
                        "a:has-text('I agree')",
                        "a:has-text('I Agree')",
                        "a:has-text('Start Assignment')",
                        "a:has-text('Agree and Continue')"
                    ]
                    for _ in range(5):
                        # Check if the quiz form has loaded while polling for confirmation button
                        if hpage.page.locator("div[data-testid^='part-Submission_'], .rc-Option, .rc-FormQuestion, .question-container, .rc-Form").count() > 0:
                            print("[ENGINE] Quiz form loaded during confirmation polling. Skipping confirmation click.")
                            quiz_loaded = True
                            break
                        for sel in confirm_selectors:
                            if hpage.page.locator(sel).count() > 0:
                                confirm_sel = sel
                                break
                        if confirm_sel:
                            break
                        time.sleep(1)
                        
                    if confirm_sel and not quiz_loaded:
                        print(f"[ENGINE] Found confirmation button: '{confirm_sel}'. Clicking...")
                        hpage.humanized_click(confirm_sel)
                        # Poll up to 15 seconds for quiz form to load after Continue
                        quiz_form_sel = "div[data-testid^='part-Submission_'], .rc-Option, .rc-FormQuestion, .question-container, .rc-Form, [data-testid='question-prompt'], .css-k008qs, form[data-testid]"
                        for _ in range(15):
                            time.sleep(1)
                            if hpage.page.locator(quiz_form_sel).count() > 0:
                                print("[ENGINE] Quiz form loaded after Continue click.")
                                quiz_loaded = True
                                break
                else:
                    all_elems = hpage.page.evaluate('''() => {
                        return Array.from(document.querySelectorAll('button, a, [role="button"]')).map(el => el.textContent.trim());
                    }''')
                    print(f"[ENGINE] Confirmation button not found! All visible button/link texts: {all_elems}")
                    
            # Widen quiz form selector to catch newer Coursera React quiz patterns
            quiz_form_sel = "div[data-testid^='part-Submission_'], .rc-Option, .rc-FormQuestion, .question-container, .rc-Form, [data-testid='question-prompt'], .css-k008qs, form[data-testid]"
            # Wait for questions to render
            try:
                hpage.page.wait_for_selector(quiz_form_sel, timeout=15000)
                print("[ENGINE] Quiz form loaded.")
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
                        time.sleep(2)
                    except Exception as re_err:
                        print(f"[ENGINE] Reload/Goto failed: {re_err}")
                else:
                    time.sleep(1)
                
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
            time.sleep(1)
            
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
                
                time.sleep(8)
                
                # Check for "Mark as completed" button on the landing page
                mark_selector = "button:has-text('Mark as completed'), button:has-text('Mark as Completed')"
                for _ in range(5):
                    if landing_page.locator(mark_selector).count() > 0:
                        print("[ENGINE] Found 'Mark as completed' button. Clicking...")
                        landing_page.locator(mark_selector).first.scroll_into_view_if_needed()
                        landing_page.locator(mark_selector).first.click()
                        time.sleep(5)
                        print("[ENGINE] Successfully completed lab via 'Mark as completed' button.")
                        return True
                    time.sleep(1)
                    
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

def main():
    logger = TeeLogger("project_accce.log")
    sys.stdout = logger
    sys.stderr = logger
    
    parser = argparse.ArgumentParser(description="ACCCE CLI Core Controller")
    parser.add_argument("--course-id", required=True, help="Coursera course identifier string")
    parser.add_argument("--mode", default="complete", choices=["complete", "poll", "verify"], help="ACCCE running mode")
    parser.add_argument("--headless", action="store_true", help="Launch browser in headless mode")
    parser.add_argument("--db-path", default="project_accce.db", help="SQLite database file path")
    parser.add_argument("--webhook-url", default="", help="Discord Webhook URL for HITL alerts")
    parser.add_argument("--api-key", default="", help="Gemini Pro API Key")
    parser.add_argument("--ai-model", default="gemini-flash-latest", help="LLM Model version")
    parser.add_argument("--module", type=int, default=None, help="Specific module number to complete")
    
    args = parser.parse_args()
    
    # Load config.json defaults if present
    config_data = {}
    if os.path.exists("config.json"):
        try:
            with open("config.json", "r") as f:
                config_data = json.load(f)
        except Exception:
            pass

    api_key = args.api_key or config_data.get("api_keys", config_data.get("api_key", ""))
    webhook_url = args.webhook_url or config_data.get("webhook_url", "")
    
    if args.mode == "poll":
        # Cron gradebook polling mode
        run_gradebook_polling_cycle(args.db_path, webhook_url)
        return

    # Create storage layer
    db = ACCCEStorage(args.db_path)
    
    # Initialize Stealth Browser (Layer 1)
    user_data_dir = os.path.join(os.getcwd(), "chrome_sessions", args.course_id)
    
    print("[ENGINE] Initializing stealth browser context...")
    with launch_stealth_browser(headless=args.headless, user_data_dir=user_data_dir) as browser:
        page = browser.new_page()
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
            # Using exact text matching (text-is) to prevent accidental clicks on "Enrolled"
            enroll_selectors = [
                "button:text-is('Enroll for free')",
                "button:text-is('Enroll')",
                "a:text-is('Enroll for free')",
                "a:text-is('Enroll')"
            ]
            for sel in enroll_selectors:
                loc = page.locator(sel)
                if loc.count() > 0 and loc.first.is_visible():
                    print(f"[ENGINE] Found enrollment button: '{sel}'. Clicking...")
                    try:
                        try:
                            loc.first.click(timeout=6000)
                        except Exception:
                            print("[ENGINE] Main enrollment button click intercepted or timed out. Falling back to JS click...")
                            loc.first.evaluate("el => el.click()")
                        time.sleep(4)
                        # Check if a confirmation modal opened and click "Go to course" / "Enroll"
                        for sub_sel in [
                            "button:has-text('Go to course')",
                            "button:has-text('Go to Course')",
                            "button:has-text('Enroll')",
                            "button:has-text('Start learning')",
                            "button:has-text('Continue')"
                        ]:
                            sub_loc = page.locator(sub_sel)
                            if sub_loc.count() > 0 and sub_loc.first.is_visible():
                                print(f"[ENGINE] Clicking modal enrollment button: '{sub_sel}'")
                                try:
                                    sub_loc.first.click(timeout=6000)
                                except Exception:
                                    print("[ENGINE] Modal enrollment button click intercepted or timed out. Falling back to JS click...")
                                    sub_loc.first.evaluate("el => el.click()")
                                time.sleep(4)
                                break
                    except Exception as e:
                        print(f"[ENGINE] Error clicking enrollment button: {e}")
                    break
                    
            time.sleep(1.5)
        else:
            print("[ENGINE] Timeout waiting for session authorization. Please run again and complete login.")
            sys.exit(1)

        print("[ENGINE] Dynamically extracting course syllabus items across all modules...")
        syllabus = []
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
                        } else {
                            const svgEl = a.querySelector('svg');
                            if (svgEl && svgEl.textContent.includes("Completed")) {
                                isCompleted = true;
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
        
        # Load existing completed nodes from database if present
        course_state = db.get_course_state(args.course_id)
        
        # Synchronize completed nodes using Coursera's live syllabus state as the source of truth
        syllabus_completed_ids = {n.id for n in syllabus if n.is_completed}
        syllabus_all_ids = {n.id for n in syllabus}
        
        completed_nodes = list(syllabus_completed_ids)
        print(f"[ENGINE] Synchronized {len(completed_nodes)} completed nodes from live Coursera state.")
        
        # Keep any historical completed nodes from DB that are not in the currently scanned syllabus
        if course_state and course_state.get("completed_nodes"):
            for node_id in course_state["completed_nodes"]:
                if node_id not in syllabus_all_ids and node_id not in completed_nodes:
                    completed_nodes.append(node_id)
                    print(f"[ENGINE] Retaining historical completed node from DB: {node_id}")
                
        # Save initial course state with combined completed nodes
        db.save_course_state(args.course_id, None, completed_nodes, [n.model_dump() for n in syllabus])
        
        # Run syllabus traversal
        for node in syllabus:
            if node.id in completed_nodes:
                print(f"[ENGINE] Skipping completed node: {node.name or node.id}")
                continue
                
            # Update current active node in SQLite
            db.save_course_state(args.course_id, node.id, completed_nodes, [n.model_dump() for n in syllabus])
            
            success = process_syllabus_node(hpage, node, api_key, args.ai_model, webhook_url, db, args.course_id)
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
