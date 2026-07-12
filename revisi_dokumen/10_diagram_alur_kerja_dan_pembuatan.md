# Diagram Alur Kerja & Peta Jalan Pembuatan Sistem
**Proyek:** Analisis Sentimen Kebijakan Publik Berbasis Kecerdasan Bahtan (AI)

Dokumen ini menyediakan diagram visual menggunakan sintaksis **Mermaid** untuk memudahkan Anda mempresentasikan cara kerja sistem dan proses pembuatannya kepada publik atau pemangku kebijakan. Anda dapat langsung menyalin kode Mermaid di bawah ini ke dalam slide presentasi (seperti Notion, GitHub, Canva, atau PowerPoint yang mendukung Mermaid).

---

## 1. Diagram Alur Kerja Pipa Data (*Data Pipeline*)
Diagram ini menjelaskan bagaimana data mengalir dari platform media sosial hingga disajikan secara interaktif dalam bentuk narasi laporan analitik di dasbor Streamlit.

```mermaid
graph TD
    %% Styling Global
    classDef Ingestion fill:#E8F1F5,stroke:#4682B4,stroke-width:2px,color:#212529;
    classDef Processor fill:#FFF3CD,stroke:#FFC107,stroke-width:2px,color:#212529;
    classDef Storage fill:#D1E7DD,stroke:#198754,stroke-width:2px,color:#212529;
    classDef Output fill:#F8D7DA,stroke:#DC3545,stroke-width:2px,color:#212529;

    %% Blok A: Data Ingestion (Penarikan Data)
    subgraph Blok_A ["Blok A: Penarikan Data - Scraping"]
        A1[target_config.json<br/>Konfigurasi Dinamis] -->|1. Baca Parameter| A2[config_parser.py<br/>Penyusun Kueri]
        A2 -->|2. Kirim Kueri Lanjutan| A3[Apify Python SDK<br/>Konektor Cloud]
        A3 -->|3. Delegasikan Tugas| A4((Apify Cloud Actor<br/>Twitter Scraper))
        A4 -->|4. Rotasi Proxy & Ekstraksi| A5[Dataset JSON Mentah]
    end
    class A1,A2,A3,A4,A5 Ingestion;

    %% Blok B: Prapemrosesan AI & Prediksi ML
    subgraph Blok_B ["Blok B: Otomatisasi AI & Machine Learning"]
        A5 -->|5. Ekstraksi Iteratif| B1[01_pipeline_data.py<br/>Pipa Data Utama]
        B1 <-->|6. Standardisasi Bahasa<br/>ke EYD Baku| B2[Google Gemini API]
        B1 <-->|7. Prediksi Kelas Sentimen<br/>Positif/Netral/Negatif| B3[Model ML Lokal<br/>svm_model.pkl]
    end
    class B1,B2,B3 Processor;

    %% Blok C: Penyimpanan Data Terstruktur
    subgraph Blok_C ["Blok C: Penyimpanan & Jejak Audit"]
        B1 -->|8. SQL UPSERT<br/>INSERT OR IGNORE| C1[(Basis Data<br/>SQLite / Supabase)]
    end
    class C1 Storage;

    %% Blok D: Visualisasi & Narasi Eksekutif
    subgraph Blok_D ["Blok D: Presentasi & Visualisasi Eksekutif"]
        C1 -->|9. Query Pengambilan Data| D1[app.py<br/>Streamlit Frontend]
        D1 <-->|10. Data-to-Text NLG<br/>Generate Narasi Laporan| D2[Google Gemini API]
        D1 -->|11. Tampilan Visual Premium| D3[Dasbor Publik<br/>Tren & Jejak Audit]
    end
    class D1,D2,D3 Output;
```

### Penjelasan Langkah Alur Data untuk Presentasi:
1. **Fase Ingestion:** Pengguna menentukan topik kebijakan yang ingin dianalisis di berkas konfigurasi lokal. Sistem secara otomatis menyusun kueri pencarian Twitter yang rumit dan mengirimkannya ke platform awan Apify untuk melakukan penarikan data secara aman tanpa terkena blokir IP.
2. **Fase Pemrosesan AI & ML:** Data mentah hasil ekstraksi dibersihkan bahasanya dari bahasa gaul/singkatan menjadi bahasa Indonesia baku (EYD) menggunakan kecerdasan buatan Gemini, lalu langsung diklasifikasikan sentimennya menggunakan model *Machine Learning* SVM (*Support Vector Machine*) yang telah dilatih secara khusus.
3. **Fase Penyimpanan:** Hasil analisis disimpan ke dalam basis data terpusat menggunakan mekanisme *Upsert* untuk menjamin data mentah asli dan data hasil pembersihan tersimpan berdampingan sebagai jejak audit yang transparan dan bebas duplikasi.
4. **Fase Visualisasi:** Dasbor Streamlit menarik data secara cepat dari database, mengirimkan statistik ringkas ke Gemini untuk dibuatkan narasi laporan birokrasi otomatis (NLG), dan menyajikannya dalam grafik tren interaktif kepada pemangku kebijakan.

---

## 2. Diagram Peta Jalan Pembuatan (*Walkthrough Alur Pembuatan*)
Diagram ini menyajikan lini masa pengembangan sistem yang dibagi menjadi dua fase strategis: dari pembuktian konsep lokal (MVP) hingga peluncuran otomatisasi penuh di awan (Production).

```mermaid
graph LR
    %% Styling Global
    classDef Lokal fill:#E2E2E2,stroke:#666666,stroke-width:2px,color:#333333;
    classDef Cloud fill:#CCE5FF,stroke:#004085,stroke-width:2px,color:#004085;
    classDef Sukses fill:#D4EDDA,stroke:#155724,stroke-width:2px,color:#155724;

    %% FASE 1: LOKAL MVP
    subgraph Fase_1 ["FASE 1: LOKAL MVP (Pembuktian Konsep)"]
        L1[1. Setup Env & Repositori] --> L2[2. Inisialisasi Database SQLite]
        L2 --> L3[3. Pipa Data Scraping & AI]
        L3 --> L4[4. Pelatihan Model SVM]
        L4 --> L5[5. Integrasi Dashboard Streamlit]
    end
    class L1,L2,L3,L4,L5 Lokal;

    %% JALUR MIGRASI
    L5 -->|Uji Coba Lokal Sukses| M1{Migrasi Sistem}

    %% FASE 2: CLOUD PRODUCTION
    subgraph Fase_2 ["FASE 2: CLOUD PRODUCTION (Otomatisasi Publik)"]
        C1[1. Migrasi DB ke Supabase PostgreSQL] --> C2[2. Unggah Repositori ke GitHub]
        C2 --> C3[3. Konfigurasi GitHub Actions Scheduler]
        C3 --> C4[4. Deploy Dashboard ke Streamlit Cloud]
        C4 --> C5[5. Evaluasi & Serah Terima UAT]
    end
    class C1,C2,C3,C4,C5 Cloud;

    M1 -->|Awan / Cloud| C1
    C5 --> S1((SISTEM AKTIF DAN AUTONOMOUS))
    class S1 Sukses;
```

### Narasi Walkthrough Pembuatan untuk Presentasi:
* **Fase 1 (Lokal MVP):** Kami membangun fondasi sistem di komputer lokal terlebih dahulu untuk meminimalkan biaya riset. Di sini, kami melatih model Machine Learning kami menggunakan dataset kecil, menyusun database relasional yang ringan (SQLite), dan memastikan dasbor Streamlit mampu memvisualisasikan data lokal dengan lancar.
* **Fase 2 (Cloud Production):** Setelah fungsionalitas sistem terbukti sempurna secara lokal, kami melakukan migrasi skala penuh ke ekosistem awan. Kami memindahkan penyimpanan data ke server Supabase PostgreSQL agar aman, mengonfigurasi jadwal penarikan data harian otomatis tanpa pelayan (*serverless*) lewat GitHub Actions, dan mempublikasikan dasbor Streamlit ke internet secara gratis menggunakan Streamlit Community Cloud agar dapat diakses kapan saja oleh pemangku kepentingan.
