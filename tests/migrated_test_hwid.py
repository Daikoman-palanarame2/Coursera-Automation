import os
import sys
import platform
import subprocess
import hashlib
import uuid

def test_hwid():
    system = platform.system()
    hardware_identifiers = []
    
    print(f"System: {system}")
    
    if system == "Windows":
        # A. Motherboard UUID
        try:
            out = subprocess.check_output("wmic csproduct get uuid", shell=True, errors='ignore')
            uuid_val = "".join([line.strip() for line in out.splitlines() if line.strip() and "UUID" not in line])
            print(f"Motherboard UUID: {uuid_val}")
            if uuid_val and "FFFFFFFF" not in uuid_val and "00000000" not in uuid_val:
                hardware_identifiers.append("win_board_uuid:" + uuid_val)
        except Exception as e:
            print(f"Error Motherboard UUID: {e}")
            
        # B. BIOS Serial Number
        try:
            out = subprocess.check_output("wmic bios get serialnumber", shell=True, errors='ignore')
            serial_val = "".join([line.strip() for line in out.splitlines() if line.strip() and "SerialNumber" not in line])
            print(f"BIOS Serial: {serial_val}")
            if serial_val and "Default string" not in serial_val:
                hardware_identifiers.append("win_bios_serial:" + serial_val)
        except Exception as e:
            print(f"Error BIOS Serial: {e}")

        # C. CPU ID
        try:
            out = subprocess.check_output("wmic cpu get processorid", shell=True, errors='ignore')
            cpu_val = "".join([line.strip() for line in out.splitlines() if line.strip() and "ProcessorId" not in line])
            print(f"CPU ProcessorId: {cpu_val}")
            if cpu_val:
                hardware_identifiers.append("win_cpu_id:" + cpu_val)
        except Exception as e:
            print(f"Error CPU ID: {e}")

        # D. Registry MachineGuid
        try:
            import winreg
            registry = winreg.ConnectRegistry(None, winreg.HKEY_LOCAL_MACHINE)
            key = winreg.OpenKey(registry, r"SOFTWARE\Microsoft\Cryptography")
            machine_guid, _ = winreg.QueryValueEx(key, "MachineGuid")
            print(f"Registry MachineGuid: {machine_guid}")
            if machine_guid:
                hardware_identifiers.append("win_reg_guid:" + machine_guid)
        except Exception as e:
            print(f"Error Registry MachineGuid: {e}")

    try:
        mac = str(uuid.getnode())
        print(f"MAC: {mac}")
        if mac:
            hardware_identifiers.append("fallback_mac:" + mac)
    except Exception as e:
        print(f"Error MAC: {e}")
        
    print(f"Collected identifiers: {hardware_identifiers}")
    fingerprint_input = "|".join(hardware_identifiers).encode('utf-8')
    hwid = hashlib.sha256(fingerprint_input).hexdigest()
    print(f"Final HWID (SHA-256): {hwid}")

if __name__ == "__main__":
    test_hwid()
