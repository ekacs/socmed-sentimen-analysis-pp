github.com/ekacs

---

## 📑 Penjelasan Fitur Tab "Jejak Audit Data Mentah & Baku"

### 🎯 Kegunaan Bagi User

Tab ini untuk **transparansi** dari sistem analisis sentimen. Dalam konteks **kebijakan publik**, user (biasanya **Analis Kebijakan, Staf Ahli Kemenkumham, Komisioner, atau Tim Audit**) TIDAK BISA hanya menerima angka Pie-chart dominan Negatif atau Positif sebagai kebenaran begitu saja. Mereka butuh jawaban:

> **"Dari mana angka ini berasal? Apakah AI tidak salah mengubah arti kalimat tweet masyarakat? Apa yang sebenarnya dikatakan publik?"**

Fitur ini menjawab pertanyaan audit itu dengan memajukan **KOLOM TEKS MENTAH (raw_text) DAN TEKS BAKU (cleaned_text) BERSEBELAHAN** untuk setiap baris data, plus label sentimen + skor keyakinan.

---

### 🧩 8 Fungsi Audit Praktis Bagi Pengguna

| #   | Kegunaan                                           | Contoh Use Case Kebijakan Publik                                                                                                                                                              |
| --- | -------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | **Verifikasi Apakah AI Tidak Merusak Makna**       | Publik tweet: *"IKN bagus tapi lambat bayar kontraktor!"* → AI EYD jangan malah berubah jadi *"IKN bagus dan lancar!"* (kebalikan makna). Cek di tab ini sebelum bikin rekomendasi ke atasan. |
| 2   | **Audit Label Sentimen SVM — Kenapa ini Negatif?** | Data tampil "Negatif 92%", tapi kalimatnya tampak netral → user bisa trace: apakah di cleaned_text ada kata "tipu, penipuan, korupsi, gagal, kecewa" yang jadi pemicu fitur TF-IDF SVM        |
| 3   | **Kualitas Data Scraper — Banyak Junk?**           | Ada baris `raw_text="halo sobat linknya https://t.co/xxx"` → cleaned_text masih kosong → user tahu Apify menarik data spam → perlu tambah stop word atau limitasi platform                    |
| 4   | **Validasi Biaya APIFY vs Output**                 | User set batas 500 tweet → cek berapa banyak baris ID konten unik → tahu apakah kredit Apify terpakai sia-sia                                                                                 |
| 5   | **Cross-Check Duplikasi**                          | 2 baris punya ID konten sama → tahu bahwa UPSERT DB tidak berjalan sempurna                                                                                                                   |
| 6   | **Bahan Pembuktian Laporan ke Atasan**             | Bisa copy paste contoh 2-3 tweet asli + sentimen ke laporan PDF/Laporan DPR (accountability)                                                                                                  |
| 7   | **Debug Scraper Per-Platform**                     | Filter Platform=News → cek raw_text Portal Berita → apakah body artikel terisi penuh atau cuma header kosong? (cek apakah `website-content-crawler` playwright jalan)                         |
| 8   | **Cek Ripple Effect Gemma EYD Limit**              | Kalimat negatif panjang 280 karakter → `cleaned_text` terpotong/tidak berubah sama sekali → user tahu `Gemini API rate limit / retry mechanism` tidak aktif sempurna                          |

---

### 🔄 Proses Kerja (Pipeline Data) — Bagaimana Sehingga Bisa Terlihat Seperti Itu

Semua kolom di tabel audit berasal dari **SATU SUMBER DATA** yaitu Tabel `log_cuitan` (SQLite lokal / PostgreSQL Supabase) yang melewati 3 tahap pipeline. Berikut alurnya baris demi baris:

```
┌─────────────────────────────────────────────────────────────────────────┐
│ TAHAP 1 : Penarikan Data Scraper (01_run_scraper.py)                    │
│ Actor Apify Cloud: apidojo/tweet-scraper, instagram-scraper, harvestapi │
│ website-content-crawler.                                                │
└───────────────────────────────────────┬─────────────────────────────────┘
                                        ▼
                          [ UPSERT KE TABEL log_cuitan ]
                          status = 'RAW'
                          ┌─────────────────────────────┐
                     ╔════╩═════════════════════════════╩══════╗
                     ║ FIELD YANG DITULIS DI TAHAP INI:       ║
                     ║ • tweet_id   → "ID Konten" (PK, UNIK) ║ ← Sumber kolom 1
                     ║ • date       → "Tanggal Pembuatan"   ║ ← Sumber kolom 2
                     ║ • username   → "Username"            ║ ← Sumber kolom 3
                     ║ • raw_text   → "Teks Mentah"         ║ ← Sumber kolom 4 (KRUSIAL!)
                     ║ • source_platform → "Platform"        ║ ← Sumber kolom 8
                     ║ • cleaned_text = NULL                ║ ══ DENGAN DULU ══
                     ║ • sentiment_label = NULL             ║ ══ DENGAN DULU ══
                     ║ • confidence_score = NULL            ║ ══ DENGAN DULU ══
                     ╚══════════════════════════════════════╝
                                        │
                                        ▼ (user klik Langkah 2 AI/ML)
┌─────────────────────────────────────────────────────────────────────────┐
│ TAHAP 2 : Prapemrosesan AI EYD + Label SVM (01_pipeline_data.py)       │
└───────────────────────────────────────┬─────────────────────────────────┘
                                        ▼
                           Loop WHERE status='RAW':
                           
   ┌──────────────────────────────────────────────────────────────────────┐
   │  2a. PANGGIL clean_text_with_gemini(raw_text)                        │
   │      Input: "IKN lambat bg! pak Jokowi ksh kompensasi dong!!"        │
   │      Retry 3x exponential backoff, fallback raw jika limit.         │
   │      Output (Teks Baku EYD):                                         │
   │      ╔═════════════════════════════════════════════════════════════╗ ║
   │      ║ cleaned_text = "IKN lambat sekali. Bapak Presiden Jokowi   ║ ║ ← kolom 5
   │      ║     tolong berikan kompensasi segera!"                     ║ ║
   │      ╚═════════════════════════════════════════════════════════════╝ ║
   │                                                                      │
   │  2b. LOAD MODEL SVM (.joblib) → tfidf_vectorizer.transform(teks)    │
   │      ╔═════════════════════════════════════════════════════════════╗ ║
   │      ║ sentiment_label   = "Negatif"                               ║ ║ ← kolom 6
   │      ║ confidence_score  = 0.924                                   ║ ║ ← kolom 7
   │      ╚═════════════════════════════════════════════════════════════╝ ║
   │                                                                      │
   │  2c. UPDATE baris WHERE tweet_id = ? SET cleaned_text=?, sentimen=? │
   │              status = 'CLEANED'                                      │
   └──────────────────────────────────────────────────────────────────────┘
                                        │
                                        ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ TAHAP 3 : Query ke app.py Streamlit + Sidebar Filter                    │
└───────────────────────────────────────┬─────────────────────────────────┘
                                        ▼
                    st.sidebar.multiselect(platform_filter)
                    st.sidebar.date_input(date_range)
                                        │
                                        ▼
                        df_all = db_manager.semua_data() → FILTER
                                        │
                                        ▼
                  df_filtered (sudah sesuai filter sidebar!)
                                        │
                                        ▼
  ┌──────────────────────────────────────────────────────────────────────────┐
  │ app.py:1381 (TAB 2 Jejak Audit):                                        │
  │ audit_cols = [ tweet_id, date, username, raw_text, cleaned_text,        │
  │               sentiment_label, confidence_score, source_platform ]      │
  │            ↕️ mapping nama kolom agar ramah manusia ↕️                   │
  │ df_audit.columns = [                                                    │
  │   'ID Konten',         ← dari tweet_id (PK asli platform)               │
  │   'Tanggal Pembuatan', ← dari date                                      │
  │   'Username',          ← dari username                                  │
  │   'Teks Mentah (X/X-like)',  ← raw_text (ASLI, TIDAK DIUBAH AI)        │
  │   'Teks Baku (EYD AI)',      ← cleaned_text (OUTPUT GEMINI)            │
  │   'Label Sentimen',          ← output klasifikasi SVM Linear            │
  │   'Skor Keyakinan',          ← predict_proba SVM (0.00 s/d 1.00)       │
  │   'Platform'                 ← source_platform (Twitter/IG/LinkedIn/News)│
  │ ]                                                                        │
  │         st.dataframe(df_audit) + format tanggal YYYY-MM-DD HH:mm:ss     │
  └──────────────────────────────────────────────────────────────────────────┘
```

---

### 🔗 Integrasi dengan Tab Lain

Hubungan antara ketiga tab dalam 1 siklus kerja Analis Kebijakan:

```
   Tab 🛠️ Pengaturan Target
   (Setting keywords, platform, limit, save target_config.json)
                │
                ▼ klik 🚀 Langkah 1 + 🧠 Langkah 2
   Tab 📑 Jejak Audit Data  ←────────────────────────────────┐
   (Audit kualitas tiap baris: raw vs cleaned vs sentimen)    │
   User cek: "apakah AI mengubah makna kalimat #125?"         │
   User cek: "apakah website-content-crawler berita Kompas    │
                sukses menarik body artikel atau cuma kosong?" │
                │                                              │
                ▼ verified OK (data bersih)                   │
   Tab 📊 Analitik Sentimen                                   │
   (Pie distribusi, Tren harian, Ringkasan Eksekutif,         │
    Top kata kunci, Export PDF laporan kebijakan)             │
                │                                              │
                ▼ (ketemu aneh: misal tiba-tiba 80% negatif)  │
   KEMBALI KE ────────────────────────────────────────────────┘
   (Investigasi penyebab baris demi baris yang mengganggu)
```

---

### 🏷️ Tombol Pendukung Audit

Di pojok kanan atas ada **🌐 Editor Supabase**:

- Link ke `https://supabase.com/dashboard/project/xxxx/editor/...` (dari function `get_supabase_dashboard_url()`)
- Gunanya: **jika user menemukan BARIS YANG SALAH LABEL / JUNK / SPAM** (misal kolom Teks Mentah kosong atau bot spam), user bisa langsung **DELETE baris itu di Supabase**, refresh Streamlit, lalu angka Pie-chart di Tab Analitik otomatis terupdate tanpa perlu re-scrape / re-train model.

---

**Kesimpulan:** Tab Jejak Audit Data adalah **quality gate accountability layer** yang membedakan sistem ML untuk kebijakan publik (butuh audit trail ketat) vs ML biasa untuk dashboard bisnis (yang cuma perlu angka chart). TANPA tab ini, laporan analisis sentimen ke Pimpinan bisa dengan mudah dibatalkan oleh pihak lain dengan alasan "Model AI kita dianggap halu!"
