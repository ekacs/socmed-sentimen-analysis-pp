"""
export_cert_and_batch.py
------------------------
Skrip untuk mengekspor sertifikat internal ke berkas SocMedInternalCert.cer
dan membuat skrip automatisasi pendaftaran sertifikat (Install_Certificate_Admin.bat)
agar aplikasi lolos dari pemblokiran Windows Smart App Control pada komputer target.
"""

import os
import sys
import subprocess

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
DIST_APP_DIR = os.path.join(PROJECT_ROOT, "dist", "SocMedSentimentAnalysis")
CERT_PATH = os.path.join(DIST_APP_DIR, "SocMedInternalCert.cer")
BAT_PATH = os.path.join(DIST_APP_DIR, "Install_Certificate_Admin.bat")

def setup_security_trust():
    if not os.path.exists(DIST_APP_DIR):
        os.makedirs(DIST_APP_DIR, exist_ok=True)

    print("[SECURITY SETUP] Memproses Sertifikat Kepercayaan Digital...")
    
    ps_cmd = f"""
    $cert = Get-ChildItem Cert:\\CurrentUser\\My | Where-Object {{ $_.Subject -like "*SocMed*" }} | Select-Object -First 1
    if (-not $cert) {{
        $cert = New-SelfSignedCertificate -Subject "CN=SocMed Sentiment Analysis Internal Code Signing" -Type CodeSigningCert -CertStoreLocation Cert:\\CurrentUser\\My -NotAfter (Get-Date).AddYears(5)
    }}
    Export-Certificate -Cert $cert -FilePath "{CERT_PATH}" -Type CERT | Out-Null
    Write-Host "Sertifikat diekspor ke: {CERT_PATH}"
    """
    
    res = subprocess.run(["powershell", "-ExecutionPolicy", "Bypass", "-Command", ps_cmd], capture_output=True, text=True)
    if os.path.exists(CERT_PATH):
        print(f"  [OK] Berkas Sertifikat berhasil dibuat: SocMedInternalCert.cer")
    else:
        print(f"  [WARNING] Gagal mengekspor sertifikat: {res.stderr}")

    # Buat file Install_Certificate_Admin.bat
    bat_content = """@echo off
title Registrasi Sertifikat Keamanan Windows - SocMed Sentiment Analysis
color 0A
echo ========================================================================
echo   REGISTRASI SERTIFIKAT KEAMANAN DIGITAL (WINDOWS SMART APP CONTROL)
echo ========================================================================
echo.
echo Sedang mendaftarkan sertifikat penerbit aplikasi ke Windows Certificate Store...
echo.

cd /d "%~dp0"

net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [PERINGATAN] Harap jalankan file ini sebagai Administrator!
    echo Klik kanan file "Install_Certificate_Admin.bat" -> Run as Administrator.
    echo.
    pause
    exit /b 1
)

certutil -addstore -f "Root" SocMedInternalCert.cer
certutil -addstore -f "TrustedPublisher" SocMedInternalCert.cer

echo.
echo ========================================================================
echo [SUKSES] Sertifikat Kepercayaan Berhasil Terpasang!
echo Aplikasi "SocMedSentimentAnalysis.exe" sekarang aman dan dapat dijalankan.
echo ========================================================================
echo.
pause
"""
    
    with open(BAT_PATH, "w", encoding="cp1252") as f:
        f.write(bat_content)
    
    print(f"  [OK] Skrip Pemasangan Sertifikat Administrator dibuat: Install_Certificate_Admin.bat")

if __name__ == "__main__":
    setup_security_trust()
