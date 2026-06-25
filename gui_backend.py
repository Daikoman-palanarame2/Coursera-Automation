import os
import sys

# Force Playwright to use the user's local AppData directory for browsers when compiled.
# This avoids needing to bundle the massive Chromium binaries inside the PyInstaller executable.
if getattr(sys, 'frozen', False):
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = os.path.expandvars(r"%LOCALAPPDATA%\ms-playwright")

import json
import time
import sqlite3
import subprocess
import threading
import webbrowser
import requests
from typing import Optional, Dict, Any, List
from playwright.sync_api import sync_playwright
from project_accce.layout import get_device_fingerprint

class ACCCEBackend:
    """Python-side API bridge exposed to the PyWebView frontend via js_api."""
    
    def __init__(self):
        # Anchor single source of truth in APPDATA for user configuration, data, and log persistence
        self._app_data_dir = os.path.join(
            os.getenv("APPDATA", os.path.dirname(os.path.abspath(__file__))), 
            "ACCCE"
        )
        os.makedirs(self._app_data_dir, exist_ok=True)

        if getattr(sys, 'frozen', False):
            # In PyInstaller, sys._MEIPASS is the temporary directory containing resources
            self._resources_dir = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
            self._app_root = self._resources_dir
        else:
            self._resources_dir = os.path.dirname(os.path.abspath(__file__))
            self._app_root = self._resources_dir
            
        self._base_dir = self._resources_dir
        self._db_path = os.path.join(self._app_data_dir, "project_accce.db")
        self._log_path = os.path.join(self._app_data_dir, "project_accce.log")
        self._env_path = os.path.join(self._app_data_dir, ".env")
        self._config_path = os.path.join(self._app_data_dir, "config.json")

        # Migrate existing configurations from old package/executable directory to APPDATA if present
        old_dir = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))
        if old_dir != self._app_data_dir:
            for filename in ["project_accce.db", "project_accce.log", ".env", "config.json"]:
                old_file = os.path.join(old_dir, filename)
                new_file = os.path.join(self._app_data_dir, filename)
                if os.path.exists(old_file) and not os.path.exists(new_file):
                    import shutil
                    try:
                        shutil.copy2(old_file, new_file)
                    except Exception:
                        pass

        self._bot_process: Optional[subprocess.Popen] = None
        self._bot_thread: Optional[threading.Thread] = None
        self._window = None
        
        # License check caching configuration
        self._cache_lock = threading.Lock()
        self._cached_license_status: Optional[dict] = None
        self._cache_timestamp: float = 0.0
        self._cache_ttl_seconds: int = 14400  # 4-hour TTL for session cache

        # Eagerly initialize SQLite schema to prevent file system races
        from project_accce.orchestrator.db import ACCCEStorage
        self._db = ACCCEStorage(self._db_path)

    def open_browser(self, url: str) -> None:
        """Open the given URL in the user's default system web browser."""
        try:
            webbrowser.open(url)
        except Exception:
            pass
    
    # ── Credential Management ──
    
    def has_credentials(self) -> dict:
        """Check if .env file exists with valid credentials."""
        if not os.path.exists(self._env_path):
            return {
                "has_credentials": False,
                "engine_token": "",
                "gemini_key": "",
                "webhook_url": "",
                "backend_url": "https://coursera-licensing-service.onrender.com",
                "ai_model": "gemini-flash-latest"
            }
        
        env_vars = {}
        with open(self._env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                     key, _, val = line.partition("=")
                     env_vars[key.strip()] = val.strip()
        
        engine_token = env_vars.get("COURSERA_ENGINE_TOKEN", "")
        gemini_key = env_vars.get("GEMINI_API_KEY", "")
        
        # Load from config.json to check for ai_model
        ai_model = "gemini-flash-latest"
        if os.path.exists(self._config_path):
            try:
                with open(self._config_path, "r") as f:
                    cfg = json.load(f)
                    ai_model = cfg.get("ai_model", "gemini-flash-latest")
            except Exception:
                pass
        
        return {
            "has_credentials": bool(engine_token and gemini_key),
            "engine_token": engine_token,
            "gemini_key": gemini_key,
            "webhook_url": "",
            "backend_url": env_vars.get("COURSERA_ENGINE_BACKEND_URL", "https://coursera-licensing-service.onrender.com"),
            "ai_model": ai_model
        }
    
    def save_credentials(self, engine_token: str, gemini_key: str, webhook_url: str = "", ai_model: str = "gemini-flash-latest") -> dict:
        """Write credentials to .env file."""
        # Invalidate license status cache safely under lock boundaries
        with self._cache_lock:
            self._cached_license_status = None
            self._cache_timestamp = 0.0

        try:
            # Preserve the existing backend URL so local-server overrides are not clobbered
            existing_creds = self.has_credentials()
            backend_url = existing_creds.get(
                "backend_url", "https://coursera-licensing-service.onrender.com"
            )
            lines = [
                "# ACCCE Configuration Settings",
                f"COURSERA_ENGINE_TOKEN={engine_token}",
                f"COURSERA_ENGINE_BACKEND_URL={backend_url}",
                f"GEMINI_API_KEY={gemini_key}",
            ]

            with open(self._env_path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
            
            # Also update config.json with the API key and model
            config = {}
            if os.path.exists(self._config_path):
                try:
                    with open(self._config_path, "r") as f:
                        config = json.load(f)
                except Exception:
                    pass
            config["api_key"] = gemini_key
            config["ai_model"] = ai_model
            # Keep api_keys list in sync; preserve any extra keys already listed
            existing_keys = config.get("api_keys", [])
            if isinstance(existing_keys, list):
                # Put the new key first so it is tried first
                if gemini_key not in existing_keys:
                    existing_keys.insert(0, gemini_key)
                else:
                    existing_keys.remove(gemini_key)
                    existing_keys.insert(0, gemini_key)
                config["api_keys"] = existing_keys
            else:
                config["api_keys"] = [gemini_key]
            
            # Ensure config.json doesn't contain any old webhook url references
            if "webhook_url" in config:
                del config["webhook_url"]
                
            with open(self._config_path, "w") as f:
                json.dump(config, f, indent=2)
            
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    # ── Bot Control ──
    
    def start_bot(self, course_url: str, headless: bool = False, module: int = None, force_rescan: bool = False) -> dict:
        """Start the ACCCE bot as a subprocess."""
        if self._bot_process and self._bot_process.poll() is None:
            return {"success": False, "error": "Bot is already running."}
        
        # Clean course URL to extract course ID
        course_id = course_url.strip()
        if "coursera.org/learn/" in course_id:
            course_id = course_id.split("/learn/")[-1].split("/")[0].strip()
        if not course_id:
            return {"success": False, "error": "Course URL or ID cannot be empty."}
        
        # Dynamically duplicate entire token matrix profile over to target course profile tracking identifiers
        discovery_session = self._db.get_session("__discovery_profile__")
        if not (discovery_session and discovery_session.get("cookies")):
            return {"success": False, "error": "No active session tokens found. Please click 'Sync' first."}
        
        try:
            self._db.save_session(course_id, discovery_session["cookies"], {})
        except Exception as e:
            return {"success": False, "error": f"Failed to duplicate session cookies: {str(e)}"}
        
        # Check trial lock status on server
        creds = self.has_credentials()
        engine_token = creds.get("engine_token", "")
        backend_url = creds.get("backend_url", "https://coursera-licensing-service.onrender.com")
        
        if engine_token.lower().startswith("trial"):
            if not module or module == 0:
                return {
                    "success": False,
                    "error": "Trial Limit: You must select a specific module to run. Full course automation is disabled for trial keys."
                }
            
            # Contact the server to validate or register the lock
            try:
                lock_url = f"{backend_url.rstrip('/')}/api/v1/web/trial/lock"
                response = requests.post(
                    lock_url,
                    json={
                        "key": engine_token,
                        "course_id": course_id,
                        "module_index": int(module)
                    },
                    timeout=10
                )
                if response.status_code == 403:
                    try:
                        err_detail = response.json().get("detail", "")
                    except Exception:
                        err_detail = response.text
                    return {
                        "success": False,
                        "error": f"Trial Lock Denied: {err_detail}"
                    }
                elif response.status_code == 404:
                    return {
                        "success": False,
                        "error": "Trial key is invalid or not found on the licensing server."
                    }
                elif response.status_code != 200:
                    return {
                        "success": False,
                        "error": f"Licensing server returned status code {response.status_code} during trial verification."
                    }
            except requests.RequestException as req_err:
                return {
                    "success": False,
                    "error": f"Network error while validating trial lock on the licensing server: {req_err}"
                }
        
        # Build command
        python_exe = os.path.join(self._resources_dir, ".venv", "Scripts", "python.exe")
        if not os.path.exists(python_exe):
            python_exe = sys.executable
        
        main_py_path = os.path.join(self._resources_dir, "main.py")
        cmd = [python_exe, main_py_path, "--course-id", course_id, "--db-path", self._db_path]
        if headless:
            cmd.append("--headless")
        if module:
            cmd.extend(["--module", str(module)])
        if force_rescan:
            cmd.append("--force-rescan")
        cmd.append("--gui")
        
        try:
            # Clear log file for fresh run
            with open(self._log_path, "w", encoding="utf-8") as f:
                f.write("")
            
            # Force environmental streams to operate unbuffered across child threads and pass appdata dir
            child_env = {
                **os.environ, 
                "PYTHONUNBUFFERED": "1",
                "ACCCE_APPDATA_DIR": self._app_data_dir
            }
            
            self._bot_process = subprocess.Popen(
                cmd,
                cwd=self._app_root,
                env=child_env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )
            
            # Start a thread to read stdout and write to log in real-time
            def _stream_output():
                try:
                    with open(self._log_path, "a", encoding="utf-8") as f:
                        for line in iter(self._bot_process.stdout.readline, b''):
                            decoded_line = line.decode("utf-8", errors="replace")
                            f.write(decoded_line)
                            f.flush()
                except Exception:
                    pass
                    pass
            
            self._bot_thread = threading.Thread(target=_stream_output, daemon=True)
            self._bot_thread.start()
            
            return {"success": True, "course_id": course_id, "pid": self._bot_process.pid}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def stop_bot(self) -> dict:
        """Terminate the bot subprocess."""
        if not self._bot_process or self._bot_process.poll() is not None:
            return {"success": True, "message": "Bot is not running."}
        
        try:
            self._bot_process.terminate()
            try:
                self._bot_process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self._bot_process.kill()
            self._bot_process = None
            return {"success": True, "message": "Bot stopped."}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def is_bot_running(self) -> dict:
        """Check if the bot subprocess is still alive."""
        running = self._bot_process is not None and self._bot_process.poll() is None
        exit_code = None
        if self._bot_process and self._bot_process.poll() is not None:
            exit_code = self._bot_process.returncode
        return {"running": running, "exit_code": exit_code}
    
    # ── Status & Logs ──
    
    def get_status(self) -> dict:
        """Read SQLite database to get current progress. Reuses dashboard_server.py logic."""
        bot_status = self.is_bot_running()
        
        if not os.path.exists(self._db_path):
            return {
                "bot_running": bot_status["running"],
                "status": "RUNNING" if bot_status["running"] else "OFFLINE",
                "course_id": "",
                "progress_percent": 0,
                "completed_count": 0,
                "total_count": 0,
                "current_node": "",
                "completed_nodes": [],
                "syllabus_nodes": [],
            }
        
        try:
            conn = sqlite3.connect(self._db_path)
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM course_state ORDER BY updated_at DESC LIMIT 1").fetchone()
            
            if not row:
                conn.close()
                return {
                    "bot_running": bot_status["running"],
                    "status": "RUNNING" if bot_status["running"] else "IDLE",
                    "course_id": "",
                    "progress_percent": 0,
                    "completed_count": 0,
                    "total_count": 0,
                    "current_node": "",
                    "completed_nodes": [],
                    "syllabus_nodes": [],
                }
            
            course_id = row["course_id"]
            current_node = row["current_node_id"] or ""
            completed_nodes = json.loads(row["completed_nodes_json"])
            syllabus_nodes = json.loads(row["syllabus_nodes_json"]) if row["syllabus_nodes_json"] else []
            updated_at = row["updated_at"]
            
            is_active = (time.time() - updated_at) < 15.0
            
            if bot_status["running"]:
                status = "RUNNING"
            elif is_active:
                status = "RUNNING"
            else:
                status = "IDLE"
            
            total_count = len(syllabus_nodes)
            completed_count = len(completed_nodes)
            progress_percent = round((completed_count / total_count) * 100, 1) if total_count > 0 else 0
            
            conn.close()
            
            return {
                "bot_running": bot_status["running"],
                "status": status,
                "course_id": course_id,
                "progress_percent": progress_percent,
                "completed_count": completed_count,
                "total_count": total_count,
                "current_node": current_node,
                "completed_nodes": completed_nodes,
                "syllabus_nodes": syllabus_nodes,
            }
        except Exception as e:
            return {
                "bot_running": bot_status["running"],
                "status": "ERROR",
                "course_id": "",
                "progress_percent": 0,
                "completed_count": 0,
                "total_count": 0,
                "current_node": "",
                "completed_nodes": [],
                "syllabus_nodes": [],
                "error": str(e)
            }
    
    def get_log_tail(self, n: int = 50) -> dict:
        """Read the last N lines of the log file."""
        if not os.path.exists(self._log_path):
            return {"lines": ["Waiting for bot to start..."]}
        try:
            with open(self._log_path, "r", encoding="utf-8") as f:
                all_lines = f.readlines()
            tail = [l.strip() for l in all_lines[-n:]]
            return {"lines": tail}
        except Exception as e:
            return {"lines": [f"Error reading log: {e}"]}
            
    def get_license_status(self, force_refresh: bool = False) -> dict:
        """Query the licensing server to check the saved token status with session caching and soft TTL."""
        with self._cache_lock:
            now = time.time()
            cache_age = now - self._cache_timestamp
            
            # Check if cache is still completely valid and unexpired
            if not force_refresh and self._cached_license_status is not None:
                if cache_age < self._cache_ttl_seconds:
                    return self._cached_license_status
            
            # Cache miss or explicit refresh triggered
            creds = self.has_credentials()
            engine_token = creds.get("engine_token", "")
            backend_url = creds.get("backend_url", "https://coursera-licensing-service.onrender.com")
            
            if not engine_token:
                return {"success": False, "error": "No token saved."}
                
            try:
                status_url = f"{backend_url.rstrip('/')}/api/v1/web/status"
                fingerprint = get_device_fingerprint()
                response = requests.post(
                    status_url,
                    json={"key": engine_token},
                    headers={"X-Device-ID": fingerprint},
                    timeout=10
                )
                if response.status_code == 200:
                    result = {"success": True, "data": response.json()}
                    # Update cache safely under lock boundaries
                    self._cached_license_status = result
                    self._cache_timestamp = now
                    return result
                else:
                    try:
                        err_detail = response.json().get("detail", "Unknown server error")
                    except Exception:
                        err_detail = response.text
                    result = {"success": False, "error": err_detail}
                    # Update cache safely even for server errors so we don't spam requests
                    self._cached_license_status = result
                    self._cache_timestamp = now
                    return result
            except Exception as e:
                # Network failure fallback strategy: If cache exists, return it as temporary grace
                if self._cached_license_status is not None:
                    return self._cached_license_status
                return {"success": False, "error": f"Network error: {e}"}

    def claim_trial(self, email: str) -> dict:
        """Request a free 24-hour trial key using the local device fingerprint (HWID)."""
        if not email or "@" not in email:
            return {"success": False, "error": "Please enter a valid email address."}
            
        creds = self.has_credentials()
        backend_url = creds.get("backend_url", "https://coursera-licensing-service.onrender.com")
        
        try:
            fingerprint = get_device_fingerprint()
            trial_url = f"{backend_url.rstrip('/')}/api/v1/web/trial"
            response = requests.post(
                trial_url,
                json={"email": email.strip()},
                headers={"X-Device-ID": fingerprint},
                timeout=15
            )
            
            if response.status_code == 200:
                data = response.json()
                trial_key = data.get("key")
                if not trial_key:
                    return {"success": False, "error": "Server returned a successful status but no key was generated."}
                
                # Save the new trial key alongside existing credentials
                gemini_key = creds.get("gemini_key", "")
                webhook_url = creds.get("webhook_url", "")
                save_res = self.save_credentials(trial_key, gemini_key, webhook_url)
                if save_res.get("success"):
                    return {"success": True, "key": trial_key}
                else:
                    return {"success": False, "error": f"Key was claimed successfully but could not be saved locally: {save_res.get('error')}"}
            else:
                try:
                    err_detail = response.json().get("detail", "Unknown server error")
                except Exception:
                    err_detail = response.text
                return {"success": False, "error": err_detail}
        except Exception as e:
            return {"success": False, "error": f"Failed to connect to licensing server: {e}"}
    
    def extract_course_id(self, course_url: str) -> Optional[str]:
        """Safely parse the target course ID slug from course URL."""
        val = course_url.strip()
        if val.startswith("http://") or val.startswith("https://"):
            if "coursera.org/learn/" not in val:
                return None
            val = val.split("/learn/")[-1].split("/")[0].strip()
        
        # Enforce that the course ID is a valid slug structure (alphanumeric and dashes/underscores)
        import re
        if not re.match(r"^[a-zA-Z0-9_\-]+$", val):
            return None
            
        return val if val else None

    def import_cauth_cookie(self, course_url: str, cauth_value: str) -> Dict[str, Any]:
        """Manually import a verified CAUTH cookie value into SQLite sessions, sanitizing input."""
        import re
        COOKIE_SAFE_REGEX = re.compile(r"^[a-zA-Z0-9_\.\-\=\+\/]+$")
        
        cauth_clean = cauth_value.strip()
        
        # 1. Input Validation Guard
        if not COOKIE_SAFE_REGEX.match(cauth_clean):
            return {"success": False, "error": "Invalid character token structure detected. Input rejected."}
            
        course_id = self.extract_course_id(course_url)
        if not course_id:
            return {"success": False, "error": "Unable to safely parse the target Course ID slug."}
            
        # 2. Structural Reconstruction of standard Playwright Cookie Object Matrix
        cookie_payload = [
            {
                "name": "CAUTH",
                "value": cauth_clean,
                "domain": ".coursera.org",
                "path": "/",
                "secure": True,
                "httpOnly": True, # Hardens session memory against client-side script inspection
                "sameSite": "Lax"
            }
        ]
        
        try:
            from project_accce.orchestrator.db import ACCCEStorage
            db = ACCCEStorage(self._db_path)
            # Pass cookies directly (save_session serializes to JSON)
            db.save_session(course_id, cookie_payload, {})
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": f"Database mutation failed: {str(e)}"}

    def cleanup(self):
        """Called when the app is closing."""
        if self._bot_process and self._bot_process.poll() is None:
            self._bot_process.terminate()
            try:
                self._bot_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._bot_process.kill()

    def set_window(self, window):
        """Store the webview window instance to open file dialogs."""
        self._window = window

    def export_logs(self) -> dict:
        """Export the bot's execution logs to a file chosen by the user."""
        if not self._window:
            return {"success": False, "error": "PyWebView main frame window reference uninitialized."}
        try:
            import webview
            import shutil
            result = self._window.create_file_dialog(
                dialog_type=webview.SAVE_DIALOG,
                file_types=("Log Files (*.log)", "Text Files (*.txt)", "All Files (*.*)"),
                save_filename="accce_execution_history.log"
            )
            if not result:
                return {"success": False, "error": "Export cancelled by operator."}
            
            destination_path = result[0] if isinstance(result, list) else result
            if os.path.exists(self._log_path):
                shutil.copy2(self._log_path, destination_path)
            else:
                with open(destination_path, "w", encoding="utf-8") as f:
                    f.write("No logs available yet.")
            return {"success": True, "path": destination_path}
        except Exception as e:
            return {"success": False, "error": f"Native file write IO subsystem failure: {str(e)}"}

    def discover_courses(self) -> dict:
        """Launch headed Playwright browser to log in and capture session cookies once CAUTH is present."""
        import logging
        logger = logging.getLogger("api")
        
        session_captured = False
        captured_cookies = []
        error_message = None
        browser_closed_by_user = True
        
        # Override Playwright browsers path if frozen to locate system-wide chrome
        if getattr(sys, 'frozen', False):
            os.environ["PLAYWRIGHT_BROWSERS_PATH"] = os.path.expandvars(r"%LOCALAPPDATA%\ms-playwright")
            
        with sync_playwright() as p:
            browser = None
            try:
                # Launch headed browser cleanly without persistent context conflicts
                browser = p.chromium.launch(headless=False, args=["--no-sandbox"])
                context = browser.new_context(viewport={"width": 1024, "height": 768})
                
                # Retrieve saved cookies from general discovery profile in DB if present
                session = self._db.get_session("__discovery_profile__")
                if session and session.get("cookies"):
                    try:
                        context.add_cookies(session["cookies"])
                    except Exception as cookie_err:
                        logger.warning(f"Could not load previous session cookies into context: {cookie_err}")
                
                page = context.new_page()
                
                # Track manual closure attempts safely
                def on_page_close():
                    nonlocal browser_closed_by_user
                    logger.info("[DISCOVERY] Browser target frame closed by user context.")
                    
                page.on("close", lambda p: on_page_close())
                
                print("[ENGINE] Launching headed portal discovery dashboard instance.")
                page.goto("https://www.coursera.org/?authMode=login", timeout=60000)
                
                # Run maximum 3 minutes authentication runway
                for _ in range(180):
                    if page.is_closed():
                        break
                        
                    cookies = context.cookies()
                    # Anchor logic: Look for the structural authorization signature string
                    has_cauth = any(c.get("name") == "CAUTH" for c in cookies)
                    
                    if has_cauth:
                        # Success: Grab ALL cookies generated during the handshake sequence
                        captured_cookies = cookies
                        session_captured = True
                        browser_closed_by_user = False
                        break
                        
                    page.wait_for_timeout(1000)
                    
            except Exception as e:
                logger.error(f"Session capture telemetry failed: {e}")
                error_message = f"Interface connection failure: {str(e)}"
            finally:
                if browser:
                    try:
                        browser.close()
                    except Exception as close_err:
                        logger.debug(f"Discovery cleanup exception during browser close: {close_err}")
                        
        if error_message:
            return {"success": False, "error": error_message}
            
        if browser_closed_by_user or not session_captured:
            return {"success": False, "error": "Authentication window closed or timed out prior to login detection."}
            
        # Commit master profile snapshot records down to core database parameters
        try:
            self._db.save_session("__discovery_profile__", captured_cookies, {})
        except Exception as db_err:
            logger.error(f"Failed to save captured session cookies to database: {db_err}")
            return {"success": False, "error": f"Database mutation failed: {str(db_err)}"}
            
        return {
            "success": True,
            "message": "Coursera authentication tokens verified and securely synced."
        }
