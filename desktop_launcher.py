"""
desktop_launcher.py
-------------------
Skrip Launcher Utama untuk mengoperasikan aplikasi Social Media Sentiment Analysis
sebagai aplikasi desktop mandiri (.exe) di Windows.
"""

import os
import sys
import time
import socket
import threading
import subprocess
import multiprocessing
import webbrowser

import license_manager

def get_base_dir() -> str:
    """Mendapatkan direktori dasar eksekusi (mendukung bundle PyInstaller sys._MEIPASS)."""
    if getattr(sys, 'frozen', False):
        return getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
    return os.path.dirname(os.path.abspath(__file__))

def find_free_port(default_port: int = 8501) -> int:
    """Mencari port bebas untuk server Streamlit lokal."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(('127.0.0.1', default_port))
        sock.close()
        return default_port
    except OSError:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
        sock.close()
        return port

def run_streamlit_server(port: int, base_dir: str):
    """Menjalankan server Streamlit lokal secara headless."""
    app_script = os.path.join(base_dir, "app.py")
    
    # Environment copy
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    
    cmd = [
        sys.executable,
        "-m", "streamlit", "run", app_script,
        f"--server.port={port}",
        "--server.address=127.0.0.1",
        "--server.headless=true",
        "--global.developmentMode=false",
        "--browser.gatherUsageStats=false"
    ]
    
    try:
        subprocess.run(cmd, env=env, cwd=base_dir)
    except Exception as e:
        print(f"[ERROR] Gagal menjalankan server Streamlit: {e}")

def main():
    # 1. Verifikasi Lisensi Perangkat
    ok_lic, msg_lic = license_manager.verify_license()
    if not ok_lic:
        print(f"[ERROR LISENSI] {msg_lic}")
        try:
            import pywebview
            pywebview.create_window("Error Lisensi Perangkat", html=f"<h3>❌ Lisensi Tidak Valid</h3><p>{msg_lic}</p>")
            pywebview.start()
        except Exception:
            pass
        sys.exit(1)
        
    print(f"[INFO LISENSI] {msg_lic}")
    
    # 2. Tentukan Port & Jalankan Backend Streamlit
    base_dir = get_base_dir()
    port = find_free_port(8501)
    target_url = f"http://127.0.0.1:{port}"
    
    print(f"[LAUNCHER] Memulai server Streamlit di {target_url} ...")
    
    t_server = threading.Thread(
        target=run_streamlit_server,
        args=(port, base_dir),
        daemon=True
    )
    t_server.start()
    
    # Tunggu sebentar agar server siap
    time.sleep(3)
    
    # 3. Buka Jendela Aplikasi Desktop (PyWebView GUI atau Browser Fallback)
    has_webview = False
    try:
        import webview
        has_webview = True
        print("[LAUNCHER] Membuka jendela aplikasi desktop via PyWebView...")
        webview.create_window(
            title="Social Media Sentiment Analysis for Public Policy (v1.1)",
            url=target_url,
            width=1340,
            height=860,
            resizable=True,
            min_size=(1024, 720)
        )
        webview.start()
    except Exception as e:
        print(f"[WARNING] PyWebView tidak tersedia atau bermasalah: {e}. Menggunakan peramban default.")
        webbrowser.open(target_url)
        # Tahan proses utama agar thread server tetap berjalan
        try:
            while t_server.is_alive():
                time.sleep(1)
        except KeyboardInterrupt:
            sys.exit(0)

if __name__ == "__main__":
    # KRUSIAL untuk PyInstaller Windows: Mencegah loop eksekusi subprocess rekursif
    multiprocessing.freeze_support()
    main()
