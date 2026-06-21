import os
import sys
import time
import json
from project_accce.stealth.browser import launch_stealth_browser
from project_accce.orchestrator.db import ACCCEStorage

def main():
    db = ACCCEStorage("project_accce.db")
    course_id = "react-basics"
    user_data_dir = os.path.join(os.getcwd(), "chrome_sessions", course_id)
    
    print("Launching stealth browser...")
    with launch_stealth_browser(headless=True, user_data_dir=user_data_dir) as browser:
        page = browser.new_page()
        
        # Load cookies
        session = db.get_session(course_id)
        if session and session.get("cookies"):
            browser.add_cookies(session["cookies"])
            
        url = f"https://www.coursera.org/learn/{course_id}/item/MsMOF"
        print(f"Navigating to {url}...")
        page.goto(url)
        time.sleep(8)
        
        page.evaluate('''() => {
            window.scrollTo(0, document.body.scrollHeight);
            const mainContent = document.querySelector('.rc-MainContent, main, #main');
            if (mainContent) {
                mainContent.scrollTo(0, mainContent.scrollHeight);
            }
        }''')
        time.sleep(2)
        
        # Find Resume/Start button
        start_selector = "button:has-text('Resume'), button:has-text('Start'), button:has-text('Start attempt'), button:has-text('Resume Quiz')"
        if page.locator(start_selector).count() > 0:
            btn = page.locator(start_selector).first
            print(f"Found button: '{btn.inner_text().strip()}'. Clicking...")
            btn.click()
            time.sleep(4)
            
            # Print visible elements
            elements = page.evaluate('''() => {
                return Array.from(document.querySelectorAll('button, a, input[type="checkbox"], [role="button"]')).map(el => {
                    return {
                        tag: el.tagName,
                        type: el.getAttribute('type') || '',
                        text: el.textContent.trim(),
                        id: el.id,
                        visible: el.offsetWidth > 0 && el.offsetHeight > 0
                    };
                }).filter(el => el.visible || el.type === 'checkbox');
            }''')
            print("\nElements post-click:")
            for el in elements:
                print(f"  [{el['tag']}] type='{el['type']}' id='{el['id']}': '{el['text']}'")
                
            page.screenshot(path="msmof_test.png")
            print("Screenshot saved to msmof_test.png")
        else:
            print("No button found!")

if __name__ == "__main__":
    main()
