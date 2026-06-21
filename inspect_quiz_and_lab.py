import os
import sys
import time
import sqlite3
import json
from project_accce.stealth.browser import launch_stealth_browser
from project_accce.orchestrator.db import ACCCEStorage

def main():
    db = ACCCEStorage("project_accce.db")
    course_id = "react-basics"
    user_data_dir = os.path.join(os.getcwd(), "chrome_sessions", course_id)
    
    # Let's inspect "Knowledge check: Data flow" (Quiz ID: r83Ux)
    # And "React Counter App" (Lab ID: Gmiey)
    inspect_nodes = [
        {"id": "r83Ux", "type": "quiz", "name": "Knowledge check: Data flow"},
        {"id": "Gmiey", "type": "lab", "name": "React Counter App: Handling Events with useState"}
    ]
    
    print("Launching stealth browser...")
    with launch_stealth_browser(headless=True, user_data_dir=user_data_dir) as browser:
        page = browser.new_page()
        
        # Load cookies
        session = db.get_session(course_id)
        if session and session.get("cookies"):
            browser.add_cookies(session["cookies"])
            
        for node in inspect_nodes:
            url = f"https://www.coursera.org/learn/{course_id}/item/{node['id']}"
            print(f"\n--- INSPECTING {node['name']} ({node['type']}) ---")
            page.goto(url)
            time.sleep(6) # Wait for page load
            
            print(f"URL: {page.url}")
            print(f"Page Title: {page.title()}")
            
            # Scroll down to ensure all elements are rendered and visible
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(2)
            
            # Print all buttons on the page
            buttons = page.evaluate('''() => {
                return Array.from(document.querySelectorAll('button, a, div[role="button"]')).map(el => {
                    return {
                        tag: el.tagName.toLowerCase(),
                        text: el.textContent.trim(),
                        href: el.getAttribute('href') || '',
                        id: el.id,
                        classes: el.className
                    };
                }).filter(b => b.text.length > 0 && b.text.length < 100);
            }''')
            print("Visible elements (buttons/links):")
            for b in buttons:
                print(f"  [{b['tag'].upper()}] id='{b['id']}' class='{b['classes']}': {b['text']}")
                
            screenshot_path = f"inspect_{node['id']}.png"
            page.screenshot(path=screenshot_path)
            print(f"Screenshot saved to: {os.path.abspath(screenshot_path)}")

if __name__ == "__main__":
    main()
