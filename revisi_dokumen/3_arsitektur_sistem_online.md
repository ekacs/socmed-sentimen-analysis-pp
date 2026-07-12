# Arsitektur Sistem Online (Cloud / Production)
**Proyek:** Analisis Sentimen Kebijakan Publik Berbasis Kecerdasan Buatan (AI)

---

## 1. Tinjauan Sistem (*System Overview*)
Arsitektur online memindahkan beban komputasi lokal (mulai dari automasi penarikan data hingga penyajian dasbor) ke infrastruktur komputasi awan (*Cloud*). Migrasi ini memungkinkan sistem beroperasi secara otonom tanpa bergantung pada mesin lokal pengembang. 

Dasbor analitik sentimen kini dapat diakses secara publik dan aman oleh pemangku kebijakan kapan saja dan di mana saja melalui URL statis publik, dengan pembaruan data secara berkala dan otomatis setiap hari.

---

## 2. Tumpukan Teknologi Online (*Tech Stack*)
Untuk mendukung skalabilitas tinggi dengan biaya operasional mendekati nol (*zero-cost infrastructure*), sistem menggunakan ekosistem awan terdistribusi berikut:

| Komponen | Layanan Cloud | Peran & Alasan Pemilihan |
| :--- | :--- | :--- |
| **Otomatisasi Aliran Kerja** | GitHub Actions | Orkestrator otomatis untuk menjalankan skrip prapemrosesan data secara harian (*cron job*) secara gratis. |
| **Basis Data Cloud** | Supabase (PostgreSQL) | Layanan basis data relasional berbasis PostgreSQL di awan yang stabil, berkinerja tinggi, dan menyediakan tingkat gratis (*Free Tier*). |
| **Penyimpanan Objek Model** | GitHub Repository | Menyimpan file model terlatih (`.pkl`) dalam repositori pribadi/publik untuk diakses langsung oleh pustaka Python selama proses penarikan data. |
| **Prapemrosesan AI & NLG** | Google Gemini API | Server-side API untuk pembersihan teks bahasa dan pembuatan narasi deskriptif pada dasbor. |
| **Hosting Aplikasi / Dasbor** | Streamlit Community Cloud | Layanan hosting gratis khusus untuk aplikasi Streamlit, menyediakan URL publik statis dengan integrasi langsung ke repositori GitHub. |

---

## 3. Topologi & Alur Data Cloud (*Data Flow*)
Sistem mengadopsi arsitektur terdistribusi yang memisahkan proses penulisan data otomatis (*Data Ingestion*) dan proses pembacaan data interaktif (*Data Visualization*).

```
[Infrastruktur Otomatisasi (GitHub Actions)]
                 │
                 ▼ (Trigger Harian - 00:00)
       ┌──────────────────┐
       │   Scraping Data  │
       └─────────┬────────┘
                 │
                 ▼
       ┌──────────────────┐
       │ AI Pre-processing│ <───> Google Gemini API
       └─────────┬────────┘
                 │
                 ▼
       ┌──────────────────┐
       │  Model Inference │ <───> Muat Model (.pkl) dari GitHub
       └─────────┬────────┘
                 │ (Upsert via psycopg2)
                 ▼
       ┌──────────────────┐
       │ Supabase Cloud DB│
       └─────────┬────────┘
                 │
                 ▼ (Query Teroptimasi & Cache)
[Infrastruktur Visualisasi (Streamlit Community Cloud)]
```

### Blok A: Otomatisasi Data (*Data Automation - GitHub Actions*)
Sistem berjalan tanpa pelayan (*serverless*) secara terjadwal di latar belakang:

1. **Pemicu Cron Job:** GitHub Actions mendeteksi jadwal waktu yang ditentukan (misalnya setiap tengah malam pukul 00:00 UTC) dan mengalokasikan container virtual untuk menjalankan skrip `01_pipeline_data.py`.
2. **Prapemrosesan & Klasifikasi:** Skrip menarik data cuitan baru, mengirimkan teks ke Gemini API untuk standardisasi ke EYD, memuat file model klasifikasi `.pkl` dari repositori, dan memprediksi kelas sentimen.
3. **Sinkronisasi Cloud Database:** Hasil prediksi didorong langsung menggunakan koneksi URI terenkripsi menuju basis data Supabase (PostgreSQL) di cloud melalui pustaka `psycopg2` atau `SQLAlchemy`.

### Blok B: Visualisasi Publik (*Visualisasi - Streamlit Cloud*)
Dasbor Streamlit di-host pada Streamlit Community Cloud dan terhubung ke Supabase secara langsung:

1. **Akses URL Statis:** Pengguna mengakses dasbor melalui tautan web statis (misal: `https://sentimen-kebijakan.streamlit.app`).
2. **Pengambilan Data Cepat (*Live Retrieval*):** Streamlit melakukan koneksi kueri ke Supabase PostgreSQL. Untuk menghemat kuota dan meminimalkan latensi, kueri dioptimalkan menggunakan fungsi dekorator `@st.cache_resource` atau `@st.cache_data`.
3. **Penyajian Laporan:** Menampilkan visualisasi analitik interaktif teranyar, lengkap dengan Ringkasan Eksekutif dinamis hasil narasi otomatis Gemini API.

---

## 4. Keamanan & Mitigasi Risiko Cloud
* **Manajemen Rahasia (*Secrets Management*):** Seluruh kunci API penting (Gemini API Key, Twitter API Key) dan kredensial koneksi basis data Supabase tidak boleh diunggah ke repositori GitHub. Kredensial tersebut wajib dikonfigurasi melalui fitur **GitHub Repository Secrets** (untuk proses penarikan data) dan **Streamlit Secrets** (untuk dasbor).
* **Connection Pooling:** Koneksi ke Supabase wajib menggunakan metode pengelompokan koneksi (*Connection Pooling*) atau penanganan pengecualian menggunakan pustaka koneksi PostgreSQL untuk mencegah kegagalan akses (*database timeout*) akibat lonjakan trafik pengunjung dasbor secara bersamaan.
