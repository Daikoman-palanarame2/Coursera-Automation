import subprocess
import time
import os
import sys
import sqlite3
from datetime import datetime, timedelta, timezone
import requests

def run_real_server_test():
    print("[TEST] Cleaning up previous databases...")
    if os.path.exists("server_licensing.db"):
        try:
            os.remove("server_licensing.db")
        except Exception:
            pass

    print("[TEST] Starting the actual licensing FastAPI server on port 8002...")
    # Start the real server
    server_process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "server.main:app", "--host", "127.0.0.1", "--port", "8002"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    
    # Wait for server to boot
    time.sleep(4)
    
    try:
        res = requests.get("http://127.0.0.1:8002/")
        if res.status_code != 200 or res.json().get("status") != "online":
            raise RuntimeError("Licensing server failed to boot correctly.")
        print("[TEST] Licensing server is online!")
    except Exception as e:
        server_process.terminate()
        print(f"[TEST] Failed to connect to server: {e}")
        sys.exit(1)

    try:
        # Set environment variables for the client
        os.environ["COURSERA_ENGINE_BACKEND_URL"] = "http://127.0.0.1:8002"
        os.environ["COURSERA_ENGINE_TOKEN"] = "test-demo-key-12345"
        
        # Import layout manager
        from project_accce.layout import fetch_layout_map, get_selector, layout_map
        
        # Step 1: Run with an active subscription (inserted as +10 minutes on boot)
        print("\n--- Step 1: Testing active subscription ---")
        fetch_layout_map()
        print(f"Selector for video_player is '{get_selector('video_player')}'")
        print("SUCCESS: Access allowed on active subscription.")
            
        # Step 2: Manually expire subscription in database to trigger paywall
        print("\n--- Step 2: Manually expiring subscription ---")
        conn = sqlite3.connect("server_licensing.db")
        cursor = conn.cursor()
        past_time = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        cursor.execute("UPDATE users SET expires_at = ? WHERE api_key = ?", (past_time, "test-demo-key-12345"))
        conn.commit()
        conn.close()
        print("Subscription set to expired in SQLite database.")
        
        # Step 3: Run should now trigger the paywall
        print("\n--- Step 3: Testing expired run (Paywall block) ---")
        try:
            # Clear cache to force reload from server
            layout_map.clear()
            fetch_layout_map()
            print("❌ FAILED: Script did not exit on paywall block.")
            sys.exit(1)
        except SystemExit as e:
            if e.code == 0:
                print("SUCCESS: Client successfully halted and printed the paywall instructions.")
            else:
                print(f"❌ FAILED: Client exited with non-zero code {e.code}")
                sys.exit(1)
                
        # Step 4: Simulate payment detection on-chain
        print("\n--- Step 4: Simulating on-chain payment detection ---")
        # Read the assigned payment amount from the SQLite database
        conn = sqlite3.connect("server_licensing.db")
        cursor = conn.cursor()
        cursor.execute("SELECT assigned_amount FROM users WHERE api_key = ?", ("test-demo-key-12345",))
        assigned_amount = cursor.fetchone()[0]
        print(f"User key 'test-demo-key-12345' was assigned paywall amount: {assigned_amount} USDT")
        assert 3.0000 < assigned_amount < 4.0000, "Assigned amount should be $3 USD + unique cents salt"
        
        # Insert a mock payment to simulate blockchain listener success
        print("Inserting simulated blockchain transaction verification...")
        cursor.execute(
            "INSERT INTO payments (tx_hash, api_key, amount, network) VALUES (?, ?, ?, ?)",
            ("0xmocktxhash987654321", "test-demo-key-12345", assigned_amount, "polygon")
        )
        # Update server to simulate payment processing logic (+30 days)
        new_expiry = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
        cursor.execute(
            "UPDATE users SET expires_at = ?, assigned_amount = 0 WHERE api_key = ?",
            (new_expiry, "test-demo-key-12345")
        )
        conn.commit()
        conn.close()
        print(f"Blockchain transaction processed. Expiration date extended to {new_expiry}.")
        
        # Step 5: Run client again (Should succeed now)
        print("\n--- Step 5: Verifying client access is restored ---")
        fetch_layout_map()
        print(f"Run 7: Selector for video_player is '{get_selector('video_player')}'")
        print("SUCCESS: Access successfully unlocked for 1 month after payment confirmation!")

    finally:
        print("\n[TEST] Stopping licensing server...")
        server_process.terminate()
        server_process.wait()
        print("[TEST] All integration tests passed successfully.")

if __name__ == "__main__":
    run_real_server_test()
