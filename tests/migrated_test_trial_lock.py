import os
import sqlite3
import sys
import unittest
from fastapi.testclient import TestClient

# Ensure project root is on PATH
base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if base_dir not in sys.path:
    sys.path.insert(0, base_dir)

os.environ["DATABASE_URL"] = "sqlite:///test_server_licensing.db"

# Clear test database if exists
if os.path.exists("test_server_licensing.db"):
    try:
        os.remove("test_server_licensing.db")
    except Exception:
        pass

from server.main import app, get_db, get_cursor, init_db

class TestTrialLock(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Initialize db schema
        init_db()
        cls.client = TestClient(app)
        
    def setUp(self):
        # Create a fresh database connection to insert test users
        conn = get_db()
        cursor = get_cursor(conn)
        
        # Clean users
        cursor.execute("DELETE FROM users")
        
        # Insert a trial key
        if hasattr(cursor, 'execute'):
            # Works for both sqlite and postgres wrappers
            cursor.execute(
                "INSERT INTO users (api_key, expires_at, is_trial) VALUES (?, ?, 1)",
                ("trial-test-key-123", "2026-07-23T12:00:00")
            )
            
            # Insert a full key
            cursor.execute(
                "INSERT INTO users (api_key, expires_at, is_trial) VALUES (?, ?, 0)",
                ("license-test-key-123", "2026-07-23T12:00:00")
            )
        conn.commit()
        conn.close()

    def test_full_license_key_does_not_lock(self):
        # Try locking full key
        response = self.client.post("/api/v1/web/trial/lock", json={
            "key": "license-test-key-123",
            "course_id": "intro-cybersecurity",
            "module_index": 1
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["message"], "Full license key. No lock required.")
        
        # Lock full key to another module
        response = self.client.post("/api/v1/web/trial/lock", json={
            "key": "license-test-key-123",
            "course_id": "intro-cybersecurity",
            "module_index": 2
        })
        self.assertEqual(response.status_code, 200)
        
    def test_trial_key_locks_successfully(self):
        # 1. Lock trial key to module 1
        response = self.client.post("/api/v1/web/trial/lock", json={
            "key": "trial-test-key-123",
            "course_id": "intro-cybersecurity",
            "module_index": 1
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["message"], "Trial key successfully locked to this module.")
        
        # Verify in DB
        conn = get_db()
        cursor = get_cursor(conn)
        
        # Fetch row
        cursor.execute("SELECT trial_locked_course_id, trial_locked_module_index FROM users WHERE api_key = ?", ("trial-test-key-123",))
        row = cursor.fetchone()
        conn.close()
        self.assertEqual(row[0] or row['trial_locked_course_id'], "intro-cybersecurity")
        self.assertEqual(int(row[1] or row['trial_locked_module_index']), 1)
        
        # 2. Try locking to same course and module (should succeed)
        response = self.client.post("/api/v1/web/trial/lock", json={
            "key": "trial-test-key-123",
            "course_id": "intro-cybersecurity",
            "module_index": 1
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["message"], "Valid matching trial allocation.")
        
        # 3. Try locking to a different module in the same course (should fail)
        response = self.client.post("/api/v1/web/trial/lock", json={
            "key": "trial-test-key-123",
            "course_id": "intro-cybersecurity",
            "module_index": 2
        })
        self.assertEqual(response.status_code, 403)
        self.assertIn("already locked", response.json()["detail"])
        
        # 4. Try locking to a different course (should fail)
        response = self.client.post("/api/v1/web/trial/lock", json={
            "key": "trial-test-key-123",
            "course_id": "other-course",
            "module_index": 1
        })
        self.assertEqual(response.status_code, 403)

    def test_trial_key_not_found(self):
        response = self.client.post("/api/v1/web/trial/lock", json={
            "key": "nonexistent-key",
            "course_id": "intro-cybersecurity",
            "module_index": 1
        })
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "Trial key not found.")

if __name__ == "__main__":
    unittest.main()
