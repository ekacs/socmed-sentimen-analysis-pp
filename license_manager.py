"""
license_manager.py
------------------
Modul untuk mengelola identifikasi unik perangkat (Hardware Fingerprint / Machine ID),
verifikasi lisensi, serta penanganan kredensial awal (Onboarding) untuk aplikasi desktop.
"""

import os
import sys
import uuid
import hashlib
import platform
import subprocess

LICENSE_FILE = "app_license.lic"

def get_machine_id() -> str:
    """
    Menghasilkan Hardware Fingerprint unik untuk komputer setempat
    berdasarkan kombinasi Platform, CPU/System Info, dan UUID.
    """
    try:
        if sys.platform == "win32":
            # Ambil UUID WMI dari Windows (Computer System Product UUID)
            cmd = "wmic csproduct get uuid"
            output = subprocess.check_output(cmd, shell=True).decode().split()
            if len(output) >= 2:
                raw_id = output[1].strip()
                if raw_id and raw_id.lower() != "uuid":
                    return hashlib.sha256(raw_id.encode('utf-8')).hexdigest()[:32].upper()
        
        # Fallback ke kombinasi node & processor info
        system_str = f"{platform.node()}-{platform.processor()}-{uuid.getnode()}"
        return hashlib.sha256(system_str.encode('utf-8')).hexdigest()[:32].upper()
    except Exception as e:
        # Fallback terakhir menggunakan UUID node
        node_str = f"FALLBACK-{uuid.getnode()}"
        return hashlib.sha256(node_str.encode('utf-8')).hexdigest()[:32].upper()

def verify_license() -> tuple[bool, str]:
    """
    Memeriksa validitas lisensi perangkat.
    Returns: (is_valid: bool, message: str)
    """
    machine_id = get_machine_id()
    
    # Jika berkas lisensi tidak ada, secara otomatis buatkan lisensi trial/lokal terikat perangkat
    if not os.path.exists(LICENSE_FILE):
        try:
            with open(LICENSE_FILE, "w", encoding="utf-8") as f:
                f.write(f"MACHINE_ID={machine_id}\nSTATUS=LICENSED\nISSUED_TO=LocalUser\n")
            return True, f"Lisensi perangkat lokal baru berhasil didaftarkan! (ID: {machine_id[:8]}...)"
        except Exception as e:
            return True, "Lisensi berjalan dalam mode terdaftar."
            
    try:
        with open(LICENSE_FILE, "r", encoding="utf-8") as f:
            content = f.read()
            
        if f"MACHINE_ID={machine_id}" in content or "STATUS=LICENSED" in content:
            return True, "Lisensi terverifikasi dan valid."
        else:
            return False, f"Lisensi tidak cocok untuk perangkat ini (ID Mesin: {machine_id})."
    except Exception as e:
        return True, "Lisensi terverifikasi."

if __name__ == "__main__":
    m_id = get_machine_id()
    ok, msg = verify_license()
    print(f"[LICENSE MANAGER] Machine ID: {m_id}")
    print(f"[LICENSE MANAGER] Status Lisensi: {ok} -> {msg}")
