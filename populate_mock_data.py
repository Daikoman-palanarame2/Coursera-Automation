import sqlite3
import json
import time
import os

DB_PATH = "project_accce.db"
LOG_PATH = "project_accce.log"

def populate():
    # 1. Syllabus Nodes definition
    syllabus_nodes = [
        {"id": "introduction-to-react", "type": "reading"},
        {"id": "why-react", "type": "video"},
        {"id": "react-components", "type": "video"},
        {"id": "functional-components", "type": "reading"},
        {"id": "component-props", "type": "video"},
        {"id": "props-quiz", "type": "quiz"},
        {"id": "state-in-react", "type": "video"},
        {"id": "working-with-state-lab", "type": "lab"},
        {"id": "state-quiz", "type": "quiz"},
        {"id": "event-handling", "type": "video"},
        {"id": "events-lab", "type": "lab"},
        {"id": "react-forms", "type": "video"},
        {"id": "forms-lab", "type": "lab"},
        {"id": "forms-quiz", "type": "quiz"},
        {"id": "component-lifecycle", "type": "video"},
        {"id": "intro-to-hooks", "type": "video"},
        {"id": "usestate-hook", "type": "video"},
        {"id": "useeffect-hook", "type": "video"},
        {"id": "context-api-reading", "type": "reading"},
        {"id": "context-quiz", "type": "quiz"},
        {"id": "final-project-peer-review", "type": "peer"},
        {"id": "course-summary", "type": "reading"}
    ]

    completed_nodes = [
        "introduction-to-react",
        "why-react",
        "react-components",
        "functional-components",
        "component-props",
        "props-quiz",
        "state-in-react",
        "working-with-state-lab",
        "state-quiz",
        "event-handling"
    ]

    current_node = "events-lab"

    # 2. Update database
    conn = sqlite3.connect(DB_PATH)
    try:
        with conn:
            conn.execute("DROP TABLE IF EXISTS course_state")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS course_state (
                    course_id TEXT PRIMARY KEY,
                    current_node_id TEXT,
                    completed_nodes_json TEXT NOT NULL,
                    syllabus_nodes_json TEXT,
                    updated_at REAL NOT NULL
                )
            """)
            conn.execute("""
                INSERT OR REPLACE INTO course_state (course_id, current_node_id, completed_nodes_json, syllabus_nodes_json, updated_at)
                VALUES (?, ?, ?, ?, ?)
            """, (
                "react-basics",
                current_node,
                json.dumps(completed_nodes),
                json.dumps(syllabus_nodes),
                time.time()
            ))
        print("SUCCESS: Database populated with mock state.")
    finally:
        conn.close()

    # 3. Create mock log file
    logs = [
        "[ENGINE] Initializing stealth browser context...",
        "[ENGINE] Restoring existing cookies from storage...",
        "[ENGINE] Navigating to course homepage...",
        "[ENGINE] Session active! Syllabus elements detected.",
        "[ENGINE] Dynamically extracting course syllabus items...",
        "[ENGINE] Successfully extracted 22 syllabus node(s) dynamically!",
        "[ENGINE] Processing node: introduction-to-react (Type: reading)",
        "[ENGINE] Reading module detected. Beginning natural human scroll...",
        "[SUCCESS] Mark as Completed clicked.",
        "[ENGINE] Node complete. Entering Poisson sleep interval...",
        "[ENGINE] Processing node: why-react (Type: video)",
        "[ENGINE] Video lecture detected. Emulating telemetry heartbeats...",
        "[ENGINE] Node complete. Entering Poisson sleep interval...",
        "[ENGINE] Processing node: react-components (Type: video)",
        "[ENGINE] Video lecture detected. Emulating telemetry heartbeats...",
        "[ENGINE] Node complete. Entering Poisson sleep interval...",
        "[ENGINE] Processing node: functional-components (Type: reading)",
        "[ENGINE] Reading module detected. Beginning natural human scroll...",
        "[SUCCESS] Mark as Completed clicked.",
        "[ENGINE] Node complete. Entering Poisson sleep interval...",
        "[ENGINE] Processing node: component-props (Type: video)",
        "[ENGINE] Video lecture detected. Emulating telemetry heartbeats...",
        "[ENGINE] Node complete. Entering Poisson sleep interval...",
        "[ENGINE] Processing node: props-quiz (Type: quiz)",
        "[ENGINE] Quiz assignment detected. Parsing payload...",
        "[ENGINE] Extracted 5 questions. Solving with LLM...",
        "[SUCCESS] Gemini suggested answers successfully submitted. Quiz Passed! Score: 100%",
        "[ENGINE] Node complete. Entering Poisson sleep interval...",
        "[ENGINE] Processing node: state-in-react (Type: video)",
        "[ENGINE] Video lecture detected. Emulating telemetry heartbeats...",
        "[ENGINE] Node complete. Entering Poisson sleep interval...",
        "[ENGINE] Processing node: working-with-state-lab (Type: lab)",
        "[ENGINE] Graded lab workspace detected. Setting up interceptors...",
        "[INFO] Lab container spun up. Connection successful.",
        "[SUCCESS] Closed-loop lab coding agent completed successfully! Tests passed.",
        "[ENGINE] Node complete. Entering Poisson sleep interval...",
        "[ENGINE] Processing node: state-quiz (Type: quiz)",
        "[ENGINE] Quiz assignment detected. Parsing payload...",
        "[ENGINE] Extracted 4 questions. Solving with LLM...",
        "[SUCCESS] Gemini suggested answers successfully submitted. Quiz Passed! Score: 100%",
        "[ENGINE] Node complete. Entering Poisson sleep interval...",
        "[ENGINE] Processing node: event-handling (Type: video)",
        "[ENGINE] Video lecture detected. Emulating telemetry heartbeats...",
        "[ENGINE] Node complete. Entering Poisson sleep interval...",
        "[ENGINE] Processing node: events-lab (Type: lab)",
        "[ENGINE] Graded lab workspace detected. Setting up interceptors..."
    ]

    with open(LOG_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(logs) + "\n")
    print("SUCCESS: Mock log file created.")

if __name__ == "__main__":
    populate()
