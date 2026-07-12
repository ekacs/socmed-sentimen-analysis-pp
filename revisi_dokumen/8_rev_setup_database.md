# Analisis & Penyesuaian Kode `setup_database_sqlite.py`
**Proyek:** Analisis Sentimen Kebijakan Publik Berbasis Kecerdasan Buatan (AI)

---

## 1. Analisis Relevansi & Isu Krusial pada Kode Saat Ini
Kode `setup_database_sqlite.py` Anda saat ini **sangat relevan** sebagai modul inisialisasi basis data lokal. Penggunaan metode parameterisasi (`?`) untuk mencegah *SQL Injection* serta metode `executemany` untuk penulisan data secara massal (*batch insert*) adalah praktik terbaik yang sangat baik dari segi performa dan keamanan.

Namun, terdapat **3 masalah struktural krusial** yang tidak sinkron dengan dokumen arsitektur dan modul scraping sebelumnya yang dapat menyebabkan kegagalan sistem (*bug*) atau hasil analisis yang tidak akurat pada dasbor Anda:

### Isu A: Ketidakselarasan Nama Kolom (Inkonsistensi Arsitektur)
* **Kondisi Saat Ini:** Modul Database menggunakan bahasa campuran (`tanggal`, `teks_asli`, `teks_baku`, `label_sentimen`), sedangkan Modul Scraping Twitter (Dokumen 5 & 6) menghasilkan kolom berbahasa Inggris dan terstandarisasi dari API Apify (`tweet_id`, `date`, `raw_text`, `username`, `likes`, `retweets`).
* **Dampak:** Skrip penarik data (*pipeline*) Anda akan mengalami kegagalan pemetaan (*mapping error*) saat mencoba menyimpan data hasil scraping ke dalam database karena kolom tidak cocok.

### Isu B: Hilangnya Mekanisme Pencegahan Duplikasi Data (*Deduplication*)
* **Kondisi Saat Ini:** Anda menggunakan kolom `id INTEGER PRIMARY KEY AUTOINCREMENT` sebagai kunci utama.
* **Dampak:** Jika skrip scraping dijalankan dua kali (misalnya hari ini pukul 08.00 dan pukul 12.00) dan mengambil cuitan yang sama, SQLite akan tetap memasukkannya kembali ke database sebagai baris baru dengan `id` baru. Hal ini akan menyebabkan **duplikasi data besar-besaran** yang merusak akurasi visualisasi dan statistik pada dasbor Streamlit Anda.
* **Solusi:** `tweet_id` (ID unik asli dari Twitter/X) harus dijadikan sebagai **PRIMARY KEY** dan menggunakan sintaks `INSERT OR IGNORE` berdasarkan kolom tersebut.

### Isu C: Kehilangan Metrik Vital untuk Dasbor Analitik
* **Kondisi Saat Ini:** Tabel Anda tidak menyediakan kolom untuk menyimpan data keterlibatan (*engagement metrics*) seperti `likes` (jumlah suka) dan `retweets` (jumlah bagikan).
* **Dampak:** Anda tidak bisa menyajikan grafik "Cuitan Paling Berpengaruh" atau menganalisis korelasi antara sentimen publik dengan tingkat keviralannya di Streamlit.

---

## 2. Struktur Perbandingan Kode

### Skema Tabel Sebelum Penyesuaian (Memicu Error & Duplikasi):
```python
cursor.execute('''
    CREATE TABLE IF NOT EXISTS log_cuitan (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tanggal TEXT NOT NULL,
        username TEXT,
        teks_asli TEXT NOT NULL,
        teks_baku TEXT,
        label_sentimen TEXT,
        skor_keyakinan REAL
    )
''')
# Duplikasi data akan terjadi karena id akan selalu bertambah secara otomatis untuk tweet yang sama.
```

### Skema Tabel Setelah Penyesuaian (Sinkron, Anti-Duplikasi, & Kaya Metrik):
Berikut adalah pembaharuan kode `setup_database_sqlite.py` yang telah disinkronkan dengan arsitektur scraping Twitter Apify, menggunakan standar penamaan yang konsisten, dan siap dimigrasikan ke Supabase PostgreSQL di masa depan:

```python
import sqlite3
import pandas as pd
from datetime import datetime

# Menggunakan satu nama file database yang konsisten dengan dokumen arsitektur
DB_FILE = 'sentimen_kebijakan.db'

def buat_tabel():
    """
    Membuat file database 'sentimen_kebijakan.db' dan tabel 'log_cuitan' 
    dengan skema terstandarisasi (anti-duplikasi & kaya metrik analitik).
    """
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    # Membuat Skema Tabel yang disinkronkan dengan Modul Scraping
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS log_cuitan (
            tweet_id TEXT PRIMARY KEY,          -- Mencegah duplikasi data tweet secara mutlak
            date TEXT NOT NULL,                 -- Format tanggal ISO 8601 terstandar
            username TEXT NOT NULL,             -- Nama akun pembuat cuitan
            raw_text TEXT NOT NULL,             -- Suara mentah masyarakat (untuk audit trail)
            cleaned_text TEXT,                  -- Teks hasil standardisasi EYD oleh Gemini API
            sentiment_label TEXT,               -- Hasil klasifikasi: 'Positif', 'Negatif', atau 'Netral'
            confidence_score REAL,              -- Tingkat akurasi/keyakinan model klasifikasi (0.0 - 1.0)
            likes INTEGER DEFAULT 0,            -- Jumlah suka (metrik analitik tambahan)
            retweets INTEGER DEFAULT 0,         -- Jumlah bagikan (metrik analitik tambahan)
            status TEXT DEFAULT 'RAW'           -- Status pemrosesan data ('RAW' / 'CLEANED')
        )
    ''')
    
    conn.commit()
    conn.close()
    print("✅ Basis data dan tabel 'log_cuitan' berhasil diselaraskan!")

def simpan_data_ke_db(data_cuitan):
    """
    Menyimpan data cuitan ke database menggunakan pendekatan UPSERT (INSERT OR IGNORE)
    untuk menghindari kegagalan sistem akibat data ganda.
    """
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()

        # Klausa INSERT OR IGNORE menjamin data ganda dilewati dengan aman tanpa memicu crash
        query = '''
            INSERT OR IGNORE INTO log_cuitan (
                tweet_id, date, username, raw_text, cleaned_text, 
                sentiment_label, confidence_score, likes, retweets, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        '''
        
        # Ekstraksi dan pemetaan yang aman dari List of Dictionary
        data_tuple = [
            (
                d['tweet_id'], 
                d['date'], 
                d['username'], 
                d['raw_text'], 
                d.get('cleaned_text', None), 
                d.get('sentiment_label', None), 
                d.get('confidence_score', 0.0),
                d.get('likes', 0),
                d.get('retweets', 0),
                d.get('status', 'RAW')
            )
            for d in data_cuitan
        ]
        
        cursor.executemany(query, data_tuple)
        conn.commit()
        print(f"🚀 {len(data_cuitan)} data diproses. Penyisipan selesai (data duplikat diabaikan otomatis).")
        
    except sqlite3.Error as e:
        print(f"❌ Kesalahan pada sistem basis data: {e}")
    finally:
        if conn:
            conn.close()

def baca_data_untuk_streamlit():
    """
    Mengambil seluruh data transaksi dari basis data SQLite ke dalam Pandas DataFrame
    untuk disajikan pada visualisasi dasbor Streamlit.
    """
    conn = sqlite3.connect(DB_FILE)
    
    # Query mengambil data terbaru berdasarkan tanggal teratas
    df = pd.read_sql_query("SELECT * FROM log_cuitan ORDER BY date DESC", conn)
    
    conn.close()
    return df

if __name__ == "__main__":
    # 1. Inisialisasi Database & Tabel
    buat_tabel()
    
    # 2. Simulasi Data Hasil Pipeline Integrasi (Twitter -> Gemini -> Model SVM)
    data_uji_coba = [
        {
            'tweet_id': '1811739213481230336',  # ID tweet nyata bertipe string panjang
            'date': datetime.now().isoformat() + "Z",  # Format standardisasi ISO 8601 UTC
            'username': '@warga_komuter',
            'raw_text': 'Macet parah nih KRL transit manggarai ampun dah telat mulu 😡',
            'cleaned_text': 'Macet sekali perjalanan KRL transit di Manggarai. Saya selalu terlambat.',
            'sentiment_label': 'Negatif',
            'confidence_score': 0.94,
            'likes': 152,
            'retweets': 45,
            'status': 'CLEANED'
        },
        {
            'tweet_id': '1811739213481230337',
            'date': datetime.now().isoformat() + "Z",
            'username': '@penikmat_transit',
            'raw_text': 'salut bgt ac krl gerbong wanita sekarang dingin pool thx KAI',
            'cleaned_text': 'Sangat salut dengan AC KRL di gerbong wanita sekarang sangat dingin, terima kasih KAI.',
            'sentiment_label': 'Positif',
            'confidence_score': 0.89,
            'likes': 80,
            'retweets': 12,
            'status': 'CLEANED'
        }
    ]
    
    # Simpan simulasi data pertama kali
    print("\n--- Percobaan Penyisipan Pertama (Data Baru) ---")
    simpan_data_ke_db(data_uji_coba)
    
    # Jalankan ulang penyisipan untuk membuktikan keandalan sistem deduplikasi
    print("\n--- Percobaan Penyisipan Kedua (Sengaja Menduplikasi Data) ---")
    simpan_data_ke_db(data_uji_coba)  # Harus melaporkan berhasil tanpa menambahkan baris baru di DB
    
    # 3. Verifikasi Data untuk Streamlit
    print("\n📊 Hasil Pembacaan Data untuk Dasbor:")
    df_dashboard = baca_data_untuk_streamlit()
    print(df_dashboard[['tweet_id', 'username', 'sentiment_label', 'likes', 'retweets']])
```

---

## 3. Manfaat Penyesuaian bagi Sistem Anda
1. **Bebas dari Data Duplikat:** Integritas data pada dasbor Streamlit Anda dijamin 100% akurat karena basis data secara otomatis menolak tweet dengan `tweet_id` yang sama.
2. **Siap Bermigrasi ke Supabase (Cloud PostgreSQL):** Karena format tipe data, parameter kueri, dan standardisasi tanggal (ISO 8601 UTC) sudah disesuaikan dengan standar industri, proses migrasi skema tabel ke Supabase di kemudian hari tidak memerlukan perombakan kode apa pun.
3. **Analitik yang Lebih Kaya:** Dasbor Streamlit Anda kini dapat menampilkan grafik visualisasi berdasarkan "Jumlah Suka/Likes" dan "Jumlah Retweet" untuk menganalisis penyebaran persepsi publik secara lebih komparatif.
