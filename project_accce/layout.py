import os
import sys
import requests
import uuid
import hashlib
import platform
import subprocess
import re

layout_map = {}

def is_generic_identifier(val: str) -> bool:
    """Helper to detect virtual machine or unconfigured generic hardware IDs."""
    v = val.strip().lower()
    if not v:
        return True
    # Strip common non-alphanumeric chars
    clean_v = "".join(c for c in v if c.isalnum())
    if not clean_v:
        return True
    # Check if string is composed of only a single repeating character (e.g. all 0s, all fs)
    if len(set(clean_v)) <= 1:
        return True
    # Check for common VM / OEM placeholders
    placeholders = [
        "oem", "o.e.m", "default string", "to be filled", "not specified",
        "not applicable", "none", "serial", "chassis", "system"
    ]
    for p in placeholders:
        if p in v:
            return True
    return False

def get_device_fingerprint() -> str:
    """Generates a stable, unique SHA-256 hash representing the local machine's hardware ID."""
    system = platform.system()
    components = []
    
    # 1. OS-Specific Hardware GUIDs
    try:
        if system == "Windows":
            # A. Read MachineGuid (extremely stable and unique OS-level key)
            try:
                import winreg
                key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography")
                machine_guid, _ = winreg.QueryValueEx(key, "MachineGuid")
                if machine_guid and not is_generic_identifier(machine_guid):
                    components.append("win_reg_guid:" + machine_guid)
            except Exception:
                pass

            # B. Read BIOS / Motherboard info from Registry (100% silent, no subprocess)
            try:
                import winreg
                key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\BIOS")
                board_prod = winreg.QueryValueEx(key, "BaseBoardProduct")[0]
                board_man = winreg.QueryValueEx(key, "BaseBoardManufacturer")[0]
                if board_prod and not is_generic_identifier(board_prod):
                    components.append("win_board_prod:" + board_prod)
                if board_man and not is_generic_identifier(board_man):
                    components.append("win_board_man:" + board_man)
            except Exception:
                pass

            # C. Read CPU identifier from Registry (100% silent, no subprocess)
            try:
                import winreg
                key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0")
                cpu_identifier = winreg.QueryValueEx(key, "Identifier")[0]
                cpu_name = winreg.QueryValueEx(key, "ProcessorNameString")[0]
                if cpu_identifier and not is_generic_identifier(cpu_identifier):
                    components.append("win_cpu_ident:" + cpu_identifier)
                if cpu_name and not is_generic_identifier(cpu_name):
                    components.append("win_cpu_name:" + cpu_name)
            except Exception:
                pass

        elif system == "Darwin": # macOS
            try:
                out = subprocess.check_output(["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"]).decode()
                for line in out.splitlines():
                    if "IOPlatformUUID" in line:
                        uuid_str = line.split("=")[-1].strip().strip('"')
                        if uuid_str and not is_generic_identifier(uuid_str):
                            components.append("mac_uuid:" + uuid_str)
                            break
            except Exception:
                pass
        elif system == "Linux":
            for path in ["/etc/machine-id", "/var/lib/dbus/machine-id"]:
                if os.path.exists(path):
                    try:
                        with open(path, "r") as f:
                            val = f.read().strip()
                            if val and not is_generic_identifier(val):
                                components.append("linux_machine_id:" + val)
                                break
                    except Exception:
                        pass
    except Exception:
        pass
        
    # 2. Network Card MAC Address Fallback
    try:
        mac = str(uuid.getnode())
        if mac and not is_generic_identifier(mac):
            components.append("fallback_mac:" + mac)
    except Exception:
        pass
        
    # Hash everything together to create a unique fingerprint (force lower and strip)
    raw_fingerprint = "|".join(components).lower().strip()
    return hashlib.sha256(raw_fingerprint.encode('utf-8')).hexdigest()

def fetch_layout_map():
    """
    Fetches the latest layout parsing map from the remote licensing server.
    Handles payment status checks and triggers the paywall terminal display if required.
    """
    global layout_map
    
    backend_url = os.getenv("COURSERA_ENGINE_BACKEND_URL", "https://coursera-automation-backend.onrender.com").rstrip("/")
    api_key = os.getenv("COURSERA_ENGINE_TOKEN")
    
    if not api_key:
        print("\n" + "!"*70)
        print("[WARNING] CONFIGURATION ERROR: COURSERA_ENGINE_TOKEN is not set.")
        print("Please configure this environment variable with your anonymous access token.")
        print("!"*70 + "\n")
        sys.exit(1)
        
    try:
        fingerprint = get_device_fingerprint()
        response = requests.get(
            f"{backend_url}/api/v1/layout-map",
            headers={
                "X-API-Key": api_key,
                "X-Device-ID": fingerprint
            },
            timeout=60
        )
        
        # Check for Paywall / Payment Required
        if response.status_code == 402:
            data = response.json()
            payment = data.get("payment_details", {})
            print("\n" + "="*80)
            print(" [WARNING] PAYWALL ACTIVE: Free trial run limits exhausted.")
            print("="*80)
            print(f" To unlock 1 month of unlimited automated runs, please send exactly:")
            print(f" -> \033[92m{payment.get('amount')} {payment.get('token')}\033[0m")
            print(f" on the \033[93m{payment.get('suggested_chain', '').upper()}\033[0m network to your master payment address:")
            print(f" -> \033[96m{payment.get('destination_address')}\033[0m")
            print("-"*80)
            print(" The server will automatically detect your payment on-chain and credit")
            print(" your account within a few minutes of transaction confirmation.")
            print("="*80 + "\n")
            sys.exit(0)
            
        if response.status_code == 403:
            print("\n[WARNING] ACCESS DENIED: The provided COURSERA_ENGINE_TOKEN is invalid.")
            sys.exit(1)
            
        if response.status_code != 200:
            print(f"\n[WARNING] SERVER ERROR: Failed fetching layout mapping (HTTP {response.status_code}).")
            sys.exit(1)
            
        layout_map.clear()
        layout_map.update(response.json().get("layout_map", {}))
        
        # Local override to prevent generic footer Continue button conflicts on quizzes
        if "start_quiz_button" in layout_map:
            layout_map["start_quiz_button"] = layout_map["start_quiz_button"].replace("button:has-text('Continue'), ", "button:has-text('Continue attempt'), ")
        
        # Local override to prevent false positives from generic wrapper forms during quiz loading
        if "quiz_container" in layout_map:
            layout_map["quiz_container"] = "div[data-testid^='part-Submission_'], .rc-FormQuestion, .question-container, .rc-Option"
        
    except requests.exceptions.RequestException as e:
        print(f"\n[WARNING] NETWORK ERROR: Could not connect to licensing server: {e}")
        sys.exit(1)

def get_selector(key: str) -> str:
    """
    Retrieves the layout selector for the given element key.
    Exits with an error if the layout map was not fetched or doesn't contain the key.
    """
    if not layout_map:
        # If lookup is called before fetch, fetch it automatically
        fetch_layout_map()
        
    selector = layout_map.get(key)
    if not selector:
        print(f"\n[WARNING] LAYOUT CONFLICT: Selector for '{key}' is missing. Please contact support.")
        sys.exit(1)
        
    return selector
