import sqlite3
import json
import time
from typing import Dict, Any, List, Optional

class ACCCEStorage:
    def __init__(self, db_path: str = "project_accce.db"):
        self.db_path = db_path
        self._init_db()

    def _get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        """
        Creates storage tables if they do not exist.
        """
        conn = self._get_connection()
        try:
            with conn:
                cursor = conn.cursor()
                
                # Table to store session context tokens and cookies
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS sessions (
                        course_id TEXT PRIMARY KEY,
                        cookies_json TEXT NOT NULL,
                        local_storage_json TEXT,
                        updated_at REAL NOT NULL
                    )
                """)
                
                # Table to store current progress in syllabus traversal
                # Added syllabus_nodes_json to store the full syllabus nodes plan
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS course_state (
                        course_id TEXT PRIMARY KEY,
                        current_node_id TEXT,
                        completed_nodes_json TEXT NOT NULL,
                        syllabus_nodes_json TEXT,
                        updated_at REAL NOT NULL
                    )
                """)
                
                # Table to store peer reviews status (Scenario C asynchronous workflows)
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS peer_reviews (
                        course_id TEXT,
                        node_id TEXT,
                        submission_id TEXT PRIMARY KEY,
                        reviews_completed INTEGER DEFAULT 0,
                        reviews_received INTEGER DEFAULT 0,
                        status TEXT NOT NULL,
                        updated_at REAL NOT NULL
                    )
                """)
        finally:
            conn.close()

    # Sessions operations
    def save_session(self, course_id: str, cookies: List[Dict[str, Any]], local_storage: Dict[str, Any]):
        conn = self._get_connection()
        try:
            with conn:
                conn.execute("""
                    INSERT OR REPLACE INTO sessions (course_id, cookies_json, local_storage_json, updated_at)
                    VALUES (?, ?, ?, ?)
                """, (
                    course_id,
                    json.dumps(cookies),
                    json.dumps(local_storage),
                    time.time()
                ))
        finally:
            conn.close()

    def get_session(self, course_id: str) -> Optional[Dict[str, Any]]:
        conn = self._get_connection()
        try:
            row = conn.execute("SELECT * FROM sessions WHERE course_id = ?", (course_id,)).fetchone()
            if row:
                return {
                    "cookies": json.loads(row["cookies_json"]),
                    "local_storage": json.loads(row["local_storage_json"]) if row["local_storage_json"] else {},
                    "updated_at": row["updated_at"]
                }
            return None
        finally:
            conn.close()

    # Course State operations
    def save_course_state(
        self,
        course_id: str,
        current_node_id: Optional[str],
        completed_nodes: List[str],
        syllabus_nodes: Optional[List[Dict[str, Any]]] = None
    ):
        conn = self._get_connection()
        try:
            with conn:
                conn.execute("""
                    INSERT OR REPLACE INTO course_state (course_id, current_node_id, completed_nodes_json, syllabus_nodes_json, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    course_id,
                    current_node_id,
                    json.dumps(completed_nodes),
                    json.dumps(syllabus_nodes) if syllabus_nodes else None,
                    time.time()
                ))
        finally:
            conn.close()

    def get_course_state(self, course_id: str) -> Optional[Dict[str, Any]]:
        conn = self._get_connection()
        try:
            row = conn.execute("SELECT * FROM course_state WHERE course_id = ?", (course_id,)).fetchone()
            if row:
                return {
                    "current_node_id": row["current_node_id"],
                    "completed_nodes": json.loads(row["completed_nodes_json"]),
                    "syllabus_nodes": json.loads(row["syllabus_nodes_json"]) if row["syllabus_nodes_json"] else None,
                    "updated_at": row["updated_at"]
                }
            return None
        finally:
            conn.close()

    # Peer reviews operations
    def save_peer_review(self, course_id: str, node_id: str, submission_id: str, reviews_completed: int, reviews_received: int, status: str):
        conn = self._get_connection()
        try:
            with conn:
                conn.execute("""
                    INSERT OR REPLACE INTO peer_reviews (course_id, node_id, submission_id, reviews_completed, reviews_received, status, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    course_id,
                    node_id,
                    submission_id,
                    reviews_completed,
                    reviews_received,
                    status,
                    time.time()
                ))
        finally:
            conn.close()

    def get_peer_review(self, submission_id: str) -> Optional[Dict[str, Any]]:
        conn = self._get_connection()
        try:
            row = conn.execute("SELECT * FROM peer_reviews WHERE submission_id = ?", (submission_id,)).fetchone()
            if row:
                return dict(row)
            return None
        finally:
            conn.close()
            
    def get_all_pending_peer_reviews(self) -> List[Dict[str, Any]]:
        conn = self._get_connection()
        try:
            rows = conn.execute("SELECT * FROM peer_reviews WHERE status NOT IN ('passed', 'failed')").fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()
