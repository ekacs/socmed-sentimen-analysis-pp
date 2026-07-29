
# Rencana Konversi Desktop (Opsi C: PyInstaller .exe)

Rencana ini disimpan untuk dieksekusi **setelah seluruh fitur aplikasi utama (Streamlit, Scraper, Model AI/ML, dan UI) selesai dan utuh dibangun**.

## Tujuan

Mengonversi aplikasi Streamlit `app.py` beserta seluruh skrip pendukung (`01_run_scraper.py`, `01_pipeline_data.py`, dll.) menjadi file `.exe` mandiri yang dapat didistribusikan kepada pengguna awam (tanpa perlu menginstal Python).

## Pendekatan Teknis (PyInstaller)

Karena Streamlit cukup menantang untuk dikompilasi secara langsung, pendekatan yang direkomendasikan adalah membuat skrip "entry-point" yang menjalankan server Streamlit menggunakan fungsi subprocess/sys.argv, lalu membungkusnya.

### Langkah-langkah (To-Do List Masa Depan)

1. **Pembuatan Skrip Entry Point (`run_desktop.py`)**

   - Membuat skrip yang memanggil `streamlit run app.py` secara terprogram.
   - Mengatur port yang dinamis atau tetap (misal 8501).
   - Menambahkan opsi pembuka browser otomatis menggunakan library `webbrowser`.
2. **Manajemen File Statis & Dependensi Tersembunyi**

   - Menyiapkan file `.spec` (konfigurasi PyInstaller) untuk memasukkan file yang bukan kode Python secara eksplisit (seperti `models/svm_model.pkl`, `models/tfidf_vectorizer.pkl`, `target_config.json`, dan file database `sentimen_kebijakan.db` atau memastikan jalur lokalnya benar).
   - Memastikan hooks untuk library berat seperti `pandas`, `scikit-learn`, `joblib`, `apify_client`, dan `google-genai` dimasukkan ke dalam *hidden-imports* PyInstaller.
3. **Penyesuaian Jalur File Relatif (Path Resolution)**

   - Saat aplikasi dikemas menjadi `.exe` dalam satu file, PyInstaller mengekstraknya ke dalam folder temp `_MEIPASS`.
   - Modifikasi kecil di kode (jika diperlukan) untuk menggunakan fungsi resolusi path seperti ini:

     ```python
     def get_base_path():
         if hasattr(sys, '_MEIPASS'):
             return sys._MEIPASS
         return os.path.dirname(os.path.abspath(__file__))
     ```
   - Ini penting untuk memuat `.env`, `target_config.json`, dan direktori `models/`.
4. **Proses Kompilasi (Build Process)**

   - Menjalankan perintah kompilasi:

     ```bash
     pyinstaller --onefile --noconsole --additional-hooks-dir=hooks run_desktop.py
     ```
   - (Catatan: `--noconsole` menyembunyikan terminal hitam di Windows).
5. **Tahap Testing (UAT - User Acceptance Test)**

   - Menjalankan file `.exe` yang dihasilkan.
   - Memastikan koneksi database SQLite berjalan.
   - Memastikan *subprocess* scraper dan *pipeline* tidak memicu loop eksekusi rekursif (sering terjadi di PyInstaller multiprocessing, butuh `multiprocessing.freeze_support()`).
   - Memastikan API Apify dan Gemini sukses terpanggil dari dalam `.exe`.

## Prasyarat Klien Akhir (End-User)

Meskipun menjadi file `.exe`, pengguna tetap wajib:

- Terhubung ke Internet.
- Memiliki akses atau file `.env` yang valid untuk kredensial API (jika `.env` tidak *hardcoded* di dalam `.exe`).
