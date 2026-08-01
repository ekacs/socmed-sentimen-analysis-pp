"""
build_desktop.py
----------------
Skrip otomatisasi untuk meng-obfuscate kode Python (anti-dekompilasi)
dan membungkus aplikasi menjadi berkas desktop executable (.exe) di Windows.
"""

import os
import sys
import shutil
import subprocess

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))

FILES_TO_OBFUSCATE = [
    "app.py",
    "db_manager.py",
    "session_credentials.py",
    "license_manager.py",
    "config_parser.py",
    "nlg_generator.py",
    "01_run_scraper.py",
    "01_pipeline_data.py",
    "02_train_model.py",
    "desktop_launcher.py"
]

def check_and_install_packages():
    """Memeriksa dan menginstall library pendukung build jika belum ada."""
    required_packages = ["pyinstaller", "pyarmor", "pywebview"]
    print("[BUILD] Memeriksa dependensi pembentuk executable...")
    for pkg in required_packages:
        try:
            __import__(pkg.replace("-", "_"))
            print(f"  [OK] {pkg} terinstall.")
        except ImportError:
            print(f"  [INSTALL] Menginstall {pkg}...")
            subprocess.run([sys.executable, "-m", "pip", "install", pkg], check=True)

def clean_previous_builds():
    """Membersihkan direktori build lama."""
    print("[BUILD] Membersihkan direktori build lama...")
    for folder in ["build", "dist", "obfuscated_src"]:
        path = os.path.join(PROJECT_ROOT, folder)
        if os.path.exists(path):
            try:
                shutil.rmtree(path)
                print(f"  [OK] Dihapus: {folder}/")
            except Exception as e:
                print(f"  [WARNING] Gagal menghapus {folder}: {e}")

def run_pyarmor_obfuscation():
    """Mengacak dan mengenkripsi kode Python menggunakan PyArmor (Anti-Decompilation)."""
    print("[BUILD] Menjalankan PyArmor Obfuscation & Enkripsi Kode...")
    obf_dir = os.path.join(PROJECT_ROOT, "obfuscated_src")
    os.makedirs(obf_dir, exist_ok=True)
    
    existing_files = [f for f in FILES_TO_OBFUSCATE if os.path.exists(os.path.join(PROJECT_ROOT, f))]
    cmd = [
        sys.executable, "-m", "pyarmor.cli", "gen",
        "-O", obf_dir
    ] + existing_files
    
    try:
        res = subprocess.run(cmd, cwd=PROJECT_ROOT, capture_output=True, text=True)
        if res.returncode == 0 or os.path.exists(os.path.join(obf_dir, "desktop_launcher.py")):
            print("  [OK] PyArmor Obfuscation berhasil! Kode terenkripsi di folder obfuscated_src/")
            return obf_dir
        else:
            print(f"  [WARNING] PyArmor: {res.stderr[:200] if res.stderr else res.stdout[:200]}...")
            print("  -> Menggunakan mode fallback pengemasan langsung.")
            return PROJECT_ROOT
    except Exception as e:
        print(f"  [WARNING] Gagal menjalankan PyArmor ({e}). Menggunakan mode fallback pengemasan langsung.")
        return PROJECT_ROOT

def create_pyinstaller_spec(src_dir):
    """Membuat file spesifikasi PyInstaller (.spec)."""
    p_root = PROJECT_ROOT.replace("\\", "/")
    s_dir = src_dir.replace("\\", "/")
    
    spec_content = f"""# -*- mode: python ; coding: utf-8 -*-

import sys
import os
from PyInstaller.utils.hooks import copy_metadata, collect_data_files

block_cipher = None

datas = [
    (r'{p_root}/target_config.json', '.'),
    (r'{p_root}/models', 'models'),
]

if os.path.exists(r'{p_root}/sentimen_kebijakan.db'):
    datas.append((r'{p_root}/sentimen_kebijakan.db', '.'))

datas += copy_metadata('streamlit')
datas += collect_data_files('streamlit')
datas += collect_data_files('plotly')

hidden_imports = [
    'streamlit',
    'plotly',
    'plotly.express',
    'pandas',
    'sklearn',
    'joblib',
    'apify_client',
    'google.genai',
    'psycopg2',
    'sqlalchemy',
    'webview',
    'license_manager',
    'db_manager',
    'session_credentials',
    'nlg_generator',
    'config_parser'
]

a = Analysis(
    [r'{s_dir}/desktop_launcher.py'],
    pathex=[r'{s_dir}'],
    binaries=[],
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={{}},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='SocMedSentimentAnalysis',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,  # Set True untuk memudahkan debugging/log terminal saat testing
    icon=None
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='SocMedSentimentAnalysis',
)
"""
    spec_path = os.path.join(PROJECT_ROOT, "SocMedApp.spec")
    with open(spec_path, "w", encoding="utf-8") as f:
        f.write(spec_content)
    print("  [OK] PyInstaller spec file berhasil dibuat: SocMedApp.spec")
    return spec_path

def build_executable(spec_path):
    """Menjalankan PyInstaller untuk membentuk file .exe."""
    print("[BUILD] Menjalankan PyInstaller untuk menyusun paket Desktop...")
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", spec_path]
    res = subprocess.run(cmd)
    if res.returncode == 0:
        dist_app_path = os.path.join(PROJECT_ROOT, "dist", "SocMedSentimentAnalysis")
        print("\n=======================================================")
        print("[SUCCESS] PENGEMASAN APLIKASI DESKTOP BERHASIL SELESAI!")
        print(f"Lokasi Output Aplikasi: {dist_app_path}")
        print(f"Berkas Utama: {os.path.join(dist_app_path, 'SocMedSentimentAnalysis.exe')}")
        print("=======================================================\n")
    else:
        print("[ERROR] Terjadi kesalahan saat kompilasi PyInstaller.")

if __name__ == "__main__":
    check_and_install_packages()
    clean_previous_builds()
    src_dir = run_pyarmor_obfuscation()
    spec_path = create_pyinstaller_spec(src_dir)
    build_executable(spec_path)
