import subprocess
import time
import os
import sys
import sqlite3
from datetime import datetime, timedelta, timezone
import requests

def run_device_gating_test():
    print("[TEST] Cleaning up previous databases...")
    if os.path.exists("server_licensing.db"):
        try:
            os.remove("server_licensing.db")
        except Exception:
            pass

    print("[TEST] Starting the licensing FastAPI server on port 8003...")
    server_process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "server.main:app", "--host", "127.0.0.1", "--port", "8003"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    
    # Wait for server to boot
    time.sleep(4)
    
    try:
        # Check server online
        res = requests.get("http://127.0.0.1:8003/")
        if res.status_code != 200 or res.json().get("status") != "online":
            raise RuntimeError("Licensing server failed to boot correctly.")
        print("[TEST] Server online!")
        
        # Setup tokens in sqlite database
        conn = sqlite3.connect("server_licensing.db")
        cursor = conn.cursor()
        
        expiry_active = (datetime.now(timezone.utc) + timedelta(hours=3)).isoformat()
        
        # Insert Trial Token 1
        cursor.execute(
            "INSERT INTO users (api_key, expires_at, is_trial, device_id) VALUES (?, ?, 1, NULL)",
            ("trial-token-1", expiry_active)
        )
        # Insert Trial Token 2
        cursor.execute(
            "INSERT INTO users (api_key, expires_at, is_trial, device_id) VALUES (?, ?, 1, NULL)",
            ("trial-token-2", expiry_active)
        )
        # Insert Paid Token
        cursor.execute(
            "INSERT INTO users (api_key, expires_at, is_trial, device_id) VALUES (?, ?, 0, NULL)",
            ("paid-token-1", expiry_active)
        )
        conn.commit()
        conn.close()
        
        # Test Case 1: First request with Trial Token 1 on Device A (Should lock and succeed)
        print("\n--- Test Case 1: Initial run with Trial Token 1 on Device A ---")
        headers = {"X-API-Key": "trial-token-1", "X-Device-ID": "device-A"}
        r = requests.get("http://127.0.0.1:8003/api/v1/layout-map", headers=headers)
        assert r.status_code == 200, f"Expected 200, got {r.status_code}"
        print("SUCCESS: Trial key authorized on first device.")
        
        # Verify in DB that token 1 is locked to Device A
        conn = sqlite3.connect("server_licensing.db")
        cursor = conn.cursor()
        cursor.execute("SELECT device_id FROM users WHERE api_key = ?", ("trial-token-1",))
        locked_device = cursor.fetchone()[0]
        conn.close()
        assert locked_device == "device-A", f"Expected device-A, got {locked_device}"
        print("SUCCESS: Trial key is correctly locked to device-A in database.")
        
        # Test Case 2: Run with Trial Token 1 on Device B (Should reject - locked to Device A)
        print("\n--- Test Case 2: Running Trial Token 1 on Device B ---")
        headers = {"X-API-Key": "trial-token-1", "X-Device-ID": "device-B"}
        r = requests.get("http://127.0.0.1:8003/api/v1/layout-map", headers=headers)
        assert r.status_code == 403, f"Expected 403, got {r.status_code}"
        assert "locked to another device" in r.json()["detail"]
        print("SUCCESS: Trial key access blocked on unauthorized device B.")
        
        # Test Case 3: Try to claim Trial Token 2 on Device A (Should reject - Device A already used a trial)
        print("\n--- Test Case 3: Claiming Trial Token 2 on Device A ---")
        headers = {"X-API-Key": "trial-token-2", "X-Device-ID": "device-A"}
        r = requests.get("http://127.0.0.1:8003/api/v1/layout-map", headers=headers)
        assert r.status_code == 403, f"Expected 403, got {r.status_code}"
        assert "already used a free trial" in r.json()["detail"]
        print("SUCCESS: Duplicate trial blocked on device-A.")
        
        # Test Case 4: Paid token running on Device A (Should bypass device check and succeed)
        print("\n--- Test Case 4: Running Paid Token on Device A ---")
        headers = {"X-API-Key": "paid-token-1", "X-Device-ID": "device-A"}
        r = requests.get("http://127.0.0.1:8003/api/v1/layout-map", headers=headers)
        assert r.status_code == 200, f"Expected 200, got {r.status_code}"
        print("SUCCESS: Paid token successfully bypassed trial device lock.")
        
    finally:
        print("\n[TEST] Stopping server...")
        server_process.terminate()
        server_process.wait()
        print("[TEST] Device gating tests finished successfully.")

if __name__ == "__main__":
    run_device_gating_test()
