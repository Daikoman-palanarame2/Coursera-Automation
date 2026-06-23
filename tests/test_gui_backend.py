import os
import sys
import time
import unittest
from unittest.mock import patch, MagicMock

# Add root folder to sys.path if not present
base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if base_dir not in sys.path:
    sys.path.insert(0, base_dir)

from gui_backend import ACCCEBackend

class TestGUIBackendTrialLock(unittest.TestCase):
    def setUp(self):
        self.backend = ACCCEBackend()
        # Clean paths for mock settings
        self.backend._env_path = "test_gui.env"
        if os.path.exists("test_gui.env"):
            os.remove("test_gui.env")
            
    def tearDown(self):
        if os.path.exists("test_gui.env"):
            os.remove("test_gui.env")

    @patch('gui_backend.requests.post')
    @patch('gui_backend.subprocess.Popen')
    def test_full_license_starts_without_module(self, mock_popen, mock_post):
        # Save credentials as a full license
        self.backend.save_credentials(engine_token="license-12345", gemini_key="gemini-key")
        
        # Start bot without module
        result = self.backend.start_bot("https://www.coursera.org/learn/test-course", headless=True, module=None)
        
        # Verify requests.post was not called (full key does not call lock endpoint)
        mock_post.assert_not_called()
        # Verify subprocess.Popen was called (allowed to launch)
        mock_popen.assert_called_once()
        self.assertTrue(result["success"])

    @patch('gui_backend.requests.post')
    @patch('gui_backend.subprocess.Popen')
    def test_trial_license_without_module_is_blocked(self, mock_popen, mock_post):
        # Save credentials as a trial license
        self.backend.save_credentials(engine_token="trial-12345", gemini_key="gemini-key")
        
        # Try launching without a module
        result = self.backend.start_bot("https://www.coursera.org/learn/test-course", headless=True, module=None)
        
        # Verify popen is not called and lock requests.post is not called (blocked earlier)
        mock_post.assert_not_called()
        mock_popen.assert_not_called()
        self.assertFalse(result["success"])
        self.assertIn("must select a specific module", result["error"])

    @patch('gui_backend.requests.post')
    @patch('gui_backend.subprocess.Popen')
    def test_trial_license_with_server_rejection_is_blocked(self, mock_popen, mock_post):
        # Mock server 403 Forbidden rejection
        mock_response = MagicMock()
        mock_response.status_code = 403
        mock_response.json.return_value = {"detail": "This trial key is already locked to Course 'test-course', Module 1."}
        mock_post.return_value = mock_response
        
        # Save credentials as trial
        self.backend.save_credentials(engine_token="trial-12345", gemini_key="gemini-key")
        
        # Try launching module 2
        result = self.backend.start_bot("https://www.coursera.org/learn/test-course", headless=True, module=2)
        
        # Verify lock request was made
        mock_post.assert_called_once()
        # Verify Popen was NOT called (blocked by 403)
        mock_popen.assert_not_called()
        self.assertFalse(result["success"])
        self.assertIn("Trial Lock Denied", result["error"])
        self.assertIn("already locked to Course 'test-course', Module 1", result["error"])

    @patch('gui_backend.requests.post')
    @patch('gui_backend.subprocess.Popen')
    def test_trial_license_with_server_approval_launches(self, mock_popen, mock_post):
        # Mock server 200 OK approval
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_post.return_value = mock_response
        
        # Save credentials
        self.backend.save_credentials(engine_token="trial-12345", gemini_key="gemini-key")
        
        # Try launching module 1
        result = self.backend.start_bot("https://www.coursera.org/learn/test-course", headless=True, module=1)
        
        # Verify lock request was made
        mock_post.assert_called_once()
        # Verify Popen was called (allowed)
        mock_popen.assert_called_once()
        self.assertTrue(result["success"])

    @patch('gui_backend.requests.post')
    def test_claim_trial_invalid_email(self, mock_post):
        result = self.backend.claim_trial("invalid-email")
        self.assertFalse(result["success"])
        self.assertIn("valid email address", result["error"])
        mock_post.assert_not_called()

    @patch('gui_backend.requests.post')
    @patch('gui_backend.get_device_fingerprint')
    def test_claim_trial_success(self, mock_fingerprint, mock_post):
        mock_fingerprint.return_value = "hwid-abc"
        
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"success": True, "key": "trial-web-ok123"}
        mock_post.return_value = mock_response
        
        result = self.backend.claim_trial("test@example.com")
        self.assertTrue(result["success"])
        self.assertEqual(result["key"], "trial-web-ok123")
        
        # Verify credentials were saved locally
        creds = self.backend.has_credentials()
        self.assertEqual(creds["engine_token"], "trial-web-ok123")

    @patch('gui_backend.requests.post')
    @patch('gui_backend.get_device_fingerprint')
    def test_claim_trial_duplicate_device(self, mock_fingerprint, mock_post):
        mock_fingerprint.return_value = "hwid-abc"
        
        mock_response = MagicMock()
        mock_response.status_code = 403
        mock_response.json.return_value = {"detail": "This computer hardware configuration has already claimed an active free trial."}
        mock_post.return_value = mock_response
        
        result = self.backend.claim_trial("test@example.com")
        self.assertFalse(result["success"])
        self.assertIn("already claimed", result["error"])


class TestGUIBackendLicenseCaching(unittest.TestCase):
    def setUp(self):
        self.backend = ACCCEBackend()
        self.backend._env_path = "test_gui.env"
        if os.path.exists("test_gui.env"):
            os.remove("test_gui.env")
        # Save dummy credentials to enable license check
        self.backend.save_credentials(engine_token="license-test-key", gemini_key="gemini-key")
            
    def tearDown(self):
        if os.path.exists("test_gui.env"):
            os.remove("test_gui.env")

    @patch('gui_backend.requests.post')
    @patch('gui_backend.get_device_fingerprint')
    def test_license_status_caching(self, mock_fingerprint, mock_post):
        mock_fingerprint.return_value = "hwid-123"
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "active", "expires_at": "2026-07-23T15:00:00Z"}
        mock_post.return_value = mock_response

        # Call 1: should perform HTTP request
        res1 = self.backend.get_license_status()
        self.assertTrue(res1["success"])
        self.assertEqual(mock_post.call_count, 1)

        # Call 2: should retrieve from memory cache (no HTTP request)
        res2 = self.backend.get_license_status()
        self.assertTrue(res2["success"])
        self.assertEqual(mock_post.call_count, 1)  # Still 1
        self.assertEqual(res1, res2)

    @patch('gui_backend.requests.post')
    @patch('gui_backend.get_device_fingerprint')
    def test_license_status_force_refresh(self, mock_fingerprint, mock_post):
        mock_fingerprint.return_value = "hwid-123"
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "active"}
        mock_post.return_value = mock_response

        # Call 1: check
        self.backend.get_license_status()
        self.assertEqual(mock_post.call_count, 1)

        # Call 2: with force_refresh=True should bypass cache and check server again
        self.backend.get_license_status(force_refresh=True)
        self.assertEqual(mock_post.call_count, 2)

    @patch('gui_backend.requests.post')
    @patch('gui_backend.get_device_fingerprint')
    def test_license_status_ttl_expiration(self, mock_fingerprint, mock_post):
        mock_fingerprint.return_value = "hwid-123"
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "active"}
        mock_post.return_value = mock_response

        # Call 1: cache populated
        self.backend.get_license_status()
        self.assertEqual(mock_post.call_count, 1)

        # Call 2: mock time to shift by 5 hours (exceeding 4-hour TTL)
        future_time = time.time() + 18000
        with patch('time.time', return_value=future_time):
            self.backend.get_license_status()
            # Should have triggered the second network call due to TTL expiration
            self.assertEqual(mock_post.call_count, 2)

    @patch('gui_backend.requests.post')
    @patch('gui_backend.get_device_fingerprint')
    def test_license_status_invalidation_on_save_credentials(self, mock_fingerprint, mock_post):
        mock_fingerprint.return_value = "hwid-123"
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "active"}
        mock_post.return_value = mock_response

        # Call 1: cache populated
        self.backend.get_license_status()
        self.assertEqual(mock_post.call_count, 1)

        # Invalidate cache by saving credentials
        self.backend.save_credentials(engine_token="license-new-key", gemini_key="gemini-key")
        
        # Call 2: should result in cache miss and trigger live request
        self.backend.get_license_status()
        self.assertEqual(mock_post.call_count, 2)

    @patch('gui_backend.requests.post')
    @patch('gui_backend.get_device_fingerprint')
    def test_license_status_network_failure_fallback(self, mock_fingerprint, mock_post):
        mock_fingerprint.return_value = "hwid-123"
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "active", "expires_at": "2026-07-23T15:00:00Z"}
        mock_post.return_value = mock_response

        # Populate cache initially
        res1 = self.backend.get_license_status()
        self.assertTrue(res1["success"])
        self.assertEqual(mock_post.call_count, 1)

        # Configure second request to raise connection error
        mock_post.side_effect = Exception("Connection Refused")
        
        # Force refresh to check live server again
        res2 = self.backend.get_license_status(force_refresh=True)
        # Should gracefully return the cached result instead of failing
        self.assertTrue(res2["success"])
        self.assertEqual(res2["data"]["status"], "active")

if __name__ == '__main__':
    unittest.main()
