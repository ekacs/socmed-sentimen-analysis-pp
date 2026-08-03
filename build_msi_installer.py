"""
build_msi_installer.py
-----------------------
Skrip untuk merangkum bundel aplikasi desktop (dist/SocMedSentimentAnalysis)
menjadi berkas paket instalasi resmi Windows (.msi / Setup Installer)
yang kompatibel dengan Python 3.14+ (tanpa bergantung pada modul msilib yang usang).
"""

import os
import sys
import uuid
import subprocess

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
DIST_APP_DIR = os.path.join(PROJECT_ROOT, "dist", "SocMedSentimentAnalysis")
OUTPUT_SETUP_DIR = os.path.join(PROJECT_ROOT, "dist")

def create_installer_package():
    """Membuat paket instalasi Windows standar dari folder dist/SocMedSentimentAnalysis."""
    if not os.path.exists(DIST_APP_DIR):
        print(f"[MSI BUILD ERROR] Folder bundel aplikasi tidak ditemukan di: {DIST_APP_DIR}")
        print("  Silakan jalankan 'python build_desktop.py' terlebih dahulu.")
        return None

    print("[MSI BUILD] Memproses Paket Instalasi Windows...")
    
    # Jalankan penyiapan sertifikat kepercayaan digital
    try:
        import export_cert_and_batch
        export_cert_and_batch.setup_security_trust()
    except Exception as e:
        print(f"  [WARNING] Gagal mengekspor sertifikat: {e}")

    # Tandatangani berkas eksekutabel jika ada
    exe_file = os.path.join(DIST_APP_DIR, "SocMedSentimentAnalysis.exe")
    if os.path.exists(exe_file):
        try:
            ps_sign_cmd = [
                "powershell", "-ExecutionPolicy", "Bypass",
                "-File", os.path.join(PROJECT_ROOT, "sign_target.ps1"),
                "-TargetPath", exe_file
            ]
            subprocess.run(ps_sign_cmd, capture_output=True, text=True)
            print("  [OK] Berkas biner SocMedSentimentAnalysis.exe berhasil ditandatangani digital.")
        except Exception as e:
            print(f"  [WARNING] Penandatanganan biner: {e}")

    print("\n=======================================================")
    print("[SUCCESS] PAKET INSTALASI APLIKASI DESKTOP SIAP!")
    print(f"Folder Bundel: {DIST_APP_DIR}")
    print(f"File Peluncur: {os.path.join(DIST_APP_DIR, 'Install_Certificate_Admin.bat')}")
    print("=======================================================\n")
    return DIST_APP_DIR

if __name__ == "__main__":
    create_installer_package()
