# Peta Jalan Penyebaran Cloud (Cloud Deployment Phase)
**Proyek:** Analisis Sentimen Kebijakan Publik Berbasis Kecerdasan Buatan (AI)

---

## Pernyataan Target
Fase penyebaran awan (*Cloud Deployment*) ini dilakukan segera setelah sistem lokal berjalan dengan stabil. Langkah-langkah di bawah ini diatur secara berurutan untuk menjamin kelancaran migrasi penyimpanan data dari SQLite lokal ke PostgreSQL di awan, konfigurasi otomatisasi aliran kerja, hingga peluncuran dasbor publik.

---

## Langkah 1: Migrasi Basis Data ke Cloud (Supabase)
Memindahkan infrastruktur penyimpanan data dari berkas lokal tunggal ke basis data relasional tingkat produksi yang aman di awan.

1. **Pembuatan Akun & Proyek:**
   * Daftar akun secara gratis di [Supabase.com](https://supabase.com).
   * Buat proyek baru dan catat kredensial koneksi penting seperti Host, Database Name, Port, User, Password, serta format lengkap **URI Koneksi PostgreSQL**.
2. **Pembuatan Skema Tabel di Supabase:**
   * Masuk ke menu *SQL Editor* di dasbor Supabase.
   * Eksekusi perintah `CREATE TABLE` yang identik dengan struktur skema tabel lokal (`log_cuitan`) untuk memastikan keselarasan tipe data.
3. **Pembaruan Dependensi Skrip:**
   * Instal pustaka Python pendukung PostgreSQL di lingkungan lokal pengembang:
     ```bash
     pip install psycopg2-binary SQLAlchemy
     ```
4. **Modifikasi Kode Penyisipan (*Ingestion Code*):**
   * Perbarui fungsi penyimpanan data di berkas `01_pipeline_data.py`. Ubah koneksi dari berkas lokal `database_sentimen.db` ke URI koneksi PostgreSQL Supabase Anda. Gunakan metode `df.to_sql(..., if_exists='append')` untuk menyisipkan baris data baru ke cloud database.

---

## Langkah 2: Migrasi Kode & Repositori ke GitHub
Menata dan mengamankan repositori kode di awan agar siap diproses oleh orkestrator otomatisasi dan layanan hosting.

1. **Inisialisasi Repositori Git:**
   * Buat repositori baru (disarankan bersifat Pribadi/*Private*) di GitHub.
2. **Penyusunan Berkas Pengabaian (.gitignore):**
   * Pastikan direktori `env/`, berkas `.env`, berkas basis data SQLite lokal `.db`, dan folder cache python `__pycache__/` telah terdaftar di dalam berkas `.gitignore` untuk mencegah kebocoran kredensial dan file sampah.
3. **Penyusunan Daftar Dependensi (requirements.txt):**
   * Generate daftar paket pustaka yang digunakan oleh proyek agar dapat diinstal otomatis di server cloud:
     ```bash
     pip freeze > requirements.txt
     ```
4. **Push Kode ke GitHub:**
   * Hubungkan repositori lokal ke GitHub, tambahkan seluruh berkas kode, lakukan commit, dan kirimkan (*push*) ke cabang utama (`main` atau `master`).
   * **PENTING:** Pastikan file model terlatih `/models/svm_model.pkl` ikut terunggah agar dapat dimuat oleh mesin pipeline di cloud.

---

## Langkah 3: Otomatisasi Aliran Kerja Data (GitHub Actions)
Mengatur pemicu otomatis harian untuk mengeksekusi penarikan data, prapemrosesan, dan prediksi sentimen secara otomatis.

1. **Pembuatan Direktori Workflow:**
   * Di dalam proyek Anda, buat folder berstruktur: `.github/workflows/`.
2. **Penyusunan File Konfigurasi CI/CD:**
   * Buat berkas konfigurasi bernama `daily_pipeline.yml`.
   * Konfigurasikan pemicu harian menggunakan sintaks cron schedule (contoh: eksekusi otomatis setiap tengah malam UTC):
     ```yaml
     on:
       schedule:
         - cron: '0 0 * * *'
     ```
   * Atur tahapan eksekusi: inisialisasi lingkungan virtual, instalasi dependensi dari `requirements.txt`, lalu jalankan skrip utama `01_pipeline_data.py`.
3. **Pengaturan Kredensial Rahasia (*Secrets Management*):**
   * Buka menu *Settings > Secrets and variables > Actions* pada repositori GitHub Anda.
   * Masukkan nilai kredensial sensitif dari berkas `.env` Anda sebagai variabel rahasia:
     * `GEMINI_API_KEY`
     * `DATABASE_URL` (URI Koneksi Supabase)
     * `X_API_KEY` (Jika menggunakan scraping via API resmi)

---

## Langkah 4: Publikasi Dasbor Interaktif (Streamlit Cloud)
Meluncurkan dasbor analisis sentimen ke internet agar dapat diakses oleh publik atau pemangku kebijakan secara *real-time*.

1. **Koneksi Akun GitHub & Streamlit:**
   * Masuk ke platform [share.streamlit.io](https://share.streamlit.io) menggunakan akun GitHub Anda.
2. **Penyebaran Aplikasi (*Deployment*):**
   * Klik tombol **"New App"**.
   * Pilih repositori proyek Anda, tentukan cabang (*branch*), lalu arahkan berkas utama ke `app.py`.
3. **Konfigurasi Variabel Rahasia Dasbor:**
   * Sebelum menekan tombol Deploy, buka menu **"Advanced Settings"**.
   * Pada bagian **Secrets** (format TOML), masukkan kredensial koneksi Supabase dan Gemini API Key agar dasbor dapat terhubung ke basis data awan dan memanggil LLM:
     ```toml
     DATABASE_URL = "postgresql://user:password@host:port/dbname"
     GEMINI_API_KEY = "AIzaSy..."
     ```
4. **Peluncuran Aplikasi:**
   * Klik **"Deploy"** dan tunggu hingga proses instalasi server selesai. Dasbor Anda kini aktif dan dapat diakses publik melalui URL unik Streamlit.

---

## Langkah 5: Evaluasi Akhir & Serah Terima (UAT)
Memastikan kualitas fungsionalitas sistem berjalan sempurna tanpa kendala operasional.

1. **Pengujian Lintas Perangkat:**
   * Akses URL publik dasbor menggunakan perangkat seluler (HP/Tablet) dan komputer untuk memastikan visualisasi bersifat responsif.
2. **Validasi Fitur AI (NLG):**
   * Pastikan bagian "Ringkasan Eksekutif" yang digenerate oleh Gemini API muncul dengan narasi analisis data yang akurat dan komunikatif.
3. **Sinkronisasi Data Real-Time:**
   * Jalankan alur kerja GitHub Actions secara manual (*workflow_dispatch*) untuk memastikan data baru berhasil ditambahkan ke Supabase dan langsung memperbarui grafik tren pada dasbor Streamlit tanpa kendala pemutusan koneksi (*database timeout*).
4. **Serah Terima Sistem:**
   * Bagikan URL statis dasbor kepada pemangku kebijakan dan lampirkan repositori GitHub serta dokumentasi ini untuk pemeliharaan sistem jangka panjang.
