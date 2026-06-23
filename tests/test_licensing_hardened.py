import os
import sys
import time
import unittest
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient

# Ensure project root is on PATH
proj_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if proj_path not in sys.path:
    sys.path.insert(0, proj_path)

# Set database URL to a temporary SQLite test database
os.environ["DATABASE_URL"] = "sqlite:///test_server_licensing.db"
# Set master wallet address for tests
os.environ["MASTER_WALLET_ADDRESS"] = "0x9999999999999999999999999999999999999999"

# Clear test database if it already exists
if os.path.exists("test_server_licensing.db"):
    try:
        os.remove("test_server_licensing.db")
    except Exception:
        pass

from server.main import app, get_db, get_cursor, init_db

# Global dict to customize mock behavior per test case
MOCK_CONFIG = {
    "status": "0x1",
    "block_number": "0x54321",
    "current_block": "0x5432a",
    "timestamp": None,  # will default to int(time.time())
    "emitter": "0xc2132d05d31c914a87c6611c10748aeb04b58e8f",
    "recipient_topic": "0x0000000000000000000000009999999999999999999999999999999999999999",
    "value_hex": "0x00000000000000000000000000000000000000000000000000000000002dc6c0",  # 3.0 USDT
    "transfer_topic": "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
}

async def mock_async_post(url, json, **kwargs):
    method = json.get("method")
    
    class MockResponse:
        def __init__(self, data_json):
            self._json = data_json
            self.status_code = 200
        def json(self):
            return self._json
            
    if method == "eth_getTransactionReceipt":
        return MockResponse({
            "result": {
                "status": MOCK_CONFIG["status"],
                "blockNumber": MOCK_CONFIG["block_number"],
                "logs": [
                    {
                        "address": MOCK_CONFIG["emitter"],
                        "topics": [
                            MOCK_CONFIG["transfer_topic"],
                            "0x0000000000000000000000001111111111111111111111111111111111111111",
                            MOCK_CONFIG["recipient_topic"]
                        ],
                        "data": MOCK_CONFIG["value_hex"]
                    }
                ]
            }
        })
    elif method == "eth_blockNumber":
        return MockResponse({
            "result": MOCK_CONFIG["current_block"]
        })
    elif method == "eth_getBlockByNumber":
        ts = MOCK_CONFIG["timestamp"]
        if ts is None:
            ts = int(time.time())
        return MockResponse({
            "result": {
                "timestamp": hex(int(ts))
            }
        })
        
    return MockResponse({"result": None})


class TestHardenedLicensing(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()
        cls.client = TestClient(app)
        
    def setUp(self):
        # Clear tables and start fresh for each test
        conn = get_db()
        cursor = get_cursor(conn)
        cursor.execute("DELETE FROM users")
        cursor.execute("DELETE FROM payments")
        conn.commit()
        conn.close()
        
        # Reset MOCK_CONFIG to defaults
        MOCK_CONFIG.update({
            "status": "0x1",
            "block_number": "0x54321",
            "current_block": "0x5432a",
            "timestamp": None,
            "emitter": "0xc2132d05d31c914a87c6611c10748aeb04b58e8f",
            "recipient_topic": "0x0000000000000000000000009999999999999999999999999999999999999999",
            "value_hex": "0x00000000000000000000000000000000000000000000000000000000002dc6c0",
            "transfer_topic": "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
        })

    def test_trial_key_flow(self):
        # 1. Claim trial key with Device A (Success)
        response = self.client.post(
            "/api/v1/web/trial",
            json={"email": "user-a@example.com"},
            headers={"X-Device-ID": "HWID-DEVICE-A", "X-Forwarded-For": "1.1.1.1"}
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertIn("key", data)
        key_a = data["key"]
        
        # 2. Verify key_a is locked to HWID-DEVICE-A in database
        conn = get_db()
        cursor = get_cursor(conn)
        row = cursor.execute("SELECT device_id, is_trial FROM users WHERE api_key = ?", (key_a,)).fetchone()
        conn.close()
        self.assertIsNotNone(row)
        self.assertEqual(row[0], "hwid-device-a") # Should be saved as lowercase/normalized
        self.assertEqual(row[1], 1)

        # 3. Try to claim another trial with the same Device A (Should fail with 403, using different IP and email)
        response = self.client.post(
            "/api/v1/web/trial",
            json={"email": "user-a2@example.com"},
            headers={"X-Device-ID": "hwid-device-a", "X-Forwarded-For": "2.2.2.2"}
        )
        self.assertEqual(response.status_code, 403)
        self.assertIn("already claimed", response.json()["detail"].lower())

        # 4. Check status of key_a using the matching device ID (Should succeed)
        # Note: Test case-insensitivity by passing uppercase header "HWID-device-A"
        response = self.client.post(
            "/api/v1/web/status",
            json={"key": key_a},
            headers={"X-Device-ID": "HWID-device-A"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "active")

        # 5. Check status of key_a using a different device ID (Should fail with 403)
        response = self.client.post(
            "/api/v1/web/status",
            json={"key": key_a},
            headers={"X-Device-ID": "hwid-device-b"}
        )
        self.assertEqual(response.status_code, 403)
        self.assertIn("locked to alternative hardware", response.json()["detail"].lower())

    def test_full_license_flow(self):
        # 1. Create a full license manually in the database
        conn = get_db()
        cursor = get_cursor(conn)
        cursor.execute(
            "INSERT INTO users (api_key, expires_at, is_trial, device_id) VALUES (?, ?, 0, NULL)",
            ("license-full-key-999", "2026-12-31T12:00:00+00:00")
        )
        conn.commit()
        conn.close()

        # 2. Status check of full key without device ID header (Should succeed since it is not a trial key)
        response = self.client.post(
            "/api/v1/web/status",
            json={"key": "license-full-key-999"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "active")

    @patch("httpx.AsyncClient.post", side_effect=mock_async_post)
    def test_claim_purchase_success(self, mock_post_fn):
        tx_hash = "0x" + "a" * 64
        response = self.client.post(
            "/api/v1/web/claim-purchase",
            json={"email": "buyer@example.com", "tx_hash": tx_hash}
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertIn("key", data)
        self.assertTrue(data["key"].startswith("license-web-"))
        
        # Verify db contains user and payment record
        conn = get_db()
        cursor = get_cursor(conn)
        user_row = cursor.execute("SELECT api_key, is_trial, email FROM users WHERE api_key = ?", (data["key"],)).fetchone()
        payment_row = cursor.execute("SELECT tx_hash, api_key, amount FROM payments WHERE tx_hash = ?", (tx_hash,)).fetchone()
        conn.close()
        
        self.assertIsNotNone(user_row)
        self.assertEqual(user_row[1], 0)  # is_trial should be 0/false
        self.assertEqual(user_row[2], "buyer@example.com")
        self.assertIsNotNone(payment_row)
        self.assertEqual(payment_row[1], data["key"])
        self.assertEqual(payment_row[2], 3.0)

    @patch("httpx.AsyncClient.post", side_effect=mock_async_post)
    def test_claim_purchase_double_spend(self, mock_post_fn):
        tx_hash = "0x" + "b" * 64
        # First claim succeeds
        response1 = self.client.post(
            "/api/v1/web/claim-purchase",
            json={"email": "buyer1@example.com", "tx_hash": tx_hash}
        )
        self.assertEqual(response1.status_code, 200)
        
        # Second claim with same tx_hash fails
        response2 = self.client.post(
            "/api/v1/web/claim-purchase",
            json={"email": "buyer2@example.com", "tx_hash": tx_hash}
        )
        self.assertEqual(response2.status_code, 403)
        self.assertIn("already been claimed", response2.json()["detail"].lower())

    @patch("httpx.AsyncClient.post", side_effect=mock_async_post)
    def test_claim_purchase_reorg_insufficient_depth(self, mock_post_fn):
        # Block number of tx: 0x54321 (344865)
        # Current block number: 0x54324 (344868) -> depth = 3 < 5
        MOCK_CONFIG["current_block"] = "0x54324"
        tx_hash = "0x" + "c" * 64
        response = self.client.post(
            "/api/v1/web/claim-purchase",
            json={"email": "buyer@example.com", "tx_hash": tx_hash}
        )
        self.assertEqual(response.status_code, 422)
        self.assertIn("confirmations. enforcing minimum depth of 5 blocks", response.json()["detail"].lower())

    @patch("httpx.AsyncClient.post", side_effect=mock_async_post)
    def test_claim_purchase_emitter_mismatch(self, mock_post_fn):
        # Spoofed token emitter contract address
        MOCK_CONFIG["emitter"] = "0x000000000000000000000000000000000000dead"
        tx_hash = "0x" + "d" * 64
        response = self.client.post(
            "/api/v1/web/claim-purchase",
            json={"email": "buyer@example.com", "tx_hash": tx_hash}
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("no successful usdt transfer", response.json()["detail"].lower())

    @patch("httpx.AsyncClient.post", side_effect=mock_async_post)
    def test_claim_purchase_timestamp_expired(self, mock_post_fn):
        # Transaction is 25 hours old
        MOCK_CONFIG["timestamp"] = int(time.time()) - 25 * 3600
        tx_hash = "0x" + "e" * 64
        response = self.client.post(
            "/api/v1/web/claim-purchase",
            json={"email": "buyer@example.com", "tx_hash": tx_hash}
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("executed more than 24 hours ago", response.json()["detail"].lower())

    @patch("httpx.AsyncClient.post", side_effect=mock_async_post)
    def test_claim_purchase_insufficient_value(self, mock_post_fn):
        # Send only 2.99 USDT (2990000 micro-units = 0x2d9f40)
        MOCK_CONFIG["value_hex"] = "0x2d9f40"
        tx_hash = "0x" + "f" * 64
        response = self.client.post(
            "/api/v1/web/claim-purchase",
            json={"email": "buyer@example.com", "tx_hash": tx_hash}
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("no successful usdt transfer", response.json()["detail"].lower())

    @patch("httpx.AsyncClient.post", side_effect=mock_async_post)
    def test_claim_purchase_wrong_recipient(self, mock_post_fn):
        # Send to a different wallet address
        MOCK_CONFIG["recipient_topic"] = "0x0000000000000000000000008888888888888888888888888888888888888888"
        tx_hash = "0x" + "0" * 64
        response = self.client.post(
            "/api/v1/web/claim-purchase",
            json={"email": "buyer@example.com", "tx_hash": tx_hash}
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("no successful usdt transfer", response.json()["detail"].lower())

    @classmethod
    def tearDownClass(cls):
        # Remove test database
        if os.path.exists("test_server_licensing.db"):
            try:
                os.remove("test_server_licensing.db")
            except Exception:
                pass

if __name__ == "__main__":
    unittest.main()
