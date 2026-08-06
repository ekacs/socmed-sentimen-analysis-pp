# Aplikasi Analisis Sentimen Publik terintegrasi AI

> **Social Media & News Sentiment Analysis for Public Policy (`socmed-sentimen-analysis-pp`)**
> *Dikembangkan dalam kolaborasi riset kebijakan publik (Universitas Parahyangan bersama Prof. Tuti)*

---

## 1. Overview Aplikasi.

**Aplikasi Analisis Sentimen Publik terintegrasi AI** adalah platform analitik komprehensif yang dirancang untuk mengumpulkan, memproses, mengklasifikasikan, dan menganalisis persepsi masyarakat di media sosial serta media berita daring terkait isu dan kebijakan publik di Indonesia.

Platform ini mengintegrasikan teknologi AI fokus pada **Large Language Model (LLM)** dan **Machine Learning (Support Vector Machine / SVM)** untuk menghasilkan wawasan kebijakan (*policy insights*) yang cepat, akurat, dan bebas dari bias subjektif.

**Demo aplikasi (hosted by Streamlit Cloud Community):**

[socmed-sentimen-analysis-pp.streamlit.app](https://socmed-sentimen-analysis-pp.streamlit.app/)

### Fitur Utama.

- **Penarikan Data Multi-Platform (Multi-Source Scraping)**: Mengambil data percakapan publik secara otomatis dari Twitter/X, Instagram, LinkedIn, dan Portal Berita Utama Indonesia (Kompas, CNN Indonesia, Katadata, Detik, Tribunnews, Liputan6, Tempo, Republika, dll.) via Apify API dengan konfigurasi terstruktur per platform.
- **Prapemrosesan & Standardisasi Teks EYD berbasis LLM & Local Caching**: Saat Menggunakan Google Gemini API (`gemini-3.1-flash-lite`) dalam mode *high-speed parallel batching* terintegrasi *Local EYD Cache* (`ambil_eyd_cache`) untuk mengoreksi typo, slang, dan singkatan menjadi Bahasa Indonesia Baku (EYD) secara hemat token tanpa pengulangan teks yang pernah dibersihkan.
- **Klasifikasi Sentimen Machine Learning (SVM)**: Memprediksi sentimen publik (**Positif**, **Negatif**, **Netral**) beserta *confidence score* (skor keyakinan 0.0 - 1.0) menggunakan model Support Vector Classifier berbasis ekstraksi fitur TF-IDF.
- **Generasi Ringkasan Eksekutif Otomatis & Pemilihan Multiversi (NLG AI)**: Menggunakan kecerdasan buatan dengan persona Analis Kebijakan Publik Senior untuk menyusun Laporan Ringkasan Eksekutif 3 bagian (Situasi Saat Ini, Analisis Permasalahan, Rekomendasi Kebijakan) dengan dukungan **hingga 3 model/versi narasi interaktif** yang dapat dipilih pengguna.
- **Dukungan Penyimpanan Ganda & Penyelarasan Riwayat Topik (Dual Database Engine)**:
  - **Local SQLite** (`sentimen_kebijakan.db`): Penyimpanan mandiri secara offline.
  - **Cloud PostgreSQL (Supabase)**: Sinkronisasi data multi-pengguna di awan terintegrasi otomatisasi penulisan kata riwayat pencarian (`keysearch_history`) dan bookmark topik.
- **Antarmuka Dashboard Interaktif (Streamlit)**: Visualisasi data real-time dengan diagram donat, tren waktu interaktif, top kata kunci, breakdown engagement (likes, retweets, views), distribusi per platform sumber, filter dinamis, dan kontrol kualitas dataset 13 kolom lengkap.
- **Ekspor Laporan Publikasi (PDF)**: Membentuk laporan formal berformat PDF siap cetak (dilengkapi grafik visualisasi dan versi narasi eksekutif AI terpilih).
- **Pengemasan Aplikasi Desktop (.exe Windows)**: Dilengkapi proteksi enkripsi kode anti-dekompilasi (PyArmor) dan pengemasan executable mandiri (PyInstaller + PyWebView).

---

## 2. Arsitektur Aplikasi

Aplikasi dibangun dengan arsitektur terisolasi berprinsip *Separation of Concerns* (SoC) yang memisahkan lapisan antarmuka, layanan bisnis/pipeline AI, manajemen lisensi & kredensial, serta lapisan basis data.

```mermaid
graph TD
    UI[Desktop GUI / Streamlit Web Dashboard<br/>app.py & desktop_launcher.py] --> Session[Session Credentials & Licensing<br/>session_credentials.py & license_manager.py]
    UI --> Scraper[Multi-Platform Scraper Engine<br/>01_run_scraper.py & config_parser.py]
    Scraper -->|Apify API Actors| ExternalPlatforms[Twitter / Instagram / LinkedIn / News Portals]
    Scraper -->|RAW Data| DB[(Database Layer<br/>SQLite / PostgreSQL Supabase)]
  
    UI --> Pipeline[AI & ML Processing Pipeline<br/>01_pipeline_data.py]
    DB -->|Read RAW Data| Pipeline
    Pipeline -->|Batch Cleaning| Gemini[Google Gemini LLM API<br/>gemini-3.1-flash-lite]
    Pipeline -->|Feature Extraction & Inference| SVMModel[SVM ML Model & TF-IDF Vectorizer<br/>models/svm_model.pkl & tfidf_vectorizer.pkl]
    Pipeline -->|Update CLEANED Data| DB
  
    UI --> NLG[NLG Executive Summary Engine<br/>nlg_generator.py]
    DB -->|Aggregated Metrics| NLG
    NLG -->|Generate Narrative| Gemini
  
    UI --> Export[Report Exporter Engine<br/>PDF ReportLab]
```

### Komponen Utama Sistem

| Komponen                        | File Utama                                                                                                      | Tanggung Jawab / Fungsi                                                                               |
| :------------------------------ | :-------------------------------------------------------------------------------------------------------------- | :---------------------------------------------------------------------------------------------------- |
| **User Interface Layer**  | [`app.py`](file:///d:/Documents/%23ptincap/socmed-sentimen-analysis-pp/app.py)                                 | Dashboard utama Streamlit (visualisasi 4-tahapan, review 13 kolom, pilihan 3 narasi AI, ekspor PDF).  |
| **Desktop Launcher**      | [`desktop_launcher.py`](file:///d:/Documents/%23ptincap/socmed-sentimen-analysis-pp/desktop_launcher.py)       | Pembungkus aplikasi desktop Windows menggunakan PyWebView & headless Streamlit server.                |
| **Scraper Engine**        | [`01_run_scraper.py`](file:///d:/Documents/%23ptincap/socmed-sentimen-analysis-pp/01_run_scraper.py)           | Orkestrator penarikan data Apify (Twitter, Instagram, LinkedIn, News) & pendaftaran kata riwayat.     |
| **Config & Query Parser** | [`config_parser.py`](file:///d:/Documents/%23ptincap/socmed-sentimen-analysis-pp/config_parser.py)             | Mengolah`target_config.json` per-platform dan merangkai kueri logika pencarian Twitter Boolean.     |
| **AI & ML Pipeline**      | [`01_pipeline_data.py`](file:///d:/Documents/%23ptincap/socmed-sentimen-analysis-pp/01_pipeline_data.py)       | Pemrosesan deduplikasi RAW, EYD batch cleaning (dengan local cache), dan inferensi sentimen SVM.      |
| **Model Trainer**         | [`02_train_model.py`](file:///d:/Documents/%23ptincap/socmed-sentimen-analysis-pp/02_train_model.py)           | Pelatihan model Support Vector Machine (Linear SVM) dan ekspor pickle file (`svm_model.pkl`).       |
| **NLG Generator**         | [`nlg_generator.py`](file:///d:/Documents/%23ptincap/socmed-sentimen-analysis-pp/nlg_generator.py)             | Generasi Laporan Ringkasan Eksekutif AI persona Analis Kebijakan Publik (versi narasi terstruktur).   |
| **Database Manager**      | [`db_manager.py`](file:///d:/Documents/%23ptincap/socmed-sentimen-analysis-pp/db_manager.py)                   | Abstraksi dual DB (SQLite & Supabase PostgreSQL), sync`keysearch_history`, dan `ambil_eyd_cache`. |
| **Session Credentials**   | [`session_credentials.py`](file:///d:/Documents/%23ptincap/socmed-sentimen-analysis-pp/session_credentials.py) | Pengelolaan kredensial terisolasi per-sesi (Session State) & fungsi penilai API Key kustom.           |
| **License Manager**       | [`license_manager.py`](file:///d:/Documents/%23ptincap/socmed-sentimen-analysis-pp/license_manager.py)         | Verifikasi Hardware Fingerprint (Machine ID WMI UUID) untuk aktivasi aplikasi desktop.                |
| **Build & Obfuscation**   | [`build_desktop.py`](file:///d:/Documents/%23ptincap/socmed-sentimen-analysis-pp/build_desktop.py)             | Pengacak kode PyArmor & kompilator executable PyInstaller ke format`.exe`.                          |

---

## 3. Pipeline Data & ML.

Pipa pemrosesan data berjalan dalam 6 tahapan utama secara terstruktur dari hulu ke hilir:

```
[1. Konfigurasi Kueri] ➔ [2. Penarikan Data (Scraper)] ➔ [3. Deduplikasi RAW] ➔ [4. Standardisasi EYD (Gemini)] ➔ [5. Inferensi Sentimen (SVM)] ➔ [6. Visualisasi & NLG AI]
```

### Rincian Tahapan Pipeline:

1. **Tahap 1: Konfigurasi & Inisialisasi Kueri**

   - Parser membaca konfigurasi dari `target_config.json` (terstruktur terpisah per platform: `twitter`, `instagram`, `linkedin`, `website`) atau input sesi pengguna di Streamlit.
   - Merangkai kombinasi kata kunci (*keywords*), tagar (*hashtags*), dan profil target menjadi kueri spesifik platform (contoh: kueri boolean Twitter dengan operator `OR` & `from:`).
2. **Tahap 2: Penarikan Data Multi-Platform (Apify Scraper)**

   - **Twitter/X**: Aktor `ghSpYIW3L1RvT57NT` (Mode Search / Profile).
   - **Instagram**: Aktor `apify/instagram-hashtag-scraper` & `apify/instagram-post-scraper`.
   - **LinkedIn**: Aktor `harvestapi/linkedin-post-search` (`buIWk2uOUzTmcLsuB`).
   - **Portal Berita**: Aktor `apify/website-content-crawler` dengan mesin rendering Playwright Adaptive JS.
   - Hasil disimpan ke basis data pada tabel `log_cuitan` dengan `status = 'RAW'`, serta merekam kueri pencarian baru ke tabel `keysearch_history` (terintegrasi dengan fitur Bookmark Topik).
3. **Tahap 3: Deduplikasi Data Mentah (RAW Clean-up)**

   - Fungsi `hapus_duplikasi_data_raw()` di `db_manager.py` menghapus baris duplikat berdasarkan pencocokan Hash Konten / `platform_id` sebelum data dikirim ke API AI untuk menghemat penggunaan kuota token.
4. **Tahap 4: Standardisasi Teks EYD (LLM Batch Cleaning & Local EYD Cache)**

   - **Mekanisme Local EYD Cache (`ambil_eyd_cache`)**: Sistem secara otomatis mengecek pasangan `raw_text` ➔ `cleaned_text` dari data berstatus `CLEANED` yang tersimpan di basis data. Teks yang sudah pernah dibersihkan langsung menggunakan hasil baku tanpa memanggil Gemini API.
   - **Batch Cleaning Gemini**: Teks mentah baru yang belum ada di cache dikelompokkan dalam batch (25-50 item per kiriman JSON) dan dikirim ke Google Gemini API (`gemini-3.1-flash-lite`) untuk dikoreksi menjadi Bahasa Indonesia Baku (EYD).
   - Hasil standardisasi disimpan pada kolom `cleaned_text`.
5. **Tahap 5: Klasifikasi Sentimen Machine Learning (Linear SVM)**

   - Teks baku (`cleaned_text`) ditransformasikan menjadi vektor numerik menggunakan `tfidf_vectorizer.pkl` (max 5.000 fitur, n-gram range 1-2).
   - Model Support Vector Classifier (`svm_model.pkl`) memprediksi label sentimen (`Positif`, `Negatif`, `Netral`) dan menghitung *confidence score*.
   - Status baris data diperbarui dari `'RAW'` menjadi `'CLEANED'`.
6. **Tahap 6: Analisis Visual, Generasi Multiversi NLG Summary, & Ekspor**

   - Data `CLEANED` ditayangkan pada Dashboard Streamlit (visualisasi diagram donat, tren harian, top kata kunci, dan distribusi platform).
   - Mengagregasi metrik sentimen dan memicu `nlg_generator.py` untuk menyusun Laporan Ringkasan Eksekutif berbasis persona Analis Kebijakan Publik dengan opsi **hingga 3 versi/model narasi interaktif**.
   - Memungkinkan pengguna memilih versi narasi yang diinginkan dan mengunduh laporan berformat PDF.

---

## 4. Panduan Development dan Prasyarat Development

### A. Development Lokal (Local Machine Setup)

#### Prasyarat Perangkat Lunak & Sistem

- **Sistem Operasi**: Windows 10/11 (direkomendasikan untuk kompilasi executable desktop), macOS, atau Linux.
- **Python**: Versi `3.10.x` atau `3.11.x`.
- **Git**: Versi terbaru.
- **Kredensial / API Key**:
  - **LLM API Key**: Diperlukan untuk pembersihan EYD & NLG Ringkasan Eksekutif (default menggunakan Google Gemini).
  - **Apify API Token**: Diperlukan untuk penarikan data scraper.
  - **Supabase Database URL** *(opsional)*: Diperlukan jika menggunakan Cloud PostgreSQL.

#### Langkah Setup Lingkungan Pengembangan Lokal (Step-by-Step)

##### 1. Clone Repositori

```PowerShell
git clone https://github.com/username/socmed-sentimen-analysis-pp.git
cd socmed-sentimen-analysis-pp
```

##### 2. Buat & Aktifkan Virtual Environment

###### Pastikan komputer sudah tersintall Python library, jika belum harap lihat video tutorial ini **[How easy to Install Python in Windows 11 today](https://youtu.be/b_kLEm5vE0k)**

```PowerShell
# Windows
python -m venv venv
venv\Scripts\activate

# macOS / Linux
python3 -m venv venv
source venv/bin/activate
```

##### 3. Instal Dependensi

```PowerShell
pip install --upgrade pip
pip install -r requirements.txt
```

##### 4. Konfigurasi File Environment (`.env`)

Buat file `.env` di direktori utama (*root project*) dan lengkapi variabel berikut:

```env
GEMINI_API_KEY=YOUR_GEMINI_API_KEY_HERE
APIFY_API_TOKEN=YOUR_APIFY_API_TOKEN_HERE
DATABASE_URL=postgresql://postgres.xxx:password@aws-0-region.pooler.supabase.com:6543/postgres
```

##### 5. Generasi Data Latih & Pelatihan Model SVM Initial

Jika file model di folder `models/` belum tersedia, jalankan skrip berikut:

```PowerShell
# 1. Generasi dataset pelatihan sintetis/mock (dataset_pelatihan.csv)
python generate_mock_training_data.py

# 2. Latih model Support Vector Machine & simpan pkl file
python 02_train_model.py
```

##### 6. Menjalankan Aplikasi Web (Mode Streamlit Local)

```PowerShell
streamlit run app.py
```

Aplikasi dapat diakses melalui peramban web di `http://localhost:8501`.

##### 7. Menjalankan Aplikasi Desktop (Mode GUI Local) (unstable)

```PowerShell
python desktop_launcher.py
```

atau jalankan (klik) file *'Jalankan_Aplikasi_Desktop.bat'*

##### 8. Membangun Paket Aplikasi Desktop Executable (.exe Windows) (unstable)

1. Buat sertifikasi keamanan software secara mandiri, untuk bypass windows security (windows defender)
2. ```PowerShell
   python build_msi_installer.py
   ```

   atau jalankan (klik) file *create_internal_ceet.ps1'*
3. Lalu meng-obfuscate kode Python dengan PyArmor dan membungkusnya menjadi satu paket executable `.exe`:

```PowerShell
python 
python build_desktop.py
```

Hasil kompilasi akan berada di folder `dist/SocMedSentimentAnalysis/`terdiri dari file: Install_Certificate_Admin `Install_Certificate_Admin.bat`, `SocMedInternalC.cer` dan`SocMedSentimentAnalysis.exe`, jalankan (klik) ketiganya secara berurutan.

---

### B. Deployment & Development pada Server (Linux Production)

Untuk menjalankan aplikasi secara terpusat (*cloud server*) agar dapat diakses oleh banyak pengguna melalui jaringan/domain publik:

#### Prasyarat Server

- **OS Server**: Ubuntu 22.04 LTS / Debian 11 (direkomendasikan).
- **Spesifikasi Server**: Minimal 2 vCPU, RAM 4 GB, Storage 20 GB SSD.
- **Port**: 80 (HTTP), 4443 / 443 (HTTPS), 8501 (Streamlit Server Internal).
- **Akses**: Akses root atau user dengan hak `sudo`.

#### Langkah-Langkah Deployment Server:

##### 1. Pembaruan Paket Sistem & Instalasi Prasyarat

```Shell
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3-pip python3-venv git nginx certbot python3-certbot-nginx ufw
```

##### 2. Clone Repositori & Setup Environment di Server

```Shell
cd /var/www
sudo git clone https://github.com/username/socmed-sentimen-analysis-pp.git
sudo chown -R $USER:$USER /var/www/socmed-sentimen-analysis-pp
cd /var/www/socmed-sentimen-analysis-pp

# Buat virtualenv
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

##### 3. Konfigurasi Production Environment (`.env`)

Buat file `.env` pada server:

```Shell
nano .env
```

Isikan kredensial produksi (Gunakan Supabase PostgreSQL agar data tersimpan aman secara terpusat):

```env
GEMINI_API_KEY=YOUR_PRODUCTION_GEMINI_KEY
APIFY_API_TOKEN=YOUR_PRODUCTION_APIFY_TOKEN
DATABASE_URL=postgresql://postgres.xxx:password@aws-0-region.pooler.supabase.com:6543/postgres
```

##### 4. Jalankan Pelatihan Model SVM di Server

```Shell
python3 generate_mock_training_data.py
python3 02_train_model.py
```

##### 5. Konfigurasi Systemd Service (Daemon Background)

Buat file layanan systemd agar Streamlit berjalan otomatis saat server *booting*:

```Shell
sudo nano /etc/systemd/system/socmed-app.service
```

Isikan konfigurasi berikut:

```ini
[Unit]
Description=Social Media Sentiment Analysis Streamlit Application
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/var/www/socmed-sentimen-analysis-pp
ExecStart=/var/www/socmed-sentimen-analysis-pp/venv/bin/streamlit run app.py --server.port=8501 --server.address=127.0.0.1 --server.headless=true --browser.gatherUsageStats=false
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

*Catatan: Sesuaikan `User=ubuntu` dengan username user server Anda.*

Aktifkan dan jalankan service:

```Shell
sudo systemctl daemon-reload
sudo systemctl enable socmed-app
sudo systemctl start socmed-app
sudo systemctl status socmed-app
```

##### 6. Konfigurasi Nginx Reverse Proxy (dengan WebSocket Support)

Streamlit membutuhkan koneksi WebSocket. Buat konfigurasi Nginx:

```Shell
sudo nano /etc/nginx/sites-available/socmed-app
```

Isikan konfigurasi berikut:

```nginx
server {
    listen 80;
    server_name sentimen-kebijakan.domain.com; # Ganti dengan domain/IP server Anda

    location / {
        proxy_pass http://127.0.0.1:8501;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # WebSocket support untuk Streamlit
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 86400;
    }
}
```

Aktifkan konfigurasi Nginx & jalankan pengujian:

```Shell
sudo ln -s /etc/nginx/sites-available/socmed-app /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
```

##### 7. Pengaktifan SSL/TLS (HTTPS) dengan Certbot

```Shell
sudo certbot --nginx -d sentimen-kebijakan.domain.com
```

##### 8. Konfigurasi Firewall Server (UFW)

```Shell
sudo ufw allow 'Nginx Full'
sudo ufw allow OpenSSH
sudo ufw enable
```

##### 9. Pembaruan Kode & CI/CD Sederhana di Server

Jika terdapat pembaruan kode di repositori Git, jalankan perintah berikut di server:

```Shell
cd /var/www/socmed-sentimen-analysis-pp
git pull origin main
source venv/bin/activate
pip install -r requirements.txt
sudo systemctl restart socmed-app
```

---

## 5. Panduan Penggunaan

Aplikasi memiliki antarmuka Streamlit yang terbagi ke dalam 4 Tab Utama dan 1 Sidebar Pengaturan Kredensial:

```
┌────────────────────────────────────────────────────────────────────────┐
│ 🔐 Sidebar Pengaturan Sesi API Key & Database Engine (SQLite / Supabase)│
├───────────────┬───────────────┬───────────────┬────────────────────────┤
│    Tab 1      │    Tab 2      │    Tab 3      │         Tab 4          │
│ Penarikan Data│ Pipa Data AI  │ Review Data   │ Dashboard Visualisasi  │
│  (Scraper)    │    & ML       │ (13 Kolom)    │ Narasi AI & Cetak PDF  │
└───────────────┴───────────────┴───────────────┴────────────────────────┘
```

### 1. Sidebar: Pengaturan API Key Sesi & Database Engine

- **Mode Database**: Pilihan antara **Cloud PostgreSQL (Supabase)** atau **Local Storage (SQLite)**.
- **Kredensial Sesi (Session-Only Keys)**: Pengguna dapat memasukkan API Key kustom (Apify Token, Gemini Key, Supabase URL) yang berlaku khusus selama sesi peramban tanpa mengubah isi file `.env`.
- **Bookmark Topik Sentimen**: Mengelola dan memilih kelompok kueri kata kunci yang sering dianalisis.

### 2. Tab 1: Penarikan Data (Scraper Engine)

- Pilih platform sasaran (**Twitter / X**, **Instagram**, **LinkedIn**, atau **Portal Berita**).
- Konfigurasi parameter terpisah per platform: kata kunci pencarian, tagar (*hashtags*), profil target, rentang tanggal, dan batas maksimal data (*max results*).
- Perekaman kueri otomatis ke tabel `keysearch_history` agar topik yang baru dicari langsung tersimpan ke riwayat bookmark.
- Klik **🚀 Jalankan Penarikan Data (Scraper)** untuk memulai proses scraping di latar belakang.

### 3. Tab 2: Pipa Data & Pemrosesan AI dan Support Vector Machine (SVM) Machine Learning

- Menampilkan ringkasan status data mentah (**RAW**) yang belum diproses.
- Klik **⚡ Jalankan Pipa Data & Pemrosesan AI** untuk memicu deduplikasi RAW, pembersihan teks EYD berbasis **LLM API + Local EYD Cache** (`ambil_eyd_cache`), serta inferensi sentimen SVM secara otomatis.

### 4. Tab 3: Review Data & Kontrol Kualitas

- Menampilkan tabel data live 13 kolom lengkap (`ID Platform`, `Username`, `Tanggal Pembuatan`, `Teks Mentah`, `Teks Baku (EYD)`, `Label Sentimen`, `Skor Keyakinan`, `Platform`, `Likes`, `Retweets`, `Tayangan`, `Log Aktivitas Scraping`, `User Aplikasi`).
- Edit label sentimen manual atau pemulihan data cadangan database.
- Tombol **🔄 Segarkan** untuk memuat ulang data live dari database secara real-time.

### 5. Tab 4: Visualisasi & Analisis Dashboard Eksekutif

- **Filter Parameter & Periode**: Pemilihan target analisis dari riwayat kata kunci, tagar, profil, atau bookmark topik.
- **Metrik Utama & Distribusi Platform**: Menampilkan Total Volume Data, Akun Unik, Persentase Sentimen (Positif, Negatif, Netral), serta breakdown persentase platform (Twitter, Instagram, LinkedIn, Website/Portal Berita).
- **Grafik Interaktif**: Tren Sentimen Publik Harian, Komposisi Sentimen (Diagram Donat), dan Bar Chart Top 10 Kata Kunci.
- **Ringkasan Eksekutif Narasi AI (NLG)**:
  - Klik **🔄 Perbarui Analisis Narasi (AI)** untuk menyusun laporan analisis kebijakan 250+ kata (minimal 100 data CLEANED).
  - Sistem mendukung generasi hingga **3 model/versi narasi interaktif**. Pengguna dapat memilih versi terbaik (`Versi 1`, `Versi 2`, atau `Versi 3`) melalui kontrol radio button untuk ditampilkan di dashboard.
  - Notifikasi proteksi jika kuota API LLM habis (HTTP 429).
- **Cetak Laporan PDF Eksekutif**: Membentuk dokumen PDF resmi berformat A4 yang mengompilasi grafik visualisasi dan versi narasi eksekutif AI pilihan pengguna.

---

## 6. Batasan Penggunaan

1. **Batasan Kuota API & Rate Limit**:

   - **Apify API**: Penarikan data bergantung pada saldo/kredit akun Apify. Jika kredit habis, API akan mengembalikan respons `HTTP 402 Payment Required`.
   - **LLM API**: Pembersihan teks dan generasi NLG tunduk pada limit token dan *Rate Limit* (HTTP 429). Jika kuota habis, sistem menampilkan notifikasi informatif dan pengarahan kontak institusi (*Prof. Tuti Rachmawati, PhD - Universitas Parahyangan*) serta menonaktifkan sementara tombol generasi AI secara aman.
2. **Pembatasan Generasi Narasi AI (Maksimal 3 Versi)**:

   - Modul pembuat Ringkasan Eksekutif membatasi regenerasi narasi hingga **maksimal 3 versi** per sesi perbaruan untuk menghemat token API LLM.
3. **Pengikat Lisensi Perangkat (Hardware Fingerprint)**:

   - Peluncuran aplikasi desktop (`desktop_launcher.py`) memeriksa ketersediaan lisensi lokal (`app_license.lic`) yang terikat dengan WMI Computer System Product UUID perangkat. Aplikasi tidak dapat dipindahkan antar komputer tanpa registrasi ulang lisensi. (Catatan: Untuk eksekusi pada server Linux via Streamlit `app.py`, verifikasi lisensi WMI desktop ini dapat dilewati secara otomatis).
4. **Spesifikasi Bahasa**:

   - Model klasifikasi SVM dan instruksi pembersihan LLM dioptimalkan khusus untuk **Bahasa Indonesia (EYD)**. Penggunaan pada teks berbahasa asing dapat menurunkan tingkat akurasi klasifikasi.
5. **Ambang Jumlah Data Minimum untuk NLG AI**:

   - Modul pembuat Ringkasan Eksekutif (`nlg_generator.py`) mensyaratkan **minimal 100 baris data `CLEANED`** yang lolos filter agar narasi analisis kebijakan yang dihasilkan valid secara statistik dan tidak mengalami *halusinasi*.
6. **Dinamika Struktur Platform Sumber**:

   - Proses scraping bergantung pada kestabilan Aktor Apify dan struktur halaman target. Perubahan besar pada API atau layout antarmuka platform (Twitter, Instagram, LinkedIn, Portal Berita) dapat mempengaruhi kelancaran penarikan data.
7. **Pemberitahuan Keamanan Windows (Smart App Control / SmartScreen)**:

   - File executable (`SocMedSentimentAnalysis.exe`) yang dibentuk via PyInstaller/PyArmor bersifat *unsigned* (belum memiliki sertifikat digital komersial *Code Signing*). Di Windows 11, fitur **Smart App Control** dapat memblokir eksekusi aplikasi secara otomatis. Pengguna dapat membuka blokir melalui `Properties` ➔ centang `Unblock`, atau menjalankan aplikasi via skrip `python desktop_launcher.py`(unstable).

---

## Lisensi & Kontribusi

Proyek ini dikembangkan untuk tujuan riset akademis dan perumusan kebijakan publik oleh **Universitas Parahyangan bersama Prof. Tuti**.

Perangkat lunak ini dilindungi di bawah **[PolyForm Noncommercial License 1.0.0 &amp; Patent Reservation Notice](file:///d:/Documents/%23ptincap/socmed-sentimen-analysis-pp/LICENSE)**:

- 🚫 **Dilarang untuk Tujuan Komersial**: Hanya diizinkan untuk riset nirlaba, akademis, dan analisis kebijakan publik.
- 🛡️ **Perlindungan Hak Paten**: Seluruh hak paten, invensi, arsitektur sistem, dan metodologi analitis tetap dimiliki secara eksklusif oleh pemegang hak cipta.

Detail ketentuan hukum lengkap dapat dilihat pada file [LICENSE](file:///d:/Documents/%23ptincap/socmed-sentimen-analysis-pp/LICENSE).
