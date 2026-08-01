"""
build_msi_installer.py
-----------------------
Skrip untuk merangkum bundel aplikasi desktop (dist/SocMedSentimentAnalysis)
menjadi berkas instalasi resmi Windows Installer (.msi) serta melakukan
penandatanganan digital (Code Signing).
"""

import os
import sys
import uuid
import msilib
import shutil

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
DIST_APP_DIR = os.path.join(PROJECT_ROOT, "dist", "SocMedSentimentAnalysis")
OUTPUT_MSI_PATH = os.path.join(PROJECT_ROOT, "dist", "SocMedSentimentAnalysis_v1.1_Setup.msi")

def create_msi_installer():
    """Membuat file installer .msi standar Windows dari folder dist/SocMedSentimentAnalysis."""
    if not os.path.exists(DIST_APP_DIR):
        print(f"[MSI BUILD] Error: Folder bundel tidak ditemukan di {DIST_APP_DIR}")
        return None

    print("[MSI BUILD] Menyusun Windows Installer (.msi)...")
    
    if os.path.exists(OUTPUT_MSI_PATH):
        try:
            os.remove(OUTPUT_MSI_PATH)
        except Exception:
            pass

    # Inisialisasi Database MSI
    product_code = "{" + str(uuid.uuid4()).upper() + "}"
    upgrade_code = "{A8F1C3D2-901B-4E5F-82D4-3C7E9A1B2C3D}"
    
    db = msilib.OpenDatabase(OUTPUT_MSI_PATH, msilib.MSIDBOPEN_CREATE)
    msilib.init_database(db, "SocMedAppSchema.wxs", "SocMedApp", product_code, "1.1.0", "Laboratorium Kebijakan Publik", upgrade_code)
    
    # Konfigurasi Properti MSI
    msilib.add_data(db, "Property", [
        ("ProductName", "Social Media Sentiment Analysis"),
        ("ProductVersion", "1.1.0"),
        ("Manufacturer", "Parahyangan Public Policy Lab"),
        ("ARPPRODUCTICON", "AppIcon"),
        ("ARPHELPLINK", "https://unpar.ac.id"),
    ])

    # Buat komponen untuk setiap file dalam bundel
    cab = msilib.CAB("SocMedAppCab")
    root_dir = msilib.Directory(db, cab, None, "TARGETDIR", "SourceDir")
    program_files = msilib.Directory(db, cab, root_dir, "ProgramFilesFolder", "PFiles")
    app_dir = msilib.Directory(db, cab, program_files, "SocMedSentimentAnalysis", "APPDIR")
    
    feature = msilib.Feature(db, "Complete", "Main Application", "Seluruh komponen aplikasi", 1)
    
    def add_folder_to_msi(src_folder, parent_msi_dir):
        for item in os.listdir(src_folder):
            item_path = os.path.join(src_folder, item)
            if os.path.isfile(item_path):
                comp = msilib.Component(db, cab, item, msilib.gen_uuid(), parent_msi_dir)
                comp.add_file(item_path)
                feature.add_component(comp)
            elif os.path.isdir(item_path):
                safe_dirname = "".join(c for c in item if c.isalnum()) or "SubDir"
                sub_msi_dir = msilib.Directory(db, cab, parent_msi_dir, item, safe_dirname)
                add_folder_to_msi(item_path, sub_msi_dir)

    add_folder_to_msi(DIST_APP_DIR, app_dir)
    
    cab.commit(db)
    db.Commit()
    db.Close()
    
    print(f"  [OK] Windows Installer (.msi) berhasil dibuat: {OUTPUT_MSI_PATH}")
    return OUTPUT_MSI_PATH

if __name__ == "__main__":
    msi_file = create_msi_installer()
    if msi_file:
        try:
            import sign_code
            sign_code.sign_file(msi_file)
        except Exception as e:
            print(f"[SIGNING WARNING] Gagal menandatangani MSI: {e}")
