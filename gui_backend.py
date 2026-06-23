import os
import sys
import json
import time
import sqlite3
import subprocess
import threading
import webbrowser
import requests
from typing import Optional, Dict, Any, List

class ACCCEBackend:
    """Python-side API bridge exposed to the PyWebView frontend via js_api."""
    
    def __init__(self):
        self._base_dir = os.path.dirname(os.path.abspath(__file__))
        self._db_path = os.path.join(self._base_dir, "project_accce.db")
        self._log_path = os.path.join(self._base_dir, "project_accce.log")
        self._env_path = os.path.join(self._base_dir, ".env")
        self._config_path = os.path.join(self._base_dir, "config.json")
        self._bot_process: Optional[subprocess.Popen] = None
        self._bot_thread: Optional[threading.Thread] = None

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
                "backend_url": "https://coursera-licensing-service.onrender.com"
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
        
        return {
            "has_credentials": bool(engine_token and gemini_key),
            "engine_token": engine_token,
            "gemini_key": gemini_key,
            "webhook_url": env_vars.get("DISCORD_WEBHOOK_URL", ""),
            "backend_url": env_vars.get("COURSERA_ENGINE_BACKEND_URL", "https://coursera-licensing-service.onrender.com")
        }
    
    def save_credentials(self, engine_token: str, gemini_key: str, webhook_url: str = "") -> dict:
        """Write credentials to .env file."""
        try:
            lines = [
                "# ACCCE Configuration Settings",
                f"COURSERA_ENGINE_TOKEN={engine_token}",
                f"COURSERA_ENGINE_BACKEND_URL=https://coursera-licensing-service.onrender.com",
                f"GEMINI_API_KEY={gemini_key}",
            ]
            if webhook_url:
                lines.append(f"DISCORD_WEBHOOK_URL={webhook_url}")
            
            with open(self._env_path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
            
            # Also update config.json with the API key
            config = {}
            if os.path.exists(self._config_path):
                try:
                    with open(self._config_path, "r") as f:
                        config = json.load(f)
                except Exception:
                    pass
            config["api_key"] = gemini_key
            if webhook_url:
                config["webhook_url"] = webhook_url
            with open(self._config_path, "w") as f:
                json.dump(config, f, indent=2)
            
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    # ── Bot Control ──
    
    def start_bot(self, course_url: str, headless: bool = False, module: int = None) -> dict:
        """Start the ACCCE bot as a subprocess."""
        if self._bot_process and self._bot_process.poll() is None:
            return {"success": False, "error": "Bot is already running."}
        
        # Clean course URL to extract course ID
        course_id = course_url.strip()
        if "coursera.org/learn/" in course_id:
            course_id = course_id.split("/learn/")[-1].split("/")[0].strip()
        if not course_id:
            return {"success": False, "error": "Course URL or ID cannot be empty."}
        
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
        python_exe = os.path.join(self._base_dir, ".venv", "Scripts", "python.exe")
        if not os.path.exists(python_exe):
            python_exe = sys.executable
        
        cmd = [python_exe, os.path.join(self._base_dir, "main.py"), "--course-id", course_id]
        if headless:
            cmd.append("--headless")
        if module:
            cmd.extend(["--module", str(module)])
        
        try:
            # Clear log file for fresh run
            with open(self._log_path, "w", encoding="utf-8") as f:
                f.write("")
            
            self._bot_process = subprocess.Popen(
                cmd,
                cwd=self._base_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )
            
            # Start a thread to read stdout and write to log
            def _stream_output():
                try:
                    for line in iter(self._bot_process.stdout.readline, b''):
                        pass  # Output is already captured by TeeLogger in main.py
                except Exception:
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
                "status": "OFFLINE",
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
                    "status": "IDLE",
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
            
    def get_license_status(self) -> dict:
        """Query the licensing server to check the saved token status."""
        creds = self.has_credentials()
        engine_token = creds.get("engine_token", "")
        backend_url = creds.get("backend_url", "https://coursera-licensing-service.onrender.com")
        
        if not engine_token:
            return {"success": False, "error": "No token saved."}
            
        try:
            status_url = f"{backend_url.rstrip('/')}/api/v1/web/status"
            response = requests.post(
                status_url,
                json={"key": engine_token},
                timeout=10
            )
            if response.status_code == 200:
                return {"success": True, "data": response.json()}
            else:
                try:
                    err_detail = response.json().get("detail", "Unknown server error")
                except Exception:
                    err_detail = response.text
                return {"success": False, "error": err_detail}
        except Exception as e:
            return {"success": False, "error": f"Network error: {e}"}
    
    def cleanup(self):
        """Called when the app is closing."""
        if self._bot_process and self._bot_process.poll() is None:
            self._bot_process.terminate()
            try:
                self._bot_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._bot_process.kill()
