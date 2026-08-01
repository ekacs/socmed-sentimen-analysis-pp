"""
sign_code.py
------------
Skrip otomatisasi untuk membuat Self-Signed Code Signing Certificate
dan menandatangani berkas .exe dan .msi agar lolos dari pemblokiran
Windows SmartScreen & Smart App Control pada komputer internal.
"""

import os
import sys
import subprocess

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
CERT_NAME = "SocMed Sentiment Analysis Internal Code Signing"

def ensure_self_signed_cert():
    """Membuat dan meng-install Self-Signed Code Signing Certificate di Windows."""
    print("[SIGNING] Memeriksa Self-Signed Code Signing Certificate...")
    
    ps_cmd = f"""
    $cert = Get-ChildItem Cert:\\CurrentUser\\My | Where-Object {{ $_.Subject -like "*{CERT_NAME}*" }} | Select-Object -First 1
    if (-not $cert) {{
        Write-Host "Membuat sertifikat digital baru..."
        $cert = New-SelfSignedCertificate -Subject "CN={CERT_NAME}" -Type CodeSigningCert -CertStoreLocation Cert:\\CurrentUser\\My -NotAfter (Get-Date).AddYears(5)
        
        # Trust Certificate di Trusted Root & Trusted Publisher (CurrentUser)
        $rootStore = Get-Item Cert:\\CurrentUser\\Root
        $rootStore.Open("ReadWrite")
        $rootStore.Add($cert)
        $rootStore.Close()
        
        $pubStore = Get-Item Cert:\\CurrentUser\\TrustedPublisher
        $pubStore.Open("ReadWrite")
        $pubStore.Add($cert)
        $pubStore.Close()
    }}
    Write-Host "Thumbprint:" $cert.Thumbprint
    """
    
    res = subprocess.run(["powershell", "-Command", ps_cmd], capture_output=True, text=True)
    if res.returncode == 0:
        print("  [OK] Sertifikat digital siap digunakan.")
        return True
    else:
        print(f"  [WARNING] Gagal menyiapkan sertifikat otomatis: {res.stderr}")
        return False

def sign_file(file_path):
    """Menandatangani berkas .exe atau .msi dengan sertifikat digital."""
    if not os.path.exists(file_path):
        print(f"  [ERROR] Berkas tidak ditemukan: {file_path}")
        return False
        
    print(f"[SIGNING] Menandatangani berkas: {os.path.basename(file_path)}...")
    
    ps_cmd = f"""
    $cert = Get-ChildItem Cert:\\CurrentUser\\My | Where-Object {{ $_.Subject -like "*{CERT_NAME}*" }} | Select-Object -First 1
    if ($cert) {{
        Set-AuthenticodeSignature -FilePath "{file_path}" -Certificate $cert -HashAlgorithm SHA256
    }} else {{
        Write-Error "Sertifikat digital tidak ditemukan."
    }}
    """
    
    res = subprocess.run(["powershell", "-Command", ps_cmd], capture_output=True, text=True)
    if res.returncode == 0 and ("Valid" in res.stdout or "Status" in res.stdout or "SignerCertificate" in res.stdout):
        print(f"  [OK] Berkas berhasil ditandatangani digital: {os.path.basename(file_path)}")
        return True
    else:
        print(f"  [WARNING] Hasil penandatanganan: {res.stdout.strip() or res.stderr.strip()}")
        return False

if __name__ == "__main__":
    if ensure_self_signed_cert():
        exe_path = os.path.join(PROJECT_ROOT, "dist", "SocMedSentimentAnalysis", "SocMedSentimentAnalysis.exe")
        if os.path.exists(exe_path):
            sign_file(exe_path)
