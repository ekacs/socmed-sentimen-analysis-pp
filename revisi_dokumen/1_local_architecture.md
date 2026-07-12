# Arsitektur Sistem Lokal (Local MVP)
**Proyek:** Analisis Sentimen Kebijakan Publik Berbasis Kecerdasan Buatan (AI)

---

## 1. Tinjauan Sistem (*System Overview*)
Arsitektur lokal ini dirancang khusus untuk fase pengembangan awal (*Development Phase*). Seluruh siklus pemrosesan data—mulai dari ekstraksi data mentah, pembersihan teks, pelatihan model klasifikasi, hingga visualisasi interaktif—dieksekusi sepenuhnya di dalam mesin pengembang (*local machine*). 

Dengan mengisolasi seluruh proses secara lokal, sistem ini menjamin **kontrol keamanan absolut** atas seluruh data pengujian tanpa ada ketergantungan pada server eksternal, sekaligus meminimalkan latensi jaringan selama proses eksperimen dan pengujian model.

---

## 2. Tumpukan Teknologi Lokal (*Tech Stack*)
Pemilihan tumpukan teknologi didasarkan pada prinsip efisiensi, kemudahan instalasi, serta interoperabilitas antar-pustaka Python modern:

| Komponen | Teknologi | Deskripsi & Peran |
| :--- | :--- | :--- |
| **Environment** | Python 3.10+ | Bahasa pemrograman utama dengan isolasi lingkungan menggunakan `venv` (*Virtual Environment*). |
| **Data Ingestion** | Tweepy (X API) / Script Scraper | Pustaka untuk mengekstrak data percubaan langsung dari platform X (Twitter) secara lokal. |
| **Pembersihan Teks & NLG** | Google Gemini API | Digunakan untuk standardisasi teks gaul/non-baku ke EYD secara *batch* melalui jaringan lokal secara aman. |
| **Database** | SQLite3 | Basis data relasional berbasis berkas tunggal (`.db`) yang ringan dan efisien untuk penyimpanan lokal tanpa memerlukan manajemen server tambahan. |
| **Machine Learning** | Scikit-Learn | Meliputi proses ekstraksi fitur menggunakan *TF-IDF Vectorizer* dan klasifikasi menggunakan algoritma *Support Vector Machine* (SVM). |
| **Frontend / Dashboard** | Streamlit | Kerangka kerja berbasis Python untuk membangun visualisasi analitik interaktif yang diakses lokal melalui `http://localhost:8501`. |

---

## 3. Topologi & Alur Data (*Data Flow*)
Aliran kerja sistem lokal terbagi menjadi dua blok fungsional utama yang saling berkomunikasi secara asinkron melalui perantara berkas basis data SQLite (`database_sentimen.db`).

```
[Blok A: Data Processing (Script Backend)]
                 │
                 ▼ (Ekstraksi)
       ┌──────────────────┐
       │   Scraping Data  │
       └─────────┬────────┘
                 │ (Teks Mentah)
                 ▼
       ┌──────────────────┐
       │ AI Pre-processing│ <───> Google Gemini API
       └─────────┬────────┘
                 │ (Teks Baku)
                 ▼
       ┌──────────────────┐
       │  Model Inference │ <───> Model SVM (.pkl)
       └─────────┬────────┘
                 │ (Label Sentimen)
                 ▼
       ┌──────────────────┐
       │  SQLite Database │
       └─────────┬────────┘
                 │
                 ▼ (Data Retrieval)
[Blok B: Visualisasi (Streamlit Frontend)]
```

### Blok A: Pemrosesan Data (*Data Processing - Script Backend*)
Dijalankan secara manual oleh pengembang melalui terminal perintah: `python process_data.py`.

1. **Scraping (Penarikan Data):** Skrip mengekstrak cuitan dari Twitter berdasarkan parameter pencarian dan menampungnya ke dalam memori menggunakan pustaka Pandas (*DataFrame*).
2. **AI Pre-processing (Prapemrosesan AI):** Skrip mengirimkan teks mentah ke Google Gemini API secara massal (*batch*) untuk dibersihkan dan diterjemahkan ke dalam bahasa baku sesuai Ejaan yang Disempurnakan (EYD).
3. **Inference (Prediksi Sentimen):** Teks baku diumpankan ke model ML lokal yang telah dilatih (`svm_model.pkl`) untuk menentukan klasifikasi sentimen (*Positif*, *Negatif*, atau *Netral*).
4. **Local Storage (Penyimpanan Lokal):** Seluruh hasil akhir (teks mentah, teks bersih, dan label sentimen) disimpan menggunakan operasi `INSERT` ke dalam berkas basis data SQLite (`database_sentimen.db`).

### Blok B: Visualisasi (*Streamlit Frontend*)
Dijalankan melalui terminal menggunakan perintah: `streamlit run app.py`.

1. **Data Retrieval (Pengambilan Data):** Saat dasbor dibuka pada peramban, Streamlit mengeksekusi perintah SQL `SELECT * FROM log_cuitan` pada berkas `database_sentimen.db`.
2. **AI NLG (Penyusunan Ringkasan):** Streamlit menghitung metrik agregat, mengirimkan data statistik tersebut ke Gemini API, dan menerima umpan balik berupa deskripsi naratif untuk bagian "Ringkasan Eksekutif".
3. **Render UI (Penyajian Tampilan):** Menampilkan grafik tren waktu (*Line Chart*), Indikator Kinerja Utama (KPI), serta tabel log jejak audit (*Audit Trail*) secara langsung di lokal.

---

## 4. Keamanan & Mitigasi Risiko Lokal
* **Isolasi Berkas Database:** Berkas SQLite `.db` wajib didaftarkan di dalam `.gitignore` untuk mencegah kebocoran data mentah publik atau internal ke repositori GitHub.
* **Manajemen Variabel Lingkungan:** Kredensial sensitif seperti API Key Twitter dan Google Gemini wajib disimpan di dalam file konfigurasi `.env` lokal dan dilarang keras ditulis langsung (*hardcoded*) di dalam kode program.
