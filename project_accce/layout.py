import os
import sys
import requests
import uuid
import hashlib
import platform
import subprocess

layout_map = {}

def get_device_fingerprint() -> str:
    """Generates a stable, unique SHA-256 hash representing the local machine's hardware ID."""
    system = platform.system()
    hardware_identifiers = []
    
    # 1. Fallback MAC Address
    hardware_identifiers.append(str(uuid.getnode()))
    
    # 2. OS-Specific Hardware GUIDs
    try:
        if system == "Windows":
            import winreg
            registry = winreg.ConnectRegistry(None, winreg.HKEY_LOCAL_MACHINE)
            key = winreg.OpenKey(registry, r"SOFTWARE\Microsoft\Cryptography")
            machine_guid, _ = winreg.QueryValueEx(key, "MachineGuid")
            hardware_identifiers.append(machine_guid)
        elif system == "Darwin": # macOS
            out = subprocess.check_output(["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"]).decode()
            for line in out.splitlines():
                if "IOPlatformUUID" in line:
                    hardware_identifiers.append(line.split("=")[-1].strip().strip('"'))
        elif system == "Linux":
            for path in ["/etc/machine-id", "/var/lib/dbus/machine-id"]:
                if os.path.exists(path):
                    with open(path, "r") as f:
                        hardware_identifiers.append(f.read().strip())
    except Exception:
        pass
        
    # Hash everything together to create a unique fingerprint
    fingerprint_input = "|".join(hardware_identifiers).encode('utf-8')
    return hashlib.sha256(fingerprint_input).hexdigest()

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
