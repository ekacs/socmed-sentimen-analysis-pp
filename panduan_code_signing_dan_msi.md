# Panduan Pengemasan Windows Installer (.msi) & Digital Code Signing

Dokumen ini menjelaskan alur pengemasan aplikasi desktop **Social Media Sentiment Analysis (v1.1)** menjadi berkas instalasi resmi **Windows Installer (.msi)** serta penerapan **Digital Code Signing (Tanda Tangan Digital)** untuk komputer internal maupun distribusi publik.

---

## 🔒 Mengapa Membutuhkan Digital Code Signing?

Fitur keamanan **Windows Defender SmartScreen** dan **Smart App Control** di Windows 10/11 secara otomatis memblokir eksekusi file `.exe` atau `.msi` yang:
1. Tidak memiliki tanda tangan digital (*Unknown Publisher*).
2. Memiliki sertifikat digital yang belum didaftarkan pada daftar *Trusted Root Certification Authorities* atau *Trusted Publishers*.

Dengan menerapkan **Digital Code Signing**, berkas installer dan aplikasi `.exe` akan memiliki identitas penerbit (*Publisher Identity*) resmi yang diakui oleh Windows OS.

---

## ⚙️ 1. Alur Pengemasan Komputer Internal (Self-Signed Code Signing)

Untuk instalasi pada **komputer internal perusahaan / laboratorium**, Anda dapat memanfaatkan sertifikat digital internal gratis menggunakan skrip PowerShell yang telah disediakan.

### Langkah-langkah di Komputer Pengembang:
1. Jalankan skrip pembentuk sertifikat dan penandatanganan biner:
   ```powershell
   powershell -ExecutionPolicy Bypass -File create_internal_cert.ps1 -FilePath "dist/SocMedSentimentAnalysis/SocMedSentimentAnalysis.exe"
   ```
2. Skrip ini akan secara otomatis:
   * Membuat *Self-Signed Code Signing Certificate* bernama **"SocMed Sentiment Analysis Internal Code Signing"**.
   * Memasukkan sertifikat tersebut ke dalam *CertStore* lokal (`Trusted Root` & `Trusted Publishers`).
   * Menandatangani berkas `.exe` / `.msi`.

### Langkah Pendaftaran di Komputer Klien / Target Internal (Satu Kali Setup):
Agar komputer klien internal tidak memunculkan peringatan SmartScreen:
1. Ekspor sertifikat digital dari komputer pengembang:
   ```powershell
   $cert = Get-ChildItem Cert:\CurrentUser\My | Where-Object { $_.Subject -like "*SocMed*" } | Select-Object -First 1
   Export-Certificate -Cert $cert -FilePath "SocMedInternalCert.cer"
   ```
2. Salin file `SocMedInternalCert.cer` ke komputer klien internal, lalu jalankan perintah berikut sebagai Administrator:
   ```cmd
   certutil -addstore -f "Root" SocMedInternalCert.cer
   certutil -addstore -f "TrustedPublisher" SocMedInternalCert.cer
   ```

---

## 🌐 2. Alur Pengemasan Publik / Komersial (EV Code Signing Certificate)

Jika aplikasi akan didistribusikan secara luas ke masyarakat / umum melalui internet tanpa perlu menginstal berkas sertifikat manual:

1. **Pembelian Sertifikat**:
   Beli **EV (Extended Validation) Code Signing Certificate** atau **OV Code Signing Certificate** dari CA resmi seperti **DigiCert**, **Sectigo**, atau **GlobalSign**.
2. **Penandatanganan Berkas**:
   Gunakan perkakas standar Windows SDK `signtool.exe`:
   ```cmd
   signtool sign /f "SertifikatResmi.pfx" /p "PasswordSertifikat" /tr http://timestamp.digicert.com /td sha256 /fd sha256 "dist\SocMedSentimentAnalysis\SocMedSentimentAnalysis.exe"
   ```

---

## 🛠️ 3. Pengemasan Menjadi Windows Installer (.msi)

Berkas installer standar Windows `.msi` dapat dibuat dan ditandatangani secara otomatis melalui skrip pembangun [build_desktop.py](file:///d:/Documents/%23ptincap/socmed-sentimen-analysis-pp/build_desktop.py) atau skrip [create_internal_cert.ps1](file:///d:/Documents/%23ptincap/socmed-sentimen-analysis-pp/create_internal_cert.ps1).

### Menjalankan Build Penuh:
```powershell
.\venv\Scripts\python.exe build_desktop.py
```
Hasil pengemasan dan penandatanganan akan secara otomatis diletakkan pada direktori:
📁 **`D:\Documents\#ptincap\socmed-sentimen-analysis-pp\dist\SocMedSentimentAnalysis`**
