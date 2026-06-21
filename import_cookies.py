from project_accce.orchestrator.db import ACCCEStorage

def main():
    cauth_value = "YOUR_CAUTH_COOKIE_VALUE_HERE"
    
    course_id = "YOUR_COURSE_ID_HERE"
    db_path = "project_accce.db"
    
    cookies = [
        {
            "name": "CAUTH",
            "value": cauth_value,
            "domain": ".coursera.org",
            "path": "/",
            "secure": True,
            "httpOnly": True,
            "sameSite": "Lax"
        }
    ]
    
    print(f"Initializing SQLite database at {db_path}...")
    db = ACCCEStorage(db_path)
    
    print(f"Importing CAUTH cookie for course {course_id}...")
    db.save_session(course_id, cookies, {})
    
    print("SUCCESS: Session cookies imported successfully into database!")

if __name__ == "__main__":
    main()
