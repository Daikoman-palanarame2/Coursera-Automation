import time
import requests
import sys

def run_tests():
    base_url = "http://127.0.0.1:8000"
    
    # Wait for server
    time.sleep(3)
    
    print("=== STARTING WEB PORTAL API TESTS ===")
    
    # 1. Test GET / to see if index.html is served
    try:
        r = requests.get(f"{base_url}/")
        assert r.status_code == 200
        assert "<title>ACCCE Self-Service Portal</title>" in r.text
        print("[OK] Task 1: GET / (Web Landing Page) successfully serving HTML")
    except Exception as e:
        print(f"[FAIL] Task 1 Failed: {e}")
        sys.exit(1)
        
    # 2. Test POST /api/v1/web/trial (First time - Success)
    trial_key = None
    try:
        r = requests.post(f"{base_url}/api/v1/web/trial", json={"email": "test-trial@example.com"})
        assert r.status_code == 200
        data = r.json()
        assert data["success"] is True
        assert "trial-web-" in data["key"]
        trial_key = data["key"]
        print(f"[OK] Task 2: Trial generation success (Key: {trial_key})")
    except Exception as e:
        print(f"[FAIL] Task 2 Failed: {e}")
        sys.exit(1)

    # 3. Test POST /api/v1/web/trial (Duplicate Email check)
    try:
        r = requests.post(f"{base_url}/api/v1/web/trial", json={"email": "test-trial@example.com"})
        assert r.status_code == 403
        data = r.json()
        assert "email" in data["detail"].lower() or "ip" in data["detail"].lower()
        print("[OK] Task 3: Email uniqueness validation succeeded (Blocked duplicate)")
    except Exception as e:
        print(f"[FAIL] Task 3 Failed: {e}")
        sys.exit(1)

    # 4. Test POST /api/v1/web/trial (Duplicate IP check)
    try:
        r = requests.post(f"{base_url}/api/v1/web/trial", json={"email": "different-trial@example.com"})
        assert r.status_code == 403
        data = r.json()
        assert "ip address" in data["detail"].lower()
        print("[OK] Task 4: IP rate-limiting validation succeeded (Blocked 24h duplicate)")
    except Exception as e:
        print(f"[FAIL] Task 4 Failed: {e}")
        sys.exit(1)

    # 5. Test POST /api/v1/web/purchase (First key - Success)
    key1 = None
    amt1 = None
    try:
        r = requests.post(f"{base_url}/api/v1/web/purchase", json={"email": "test-buyer1@example.com"})
        assert r.status_code == 200
        data = r.json()
        assert data["success"] is True
        assert "license-web-" in data["key"]
        key1 = data["key"]
        amt1 = data["amount"]
        print(f"[OK] Task 5: Purchase generation success (Key: {key1}, Salt Amount: {amt1})")
    except Exception as e:
        print(f"[FAIL] Task 5 Failed: {e}")
        sys.exit(1)

    # 6. Test POST /api/v1/web/purchase (Second key - Unique Salt validation)
    key2 = None
    amt2 = None
    try:
        r = requests.post(f"{base_url}/api/v1/web/purchase", json={"email": "test-buyer2@example.com"})
        assert r.status_code == 200
        data = r.json()
        key2 = data["key"]
        amt2 = data["amount"]
        assert amt1 != amt2  # Verify salt is unique
        print(f"[OK] Task 6: Unique salt allocation succeeded (Salt 1: {amt1} vs Salt 2: {amt2})")
    except Exception as e:
        print(f"[FAIL] Task 6 Failed: {e}")
        sys.exit(1)

    # 7. Test POST /api/v1/web/status (Idempotent check - Expired/Pending key)
    try:
        # Check first status
        r1 = requests.post(f"{base_url}/api/v1/web/status", json={"key": key1})
        assert r1.status_code == 200
        d1 = r1.json()
        assert d1["status"] == "payment_required"
        assert d1["amount"] == amt1
        
        # Check second status (should be identical, idempotent, no new salt)
        r2 = requests.post(f"{base_url}/api/v1/web/status", json={"key": key1})
        assert r2.status_code == 200
        d2 = r2.json()
        assert d2["status"] == "payment_required"
        assert d2["amount"] == amt1
        print("[OK] Task 7: Status check is fully idempotent (Does not mutate database salt)")
    except Exception as e:
        print(f"[FAIL] Task 7 Failed: {e}")
        sys.exit(1)

    # 8. Verify layout-map integration for the generated trial key
    try:
        headers = {
            "X-API-Key": trial_key,
            "X-Device-ID": "test-device-uuid-1234"
        }
        r = requests.get(f"{base_url}/api/v1/layout-map", headers=headers)
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "authorized"
        assert "layout_map" in data
        print("[OK] Task 8: Bot layout-map client authentication integration verified successfully")
    except Exception as e:
        print(f"[FAIL] Task 8 Failed: {e}")
        sys.exit(1)
        
    print("\n=== ALL TESTS PASSED SUCCESSFULLY! ===")

if __name__ == "__main__":
    run_tests()
