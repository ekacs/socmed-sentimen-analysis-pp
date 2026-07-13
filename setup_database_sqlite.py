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
            status TEXT DEFAULT 'RAW',          -- Status pemrosesan data ('RAW' / 'CLEANED')
            source_platform TEXT NOT NULL       -- Keterangan sumber: 'Twitter', 'Instagram', 'LinkedIn', 'News'
        )
    ''')
    
    conn.commit()
    conn.close()
    print("[OK] Basis data dan tabel 'log_cuitan' berhasil diselaraskan!")

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
                sentiment_label, confidence_score, likes, retweets, status,
                source_platform
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                d.get('status', 'RAW'),
                d.get('source_platform', 'Twitter')
            )
            for d in data_cuitan
        ]
        
        cursor.executemany(query, data_tuple)
        conn.commit()
        print(f"[SUCCESS] {len(data_cuitan)} data diproses. Penyisipan selesai (data duplikat diabaikan otomatis).")
        
    except sqlite3.Error as e:
        print(f"[ERROR] Kesalahan pada sistem basis data: {e}")
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
            'status': 'CLEANED',
            'source_platform': 'Twitter'
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
            'status': 'CLEANED',
            'source_platform': 'Twitter'
        }
    ]
    
    # Simpan simulasi data pertama kali
    print("\n--- Percobaan Penyisipan Pertama (Data Baru) ---")
    simpan_data_ke_db(data_uji_coba)
    
    # Jalankan ulang penyisipan untuk membuktikan keandalan sistem deduplikasi
    print("\n--- Percobaan Penyisipan Kedua (Sengaja Menduplikasi Data) ---")
    simpan_data_ke_db(data_uji_coba)  # Harus melaporkan berhasil tanpa menambahkan baris baru di DB
    
    # 3. Verifikasi Data untuk Streamlit
    print("\n[DATA] Hasil Pembacaan Data untuk Dasbor:")
    df_dashboard = baca_data_untuk_streamlit()
    print(df_dashboard[['tweet_id', 'username', 'sentiment_label', 'likes', 'retweets']])
