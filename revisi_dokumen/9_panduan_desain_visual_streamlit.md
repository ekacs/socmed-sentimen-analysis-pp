# Panduan Desain Visual Streamlit & Klarifikasi Alur Kerja
**Proyek:** Analisis Sentimen Kebijakan Publik Berbasis Kecerdasan Buatan (AI)

---

## Bagian 1: Apakah Proses Pembersihan Sudah Masuk pada Roadmap Modul Scraping?

Secara arsitektur, **Proses Pembersihan (Prapemrosesan AI)** sengaja dipisahkan dari **Modul Scraping Murni**, namun **sudah sepenuhnya terintegrasi di dalam Peta Jalan Penggabungan (End-to-End Pipeline)**.

Berikut adalah penjelasan mengapa pemisahan ini dilakukan dan di mana posisi proses pembersihan tersebut berada di dalam peta jalan yang telah kita susun:

### 1. Pemisahan Tanggung Jawab (*Separation of Concerns*)
* **Modul Scraping (Dokumen 5 & 6):** Berfokus murni pada *Data Ingestion* (penarikan data mentah). Modul ini bertugas mengambil data secepat dan seandil mungkin dari Twitter melalui platform Apify, lalu langsung menyimpannya ke database dengan status `'RAW'`. 
* **Alasan Pemisahan:** Proses scraping Twitter sangat rawan terkena pembatasan laju (*rate limits*) atau blokir IP. Jika proses scraping digabungkan langsung dengan proses pembersihan teks menggunakan LLM (yang memerlukan waktu tunggu/latensi API Gemini), maka jika API Gemini mengalami keterlambatan (*timeout*), koneksi scraping Anda bisa terputus di tengah jalan.

### 2. Posisi Pembersihan di dalam Peta Jalan (Roadmap)
Proses pembersihan teks menggunakan kekuatan AI (Gemini) ditempatkan pada **Langkah 3** dan **Langkah 5** di dalam **Peta Jalan Pengembangan Lokal (Dokumen 2)**:
* **Langkah 3 (Roadmap Lokal):** Membuat modul pipa data (`01_pipeline_data.py`) yang berisi fungsi khusus pembersihan bahasa menggunakan perintah instruksi (*System Prompt*) Gemini API untuk mengubah bahasa gaul/singkatan ke EYD baku.
* **Langkah 5 (Roadmap Lokal):** Melakukan integrasi akhir. Setelah data mentah berhasil ditarik oleh scraper, data tersebut langsung dialirkan ke fungsi pembersihan Gemini, dilabeli oleh model ML, dan disimpan ke database dengan status `'CLEANED'`.

Dengan alur ini, Anda memiliki **jejak audit (*audit trail*) yang sempurna**: Anda menyimpan teks mentah asli dari masyarakat sekaligus teks bersih hasil standardisasi AI di dalam satu baris database yang sama untuk transparansi analisis.

---

## Bagian 2: Saran Desain Visual Dasbor Streamlit Modern

Streamlit secara bawaan memiliki tampilan yang fungsional, namun sering kali terlihat generik. Untuk membuat dasbor analisis sentimen kebijakan publik Anda terlihat **sangat premium, bersih (minimalis), fungsional, dan persuasif bagi para pemangku kebijakan**, Anda dapat menerapkan konsep desain visual berikut:

### 1. Konsep Estetika: *Minimalist Corporate & Executive Analytics*
Hindari penggunaan warna-warna neon yang mencolok atau gradasi warna yang berlebihan (kesan *tech-larping*). Gunakan pendekatan gaya desain Swiss Modern: **kontras tinggi, tipografi bersih, ruang negatif yang lega, dan fungsional**.

* **Warna Latar Belakang (*Canvas*):** Putih bersih (`#FFFFFF`) atau abu-abu ultra-terang (*soft off-white* seperti `#F8F9FA`) untuk area utama, dikombinasikan dengan warna abu-abu slate muda (`#F1F3F5`) untuk area kartu metrik.
* **Warna Teks Utama:** Charcoal gelap (`#212529`) untuk memastikan keterbacaan tingkat tinggi (*high accessibility contrast*).
* **Warna Aksen Sentimen (Palet Redup/Muted):**
  * Sentimen **Positif:** Hijau Zamrud Lembut (*Emerald Green* - `#2D6A4F` atau `#D8F3DC` sebagai latar belakang kartu).
  * Sentimen **Netral:** Biru Slate Lembut (*Steel Blue* - `#4682B4` atau `#E8F1F5`).
  * Sentimen **Negatif:** Merah Bata/Terracotta (*Muted Crimson* - `#B00020` atau `#FFD8D8`).

### 2. Struktur Tata Letak: *Bento Grid Layout* (Berbasis Kolom)
Manfaatkan fitur `st.columns()` untuk membagi informasi ke dalam kotak-kotak fungsional yang sejajar, menyerupai tren desain tata letak *bento grid* modern:

```
┌────────────────────────────────────────────────────────┐
│  [HEADER] Judul Dasbor & Selektor Filter Rentang Waktu  │
├────────────────────────────────────────────────────────┤
│  [KARTU METRIK UTAMA - 3 KOLOM SEJAJAR]                 │
│  ┌────────────────┐ ┌────────────────┐ ┌─────────────┐ │
│  │ Total Volume   │ │ Dominasi Isu   │ │ Indeks Sent │ │
│  │ 1.250 Tweet    │ │ Delay & AC     │ │ 60% Negatif │ │
│  └────────────────┘ └────────────────┘ └─────────────┘ │
├────────────────────────────────────────────────────────┤
│  [AREA UTAMA - 2 KOLOM TIDAK SEJAJAR - RASIO 70:30]    │
│  ┌───────────────────────────────────┐ ┌─────────────┐ │
│  │ KOLOM KIRI (70%):                 │ │KOLOM KANAN  │ │
│  │ - Tren Sentimen Harian (Line Chart)│ │(30%):       │ │
│  │ - Narasi Ringkasan Eksekutif AI   │ │- Top Words  │ │
│  │   (NLG Laporan Komparatif)        │ │  (List)     │ │
│  └───────────────────────────────────┘ └─────────────┘ │
├────────────────────────────────────────────────────────┤
│  [BAGIAN BAWAH]                                        │
│  - Jejak Audit Data: Tabel Interaktif (Teks Mentah vs  │
│    Teks Bersih)                                        │
└────────────────────────────────────────────────────────┘
```

### 3. Trik Injeksi CSS Kustom Streamlit (Membuat Dasbor Terlihat Premium)
Anda dapat menyisipkan kode CSS kustom di bagian atas skrip `app.py` untuk menghilangkan elemen-elemen bawaan Streamlit yang mengganggu estetika (seperti garis merah di bagian atas, menu hamburger, dan footer default), sekaligus mempercantik visual kartu:

```python
import streamlit as st

# Mengatur konfigurasi halaman agar menggunakan layout lebar secara bawaan
st.set_page_config(
    page_title="Analisis Sentimen Kebijakan Publik",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Injeksi CSS Kustom untuk estetika Swiss Modern yang bersih
st.markdown("""
    <style>
        /* 1. Menghilangkan dekorasi bawaan Streamlit */
        #MainMenu {visibility: hidden;}
        footer {visibility: hidden;}
        header {visibility: hidden;}
        
        /* 2. Mengatur font global ke Inter atau system-ui */
        html, body, [class*="css"] {
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
            color: #212529;
        }
        
        /* 3. Mendesain kartu metrik agar memiliki sudut tumpul halus & bayangan sangat tipis */
        div[data-testid="stMetricValue"] {
            font-size: 2rem !important;
            font-weight: 700 !important;
            color: #1A1D20 !important;
        }
        
        /* 4. Membuat border halus pada container visualisasi */
        div.stBox {
            border: 1px solid #E9ECEF !important;
            border-radius: 8px !important;
            background-color: #F8F9FA !important;
            padding: 1.5rem !important;
        }
    </style>
""", unsafe_allow_html=True)
```

### 4. Optimalisasi Grafik (*Functional Charts over Decorative Charts*)
* **Gunakan Plotly, Hindari Matplotlib:** Plotly menghasilkan grafik interaktif yang tajam (bisa di-zoom dan memiliki tooltip hover) serta secara dinamis menyesuaikan ukuran layar.
* **Sederhanakan Sumbu & Elemen Grafik:**
  * Hilangkan garis kisi-kisi (*gridlines*) yang terlalu ramai di latar belakang grafik.
  * Buat latar belakang kanvas grafik menjadi transparan (`paper_bgcolor='rgba(0,0,0,0)'`, `plot_bgcolor='rgba(0,0,0,0)'`) agar menyatu sempurna dengan warna latar dasbor Streamlit Anda.
  * Gunakan diagram garis (*Line Chart*) bersudut tumpul (*spline*) untuk tren waktu, yang jauh lebih mudah dibaca dibanding diagram batang bertumpuk yang membingungkan bagi eksekutif.

### 5. Interaksi Pengguna yang Taktis
* **Sidebar Minimalis:** Tempatkan filter-filter global seperti selektor tanggal, pilihan kategori kebijakan, dan tombol unduh laporan di bagian Sidebar kiri yang dapat disembunyikan (*collapsible*). Biarkan area tengah fokus penuh sebagai kanvas laporan visual.
* **Sajian Tab untuk Kejelasan Informasi:**
  * **Tab 1: Ringkasan & Tren (Fokus Eksekutif):** Berisi metrik utama, grafik tren, dan Ringkasan Eksekutif berbasis NLG.
  * **Tab 2: Analisis Detail (Fokus Operasional):** Berisi grafik distribusi kata kunci, sentimen per stasiun/wilayah, dan analisis korelasi.
  * **Tab 3: Jejak Audit (Fokus Transparansi):** Menampilkan tabel interaktif berisi teks mentah dari Twitter bersandingan dengan teks yang sudah dibersihkan oleh Gemini API, memberikan jaminan keandalan analisis kepada pemangku kebijakan.
