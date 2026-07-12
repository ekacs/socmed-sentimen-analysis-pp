# Peta Jalan Modul Scraping (Apify SDK Integration)
**Proyek:** Analisis Sentimen Kebijakan Publik Berbasis Kecerdasan Buatan (AI)

---

## Pernyataan Target
Dokumen ini merupakan Prosedur Operasional Standar (SOP) dan peta jalan langkah-demi-langkah pengembangan untuk mengimplementasikan modul penarikan data (*Data Ingestion*) menggunakan Apify Python SDK. Modul ini dirancang untuk membaca konfigurasi dinamis secara berkala dan menghasilkan keluaran data terstruktur yang siap diolah oleh model AI.

---

## Fase 1: Persiapan Lingkungan Dasar
Fokus utama fase ini adalah memastikan seluruh infrastruktur isolasi kode dan dependensi pustaka yang tepat terpasang dengan baik.

1. **Aktivasi Virtual Environment:**
   Pastikan Anda berada di direktori proyek dan telah mengaktifkan lingkungan virtual:
   ```bash
   # Windows
   .\env\Scripts\activate
   # Linux/MacOS
   source env/bin/activate
   ```
2. **Instalasi Apify Python SDK:**
   Jalankan perintah instalasi melalui terminal:
   ```bash
   pip install apify-client
   ```
3. **Manajemen Kredensial Pengembang:**
   * Daftar atau masuk ke [Apify Console](https://console.apify.com).
   * Masuk ke menu *Settings > Integrations* dan salin **API Token** pribadi Anda.
   * Simpan token ini ke dalam file `.env` lokal Anda:
     ```env
     APIFY_API_TOKEN=MASUKKAN_TOKEN_APIFY_ANDA
     ```

---

## Fase 2: Konfigurasi Input Dinamis
Membangun sistem modular yang memungkinkan pengguna untuk menentukan target kata kunci pencarian, tagar, atau akun spesifik tanpa perlu menyentuh atau memodifikasi berkas kode program utama.

1. **Pembuatan Berkas Konfigurasi:**
   Buat berkas bernama `target_config.json` di direktori utama proyek Anda.
2. **Pengisian Struktur Default:**
   Tentukan parameter pencarian seperti contoh di bawah ini:
   ```json
   {
     "keywords": ["Ibu Kota Baru", "IKN"],
     "hashtags": ["#IKNNusantara"],
     "usernames": ["jokowi"],
     "max_tweets": 100,
     "language": "id"
   }
   ```
3. **Pembuatan Pengurai Kueri (*Query Builder*):**
   * Buat berkas Python bernama `config_parser.py`.
   * Tulis fungsi `load_config()` untuk membaca isi berkas `target_config.json`.
   * Tulis fungsi `build_twitter_query()` untuk merangkai nilai-nilai dari konfigurasi menjadi format pencarian tingkat lanjut Twitter yang sah. Contoh: menggabungkan kata kunci dengan kata kunci lainnya menggunakan operator `OR`, dan format pencarian spesifik akun menggunakan operator `from:`.

---

## Fase 3: Implementasi Basis Data (SQLite Sink)
Fase ini berfokus pada pembangunan landasan penyimpanan data terstruktur yang efisien untuk menerima data hasil ekstraksi dari platform Apify serta menjamin jejak audit data (*audit trail*).

1. **Pembuatan Modul Basis Data:**
   Buat berkas Python bernama `db_manager.py`.
2. **Inisialisasi Skema Tabel:**
   * Di dalam berkas `db_manager.py`, buat fungsi untuk membuat koneksi ke berkas basis data SQLite: `sqlite3.connect('raw_data.db')`.
   * Tulis kueri `CREATE TABLE IF NOT EXISTS raw_tweets` dengan kolom-kolom: `tweet_id` (sebagai PRIMARY KEY), `date`, `raw_text`, `username`, `likes`, `retweets`, dan `status`.
3. **Pembuatan Fungsi Penyisipan Tangguh (*Upsert Function*):**
   * Tulis fungsi `insert_tweets(data_list)` untuk memasukkan data hasil scraping ke basis data.
   * Gunakan sintaks SQL pelindung duplikasi untuk mengabaikan data yang sudah pernah diimpor sebelumnya:
     ```sql
     INSERT OR IGNORE INTO raw_tweets (tweet_id, date, raw_text, username, likes, retweets, status) 
     VALUES (?, ?, ?, ?, ?, ?, ?);
     ```

---

## Fase 4: Integrasi ApifyClient (The Scraper Engine)
Menghubungkan komponen masukan dinamis, mesin penarik data cloud Apify, dan sistem basis data ke dalam satu kesatuan alur kerja yang terintegrasi.

1. **Pembuatan Skrip Utama:**
   Buat berkas Python bernama `01_run_scraper.py`.
2. **Inisialisasi Klien Apify:**
   * Impor dependensi modul: `from apify_client import ApifyClient`.
   * Muat token dari sistem variabel lingkungan menggunakan pustaka `os` atau `dotenv` untuk memulai instans: `client = ApifyClient(os.getenv("APIFY_API_TOKEN"))`.
3. **Pemicu Pemanggilan Actor (*Actor Invocation*):**
   * Panggil fungsi `build_twitter_query()` dari berkas `config_parser.py` untuk mendapatkan string kueri dinamis.
   * Eksekusi pemanggilan Actor Twitter Scraper (misal: `apidojo/tweet-scraper`) dengan melewatkan parameter string kueri dan batas maksimum penarikan data (`max_tweets`):
     ```python
     run_input = {
         "searchTerms": [query_string],
         "maxTweets": max_tweets
     }
     run = client.actor("apidojo/tweet-scraper").call(run_input=run_input)
     ```
4. **Penarikan Dataset Hasil:**
   * Ambil ID Dataset yang dihasilkan oleh Actor: `dataset_id = run["defaultDatasetId"]`.
   * Iterasi data secara efisien menggunakan metode iterator bawaan SDK:
     ```python
     for item in client.dataset(dataset_id).iterate_items():
         # Proses ekstraksi dan pemetaan data mentah ke skema tabel
     ```

---

## Fase 5: Penggabungan & Pengujian Akhir (*E2E Testing*)
Memastikan seluruh komponen dari fase 1 hingga fase 4 terhubung dengan sempurna dan siap dioperasikan dalam lingkungan produksi.

1. **Integrasi Alur Kerja (*Workflow Integration*):**
   Perbarui berkas `01_run_scraper.py` agar menyalurkan setiap objek data hasil perulangan dari iterator dataset Apify langsung sebagai masukan ke fungsi `insert_tweets(data_list)` pada modul `db_manager.py`.
2. **Eksekusi Pengujian Pertama:**
   Jalankan pengujian penuh melalui terminal:
   ```bash
   python 01_run_scraper.py
   ```
   Pantau keluaran terminal untuk memastikan tidak ada kesalahan pemanggilan API dan pantau kemajuan penarikan data.
3. **Verifikasi Integritas Data (*Quality Check*):**
   * Gunakan aplikasi pihak ketiga seperti *DB Browser for SQLite* untuk membuka berkas basis data `raw_data.db`.
   * Verifikasi bahwa seluruh kolom data terisi dengan nilai yang benar, karakter khusus di dalam teks cuitan tetap utuh, dan jumlah baris data sesuai dengan jumlah yang ditarik.
4. **Validasi Mekanisme Deduplikasi:**
   * Jalankan kembali skrip eksekusi `python 01_run_scraper.py` untuk kedua kalinya tanpa mengubah nilai konfigurasi pada berkas `target_config.json`.
   * Pastikan sistem tidak menampilkan pesan galat (*database error*) akibat pelanggaran *primary key*, melainkan mengonfirmasi bahwa 0 baris baru yang ditambahkan karena seluruh data telah terdeteksi sebagai duplikat dan diabaikan secara aman.
