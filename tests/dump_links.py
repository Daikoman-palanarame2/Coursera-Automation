import os
import time
from project_accce.stealth.browser import launch_stealth_browser

def main():
    course_id = "react-basics"
    user_data_dir = os.path.join(os.getcwd(), "chrome_sessions", course_id)
    
    print("Launching stealth browser...")
    with launch_stealth_browser(headless=True, user_data_dir=user_data_dir) as browser:
        page = browser.new_page()
        
        print("Navigating to course home page...")
        page.goto(f"https://www.coursera.org/learn/{course_id}/home/welcome")
        time.sleep(8)
        
        # Take screenshot for visual validation
        screenshot_path = "home_page_check.png"
        page.screenshot(path=screenshot_path)
        print(f"Screenshot saved to {screenshot_path}")
        
        print("Extracting all hrefs on the page:")
        hrefs = page.evaluate('''() => {
            return Array.from(document.querySelectorAll('a')).map(a => a.href);
        }''')
        
        print(f"Total links found: {len(hrefs)}")
        coursera_links = [h for h in hrefs if "coursera.org/learn/" in h]
        print(f"Coursera learn links found: {len(coursera_links)}")
        for link in sorted(list(set(coursera_links)))[:50]:
            print("  -", link)

if __name__ == "__main__":
    main()
