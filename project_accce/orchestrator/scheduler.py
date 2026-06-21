import time
import urllib.request
import json
from typing import Dict, Any, List
from project_accce.orchestrator.db import ACCCEStorage
from project_accce.orchestrator.notifier import send_discord_notification

def check_coursera_grade(course_id: str, cookies: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Queries Coursera's grades API for the given course to check if all assignments are passed.
    """
    # Convert cookie list to a Cookie header string
    cookie_header = "; ".join([f"{c['name']}={c['value']}" for c in cookies])
    
    # Standard Coursera grades API endpoint
    url = f"https://www.coursera.org/api/courseGrades.v1/?q=course&courseId={course_id}&fields=passingState,gradebook"
    
    req = urllib.request.Request(
        url,
        headers={
            "Cookie": cookie_header,
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/115.0",
            "Accept": "application/json"
        }
    )
    
    try:
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode("utf-8"))
            # Process response to check passing state
            # Typical Coursera schema returns a list of grade records under "elements"
            elements = data.get("elements", [])
            if elements:
                record = elements[0]
                passing_state = record.get("passingState", "NotPassed") # e.g. "Passed" or "NotPassed"
                return {"success": True, "passed": passing_state == "Passed", "details": record}
            return {"success": True, "passed": False, "details": {}}
    except Exception as e:
        # Fallback or error reporting
        return {"success": False, "passed": False, "error": str(e)}

def run_gradebook_polling_cycle(db_path: str, webhook_url: str):
    """
    Runs a single query cycle over all pending peer reviews in the database.
    """
    db = ACCCEStorage(db_path)
    pending = db.get_all_pending_peer_reviews()
    
    if not pending:
        print("[SCHEDULER] No pending peer reviews in queue.")
        return

    print(f"[SCHEDULER] Polling gradebook for {len(pending)} pending courses...")
    for item in pending:
        course_id = item["course_id"]
        submission_id = item["submission_id"]
        node_id = item["node_id"]
        
        session = db.get_session(course_id)
        if not session or not session.get("cookies"):
            print(f"[SCHEDULER] No active session cookies found for course {course_id}. Skipped.")
            continue
            
        res = check_coursera_grade(course_id, session["cookies"])
        
        if res["success"]:
            if res["passed"]:
                print(f"[SCHEDULER] Course {course_id} has PASSED!")
                db.save_peer_review(course_id, node_id, submission_id, 3, 3, "passed")
                
                # Send Discord Notification
                send_discord_notification(
                    webhook_url,
                    content=f"🎉 **Assignment Passed!** Course `{course_id}` peer grading has settled. Core task node `{node_id}` marked as PASSED."
                )
            else:
                # Still in review pool. Update checks count or status.
                print(f"[SCHEDULER] Course {course_id} is still pending peer evaluations.")
                db.save_peer_review(course_id, node_id, submission_id, item["reviews_completed"], item["reviews_received"], "reviewing")
        else:
            print(f"[SCHEDULER] Gradebook poll failed for {course_id}: {res.get('error')}")
