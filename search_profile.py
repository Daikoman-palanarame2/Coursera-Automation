import re
import json

def main():
    if not os.path.exists("page_source.html"):
        print("page_source.html not found.")
        return
        
    with open("page_source.html", "r", encoding="utf-8") as f:
        html = f.read()
        
    # Search for email addresses
    emails = re.findall(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', html)
    # Filter out common false positives
    ignored_domains = {"sentry.io", "coursera.org", "googletagmanager.com", "google-analytics.com", "facebook.net"}
    filtered_emails = [e for e in emails if not any(dom in e for dom in ignored_domains)]
    
    print("Found emails:", set(filtered_emails))
    
    # Search for full names and user IDs in common JS states
    full_names = re.findall(r'"fullName"\s*:\s*"([^"]+)"', html)
    print("Found fullNames:", set(full_names))
    
    user_ids = re.findall(r'"userId"\s*:\s*(\d+)', html)
    print("Found userIds:", set(user_ids))
    
    username = re.findall(r'"username"\s*:\s*"([^"]+)"', html)
    print("Found usernames:", set(username))
    
    # Search for active programs or session contexts
    programs = re.findall(r'"programName"\s*:\s*"([^"]+)"', html)
    print("Found programNames:", set(programs))

if __name__ == "__main__":
    import os
    main()
