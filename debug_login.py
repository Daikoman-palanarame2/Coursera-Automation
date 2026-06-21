import os
import sys
import time
from project_accce.stealth.browser import launch_stealth_browser
from project_accce.orchestrator.db import ACCCEStorage

def main():
    db = ACCCEStorage("project_accce.db")
    course_id = "react-basics"
    user_data_dir = os.path.join(os.getcwd(), "chrome_sessions", course_id)
    
    print(f"Launching stealth browser with profile: {user_data_dir}")
    with launch_stealth_browser(headless=True, user_data_dir=user_data_dir) as browser:
        page = browser.new_page()
        
        # Load cookies if any
        session = db.get_session(course_id)
        if session and session.get("cookies"):
            print("Loading cookies from database...")
            browser.add_cookies(session["cookies"])
            
        print("Navigating to reading item PMigT...")
        page.goto(f"https://www.coursera.org/learn/{course_id}/item/PMigT")
        
        print("Waiting 10 seconds for rendering...")
        time.sleep(10)
        
        title = page.title()
        url = page.url
        print(f"Page Title: {title}")
        print(f"Current URL: {url}")
        
        # Extract user profile name/email/ID from DOM
        user_info = page.evaluate('''() => {
            const btn = document.querySelector('button[aria-label^="User Menu"]');
            if (btn) return btn.getAttribute("aria-label");
            const dropdown = document.querySelector('.rc-UserDropdownMenu, .profile-name');
            if (dropdown) return dropdown.textContent.trim();
            return "User Profile element not found";
        }''')
        print(f"Logged-in user menu label: {user_info}")
        
        # Extract button text from DOM
        btns = page.evaluate('''() => {
            return Array.from(document.querySelectorAll('button')).map(b => b.textContent.trim());
        }''')
        print(f"Buttons on page: {btns}")
        
        screenshot_path = "debug_login.png"
        page.screenshot(path=screenshot_path)
        print(f"Screenshot saved to: {os.path.abspath(screenshot_path)}")
        
        # Check if page has syllabus links or is logged in
        has_syllabus = page.evaluate('''(courseId) => {
            const pattern = new RegExp(`\\/learn\\/${courseId}\\/(lecture|supplement|exam|peer|item|lti|ungradedLtiHistory)\\/`);
            return Array.from(document.querySelectorAll('a')).some(a => pattern.test(a.href));
        }''', course_id)
        print(f"Syllabus links detected: {has_syllabus}")
        
        # Check if login button is visible
        login_visible = page.locator("a:has-text('Log In'), button:has-text('Log in')").count() > 0
        print(f"Login button visible: {login_visible}")

if __name__ == "__main__":
    main()
