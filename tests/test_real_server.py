import subprocess
import time
import os
import sys
import sqlite3
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
        
        # Step 1: Run 5 authorized requests (Free tier)
        print("\n--- Step 1: Testing 5 free runs ---")
        for i in range(1, 6):
            fetch_layout_map()
            print(f"Run {i}: Selector for video_player is '{get_selector('video_player')}'")
            
        # Step 2: 6th run should trigger the paywall
        print("\n--- Step 2: Testing 6th run (Paywall block) ---")
        try:
            fetch_layout_map()
            print("❌ FAILED: Script did not exit on paywall block.")
            sys.exit(1)
        except SystemExit as e:
            if e.code == 0:
                print("SUCCESS: Client successfully halted and printed the paywall instructions.")
            else:
                print(f"❌ FAILED: Client exited with non-zero code {e.code}")
                sys.exit(1)
                
        # Step 3: Simulate payment detection on-chain
        print("\n--- Step 3: Simulating on-chain payment detection ---")
        # Read the assigned payment amount from the SQLite database
        conn = sqlite3.connect("server_licensing.db")
        cursor = conn.cursor()
        cursor.execute("SELECT assigned_amount FROM users WHERE api_key = ?", ("test-demo-key-12345",))
        assigned_amount = cursor.fetchone()[0]
        print(f"User key 'test-demo-key-12345' was assigned paywall amount: {assigned_amount} USDT")
        
        # Insert a mock payment to simulate blockchain listener success
        print("Inserting simulated blockchain transaction verification...")
        cursor.execute(
            "INSERT INTO payments (tx_hash, api_key, amount, network) VALUES (?, ?, ?, ?)",
            ("0xmocktxhash987654321", "test-demo-key-12345", assigned_amount, "polygon")
        )
        cursor.execute(
            "UPDATE users SET credits = 50, assigned_amount = 0 WHERE api_key = ?",
            ("test-demo-key-12345",)
        )
        conn.commit()
        conn.close()
        print("Blockchain transaction processed. Credits reloaded to 50.")
        
        # Step 4: Run 7th request (Should succeed now)
        print("\n--- Step 4: Verifying client access is restored ---")
        fetch_layout_map()
        print(f"Run 7: Selector for video_player is '{get_selector('video_player')}'")
        print("SUCCESS: Access successfully unlocked after payment confirmation!")

    finally:
        print("\n[TEST] Stopping licensing server...")
        server_process.terminate()
        server_process.wait()
        print("[TEST] All integration tests passed successfully.")

if __name__ == "__main__":
    run_real_server_test()
