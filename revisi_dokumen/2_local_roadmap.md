# Peta Jalan Pengembangan Lokal (Local Development Phase)
**Proyek:** Analisis Sentimen Kebijakan Publik Berbasis Kecerdasan Buatan (AI)

---

## Pernyataan Target
Fase pengembangan lokal ini ditargetkan selesai dalam rentang waktu **1 hingga 2 minggu**. Fokus utama fase ini adalah memastikan seluruh logika kode, skema basis data, pembersihan teks berbasis LLM, klasifikasi model ML, dan antarmuka dasbor berjalan dengan sempurna secara lokal sebelum bermigrasi ke lingkungan komputasi awan (*Cloud*).

---

## Langkah 1: Persiapan Lingkungan & Repositori
Langkah ini bertujuan untuk memastikan struktur proyek rapi, terisolasi, dan aman dari potensi kebocoran kredensial.

1. **Inisialisasi Direktori Proyek:**
   ```bash
   mkdir sentimen_kebijakan_mvp
   cd sentimen_kebijakan_mvp
   ```
2. **Isolasi Lingkungan Pengembang (Virtual Environment):**
   ```bash
   python -m venv env
   # Mengaktifkan env (Windows)
   .\env\Scripts\activate
   # Mengaktifkan env (Linux/MacOS)
   source env/bin/activate
   ```
3. **Instalasi Paket Dependensi Utama:**
   ```bash
   pip install pandas streamlit scikit-learn google-generativeai plotly python-dotenv
   ```
4. **Penyusunan Keamanan Kredensial:**
   Buat file `.env` di direktori utama dan definisikan variabel berikut tanpa tanda kutip:
   ```env
   GEMINI_API_KEY=MASUKKAN_KUNCI_API_GEMINI_ANDA
   X_API_KEY=MASUKKAN_KUNCI_API_TWITTER_ANDA
   ```

---

## Langkah 2: Pembuatan Fondasi Basis Data (SQLite)
Membangun media penyimpanan lokal yang tangguh untuk menyimpan log cuitan mentah hingga hasil analisis akhir.

1. **Skrip Inisialisasi Database:**
   Buat berkas `database_setup.py` untuk mengotomatiskan pembuatan skema tabel.
2. **Eksekusi Skema Tabel:**
   Jalankan skrip untuk membuat tabel `log_cuitan` dengan struktur kolom yang mendukung jejak audit data (*audit trail*).
3. **Inspeksi Visual:**
   Unduh dan gunakan aplikasi *DB Browser for SQLite* untuk memastikan tabel `log_cuitan` terbentuk dengan kolom-kolom utama seperti `tweet_id` (sebagai PRIMARY KEY), `raw_text`, `cleaned_text`, dan `sentiment_label`.

---

## Langkah 3: Modul Ingestion & Prapemrosesan LLM
Mengimplementasikan alur penarikan data mentah dan standardisasi bahasa tidak baku menggunakan kekuatan Generatif AI.

1. **Pembuatan Pipa Data (*Data Pipeline*):**
   Buat berkas Python bernama `01_pipeline_data.py`.
2. **Fungsi Penarikan Data (*Ingestion*):**
   Implementasikan fungsi penarikan data mentah dari API Twitter atau modul scraper lokal ke dalam struktur Pandas DataFrame.
3. **Pembersihan Bahasa Berbasis AI (LLM Preprocessing):**
   Gunakan SDK `@google/genai` untuk memanggil model Gemini. Rancang instruksi sistem (*System Prompt*) khusus agar model menerjemahkan bahasa gaul, singkatan, dan salah ketik ke dalam format bahasa Indonesia baku (EYD).
4. **Penyimpanan Hasil Prapemrosesan:**
   Tulis kueri SQL `INSERT INTO` untuk menyimpan teks mentah dan teks hasil standardisasi ke dalam basis data SQLite secara efisien.

---

## Langkah 4: Pelatihan Model Klasifikasi ML (Sekali Proses)
Melatih algoritma machine learning lokal agar mampu mengenali pola sentimen secara konsisten.

1. **Persiapan Data Pelatihan (Dataset):**
   Siapkan minimal 200 baris data teks baku berlabel manual menggunakan skala ordinal (0: Negatif, 1: Netral, 2: Positif) menggunakan *DB Browser for SQLite* atau file CSV bantuan.
2. **Skrip Pelatihan Model:**
   Buat berkas `02_train_model.py`.
3. **Ekstraksi Fitur & Pemodelan:**
   * Ekstraksi teks menggunakan metode `TfidfVectorizer` dari Scikit-Learn.
   * Latih model klasifikasi menggunakan algoritma `SVC` (Support Vector Classifier) dengan parameter penyeimbang kelas `class_weight='balanced'`.
4. **Ekspor Model & Serialisasi:**
   Simpan objek model dan vectorizer yang telah dilatih ke dalam direktori khusus menggunakan pustaka `joblib` ke dalam format file `.pkl` (contoh: `/models/svm_model.pkl`).

---

## Langkah 5: Integrasi Model ke dalam Pipa Data
Menggabungkan kemampuan klasifikasi model ML yang telah dilatih ke dalam pipa prapemrosesan data otomatis.

1. **Pembaruan Skrip Pipeline:**
   Buka kembali berkas `01_pipeline_data.py`.
2. **Implementasi Prediksi Otomatis:**
   Tambahkan langkah pasca-pembersihan teks: muat berkas `/models/svm_model.pkl`, jalankan metode `model.predict()`, lalu simpan hasil klasifikasi sentimen langsung ke kolom `sentiment_label` di baris database yang bersangkutan.

---

## Langkah 6: Pembuatan Dasbor Interaktif (Streamlit)
Menyajikan visualisasi data yang intuitif bagi pengguna akhir untuk memantau tren kebijakan publik.

1. **Pembuatan File Aplikasi Utama:**
   Buat berkas `app.py`.
2. **Koneksi Basis Data:**
   Gunakan pustaka `sqlite3` dan metode Pandas `pd.read_sql()` untuk menarik data sentimen terkini secara dinamis.
3. **Integrasi Narasi AI (NLG):**
   Buat fungsi untuk mengirimkan data statistik agregat ke Gemini API untuk menghasilkan ringkasan eksekutif naratif otomatis (*Data-to-Text NLG*).
4. **Desain Antarmuka Dasbor:**
   Rancang tata letak Streamlit menggunakan komponen Tab:
   * **Tab Ringkasan Eksekutif & Analitik:** Menyajikan grafik tren sentimen, metrik KPI utama, dan narasi rekomendasi AI.
   * **Tab Audit Model & Data:** Menyajikan tabel detail jejak audit data mentah vs teks baku untuk transparansi analisis.
5. **Uji Coba Pengoperasian:**
   Jalankan perintah `streamlit run app.py` dan verifikasi bahwa setiap penambahan data baru di database langsung direfleksikan secara *real-time* pada dasbor.
