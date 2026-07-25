# Walkthrough: Sistem Analisis Sentimen Kebijakan Publik Berbasis AI

Selamat! Seluruh tahapan migrasi dan deployment awan untuk proyek **Analisis Sentimen Kebijakan Publik Berbasis AI** telah berhasil dilaksanakan. Sistem kini telah aktif sepenuhnya secara mandiri (*autonomous*).

Dokumen ini berfungsi sebagai ringkasan arsitektur sistem, berkas utama, serta panduan pengujian penerimaan pengguna (*User Acceptance Testing* - UAT) untuk memverifikasi fungsionalitas akhir sistem Anda.

---

## 🏛️ Arsitektur & Alur Kerja Data

Berikut adalah visualisasi bagaimana data mengalir secara otomatis antara platform digital, database awan Supabase, kecerdasan buatan Gemini, model SVM lokal, dan dasbor interaktif Streamlit Cloud.

```mermaid
graph TD
    classDef Ingestion fill:#E8F1F5,stroke:#4682B4,stroke-width:2px,color:#212529;
    classDef Processor fill:#FFF3CD,stroke:#FFC107,stroke-width:2px,color:#212529;
    classDef Storage fill:#D1E7DD,stroke:#198754,stroke-width:2px,color:#212529;
    classDef Output fill:#F8D7DA,stroke:#DC3545,stroke-width:2px,color:#212529;
    classDef UI fill:#E2D9F3,stroke:#673AB7,stroke-width:2px,color:#212529;

    subgraph Blok_D ["Pusat Kendali & Visualisasi (Streamlit Cloud)"]
        U1((Analis / Pengguna)) -->|1. Set Parameter Target| D1[app.py\nStreamlit Dashboard]
        D1 -->|2. Simpan Target| A1[target_config.json]
        D1 <-->|NLG Narasi Otomatis| D2[Google Gemini API]
        D1 -->|Visualisasi Data| D3[Tren Sentimen, Audit & Pengaturan]
    end
    class U1,D1 UI;
    class D2,D3 Output;

    subgraph Blok_A ["Penarikan Data & Penjadwalan (GitHub Actions & Apify)"]
        A1 -->|3. Baca Parameter| A2[01_run_scraper.py\nOrkestrator Scraper]
        A2 -->|4. Trigger API| A3[Apify Python SDK]
        A3 -->|5. Eksekusi Scraper| A4((Apify Cloud Actors))
        A4 -->|6. JSON Mentah| A5[Dataset Tweet Mentah]
    end
    class A1,A2,A3,A4,A5 Ingestion;

    subgraph Blok_B ["Otomatisasi AI & Machine Learning"]
        A5 -->|7. Pipa Data Utama| B1[01_pipeline_data.py]
        B1 <-->|8. Standardisasi EYD| B2_AI[Google Gemini API]
        B1 <-->|9. Prediksi Sentimen| B3[Model ML Lokal\nsvm_model.pkl]
    end
    class B1,B2_AI,B3 Processor;

    subgraph Blok_C ["Penyimpanan Cloud (Supabase)"]
        B1 -->|10. SQL UPSERT| C1[(PostgreSQL Supabase)]
        C1 -->|Kueri Data Terkini| D1
    end
    class C1 Storage;
```

---

## 🗂️ Berkas Utama Proyek

*   **Antarmuka Visual**: [app.py](file:///d:/GitHub/socmed-sentimen-analysis-pp/app.py) & [nlg_generator.py](file:///d:/GitHub/socmed-sentimen-analysis-pp/nlg_generator.py)
*   **Logika Database**: [db_manager.py](file:///d:/GitHub/socmed-sentimen-analysis-pp/db_manager.py)
*   **Orkestrator Scraper**: [01_run_scraper.py](file:///d:/GitHub/socmed-sentimen-analysis-pp/01_run_scraper.py) & [config_parser.py](file:///d:/GitHub/socmed-sentimen-analysis-pp/config_parser.py)
*   **Pipa AI & Klasifikasi**: [01_pipeline_data.py](file:///d:/GitHub/socmed-sentimen-analysis-pp/01_pipeline_data.py) & [models/svm_model.pkl](file:///d:/GitHub/socmed-sentimen-analysis-pp/models/svm_model.pkl)
*   **Alur Kerja Awan**: [.github/workflows/daily_pipeline.yml](file:///d:/GitHub/socmed-sentimen-analysis-pp/.github/workflows/daily_pipeline.yml)

---

## 🛠️ Langkah Pengujian Akhir (User Acceptance Testing - UAT)

Guna memastikan seluruh sistem terhubung tanpa hambatan, silakan lakukan tiga langkah pengujian berikut:

### Langkah 1: Pengujian Antarmuka Streamlit Cloud
1.  Buka URL aplikasi Streamlit Cloud Anda yang sudah dideploy.
2.  Pergi ke tab **⚙️ Pengaturan Target** di paling kiri.
3.  Ubah kata kunci pencarian (misal tambahkan kata kunci kebijakan baru yang sedang tren) lalu klik **Simpan Konfigurasi Target**.
4.  Pastikan parameter berhasil tersimpan ke berkas konfigurasi.

### Langkah 2: Pengujian Pemicu Manual GitHub Actions
1.  Buka repositori GitHub proyek Anda di browser.
2.  Masuk ke tab **Actions** di menu atas.
3.  Pilih workflow **"Daily Data Scraping & AI Sentiment Pipeline"** di sebelah kiri.
4.  Klik tombol dropdown **Run workflow** -> pilih cabang `main` -> klik tombol hijau **Run workflow**.
5.  Tunggu sekitar 1–2 menit hingga seluruh indikator berwarna hijau (sukses).
6.  Klik pada riwayat eksekusi tersebut untuk melihat log detail dari modul penarikan data Apify dan standardisasi AI/ML.

### Langkah 3: Verifikasi Sinkronisasi Data
1.  Kembali ke dasbor Streamlit Cloud Anda.
2.  Masuk ke tab **📊 Analitik Sentimen** lalu klik tombol **🔄 Perbarui Analisis Narasi**.
3.  Pastikan ringkasan eksekutif berbasis bahasa alami (NLG) berhasil dirender oleh Gemini API dengan mengambil data kueri terbaru.
4.  Masuk ke tab **📑 Jejak Audit Data** untuk memverifikasi baris tweet baru telah tersimpan berdampingan antara *Teks Mentah* dari media sosial dengan *Teks Baku (EYD)* hasil olahan AI.
5.  *Optional*: Klik tombol **🌐 Buka Tabel Supabase** di sidebar dasbor untuk memastikan baris baru berhasil ditulis ke server PostgreSQL secara langsung.

---

> [!NOTE]
> Sistem saat ini dikonfigurasi dalam mode otomatis harian. Jika Anda ingin menonaktifkan cronjob otomatis GitHub Actions agar tidak memakan sisa batas gratis API Apify/Gemini secara berkala, Anda dapat mengubah **Mode Penarikan Data (Scraping)** di sidebar dasbor menjadi **Manual (Hanya via Dasbor)**.
