import subprocess
import time
import os
import sys
import requests

def run_test():
    print("[TEST] Starting local mock licensing server...")
    # Start the mock server on port 8001
    server_process = subprocess.Popen(
        [sys.executable, "tests/mock_licensing_server.py"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    
    # Wait for server to boot
    time.sleep(3)
    
    # Ensure server is running
    try:
        res = requests.get("http://127.0.0.1:8001/")
        if res.status_code != 200 or res.json().get("status") != "mock_online":
            raise RuntimeError("Mock server failed to respond correctly.")
        print("[TEST] Mock server is online!")
    except Exception as e:
        server_process.terminate()
        print(f"[TEST] Failed to connect to mock server: {e}")
        sys.exit(1)

    try:
        # Set environment variables for the test
        os.environ["COURSERA_ENGINE_BACKEND_URL"] = "http://127.0.0.1:8001"
        
        # Test Case 1: Valid credentials (credits available)
        print("\n[TEST CASE 1] Verifying layout fetch with valid key...")
        os.environ["COURSERA_ENGINE_TOKEN"] = "test-success-key"
        
        # Import layout module dynamically to apply env variables
        from project_accce.layout import fetch_layout_map, get_selector, layout_map
        fetch_layout_map()
        
        # Assert selectors are loaded
        assert len(layout_map) > 0, "Layout map should not be empty on successful fetch."
        assert get_selector("video_player") == "video", "Should retrieve 'video' for video_player selector."
        print("SUCCESS: Test Case 1 - Dynamic selectors loaded successfully from mock server.")
        
        # Test Case 2: Exhausted credits (paywall trigger)
        print("\n[TEST CASE 2] Verifying paywall triggers with exhausted key...")
        os.environ["COURSERA_ENGINE_TOKEN"] = "test-paywall-key"
        
        # We expect fetch_layout_map to call sys.exit(0) when 402 is intercepted
        try:
            fetch_layout_map()
            print("FAILED: Test Case 2 - Script did not exit on 402 paywall status.")
            sys.exit(1)
        except SystemExit as e:
            if e.code == 0:
                print("SUCCESS: Test Case 2 - Client successfully intercepted the 402 paywall and exited with code 0.")
            else:
                print(f"FAILED: Test Case 2 - Client exited with non-zero code {e.code}")
                sys.exit(1)
                
    finally:
        # Tear down mock server
        print("\n[TEST] Stopping mock licensing server...")
        server_process.terminate()
        server_process.wait()
        print("[TEST] Integration test complete.")

if __name__ == "__main__":
    run_test()
