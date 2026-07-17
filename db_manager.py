import os
import sqlite3
import pandas as pd
from dotenv import load_dotenv

# Memuat file .env — override=False agar env var sistem (GitHub Actions) tidak tertimpa
load_dotenv(override=False)

DB_FILE = 'sentimen_kebijakan.db'

def get_db_type():
    """
    Menentukan tipe database yang digunakan berdasarkan ketersediaan DATABASE_URL.
    """
    db_url = os.getenv("DATABASE_URL", "")
    if db_url and "postgresql://" in db_url and "YOUR_DATABASE_URL" not in db_url:
        return "postgresql"
    return "sqlite"

def get_connection():
    """
    Mendapatkan koneksi database yang sesuai (sqlite3 atau psycopg2).
    """
    db_type = get_db_type()
    db_url = os.getenv("DATABASE_URL")
    
    if db_type == "postgresql":
        import psycopg2
        # Menghapus bracket literal jika ada di placeholder kata sandi
        if "[" in db_url and "]" in db_url:
            db_url = db_url.replace("[", "").replace("]", "")
        return psycopg2.connect(db_url)
    else:
        return sqlite3.connect(DB_FILE)

def get_placeholder():
    """
    Mendapatkan string placeholder parameter SQL yang sesuai (? untuk SQLite, %s untuk PostgreSQL).
    """
    return "%s" if get_db_type() == "postgresql" else "?"

def buat_tabel():
    """
    Membuat skema tabel 'log_cuitan' yang kompatibel dengan SQLite dan PostgreSQL.
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        # Skema tabel identik untuk kedua tipe database
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
        print(f"[OK] Basis data ({get_db_type()}) dan tabel 'log_cuitan' berhasil diselaraskan!")
    except Exception as e:
        print(f"[ERROR] Gagal menyelaraskan tabel: {e}")
    finally:
        conn.close()

def simpan_data_ke_db(data_cuitan):
    """
    Menyimpan data cuitan ke database menggunakan pendekatan UPSERT yang disesuaikan
    dengan tipe database aktif (ON CONFLICT untuk PostgreSQL, INSERT OR IGNORE untuk SQLite).
    """
    if not data_cuitan:
        return
        
    db_type = get_db_type()
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        if db_type == "postgresql":
            query = '''
                INSERT INTO log_cuitan (
                    tweet_id, date, username, raw_text, cleaned_text, 
                    sentiment_label, confidence_score, likes, retweets, status,
                    source_platform
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (tweet_id) DO NOTHING
            '''
        else:
            query = '''
                INSERT OR IGNORE INTO log_cuitan (
                    tweet_id, date, username, raw_text, cleaned_text, 
                    sentiment_label, confidence_score, likes, retweets, status,
                    source_platform
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            '''
            
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
        print(f"[SUCCESS] {len(data_cuitan)} data diproses. Penyisipan ke {db_type} selesai (duplikasi diabaikan otomatis).")
    except Exception as e:
        print(f"[ERROR] Kesalahan saat menyisipkan data ke database: {e}")
    finally:
        conn.close()

def baca_data_untuk_streamlit():
    """
    Mengambil seluruh data dari basis data untuk disajikan di dasbor Streamlit.
    Menggunakan SQLAlchemy untuk PostgreSQL agar kompatibel dengan Pandas.
    """
    db_type = get_db_type()
    db_url = os.getenv("DATABASE_URL")
    
    if db_type == "postgresql":
        # Menghapus bracket literal jika ada di placeholder kata sandi
        if "[" in db_url and "]" in db_url:
            db_url = db_url.replace("[", "").replace("]", "")
        
        from sqlalchemy import create_engine
        try:
            engine = create_engine(db_url)
            df = pd.read_sql_query("SELECT * FROM log_cuitan ORDER BY date DESC", engine)
            return df
        except Exception as e:
            print(f"[ERROR] Gagal memuat data dari PostgreSQL via SQLAlchemy: {e}")
            return pd.DataFrame()
    else:
        if not os.path.exists(DB_FILE):
            return pd.DataFrame()
        try:
            conn = sqlite3.connect(DB_FILE)
            df = pd.read_sql_query("SELECT * FROM log_cuitan ORDER BY date DESC", conn)
            conn.close()
            return df
        except Exception as e:
            print(f"[ERROR] Gagal memuat data dari SQLite: {e}")
            return pd.DataFrame()

def ambil_cuitan_mentah():
    """
    Mengambil tweet mentah (status = 'RAW') dari database untuk diproses di pipeline AI.
    """
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT tweet_id, raw_text FROM log_cuitan WHERE status = 'RAW'")
        rows = cursor.fetchall()
        return rows
    except Exception as e:
        print(f"[ERROR] Gagal mengambil data cuitan mentah: {e}")
        return []
    finally:
        conn.close()

def perbarui_cuitan_setelah_proses(tweet_id, cleaned_text, sentiment_label, confidence_score):
    """
    Memperbarui baris data cuitan setelah dibersihkan oleh Gemini dan diprediksi oleh SVM.
    """
    conn = get_connection()
    cursor = conn.cursor()
    placeholder = get_placeholder()
    
    try:
        if sentiment_label:
            query = f'''
                UPDATE log_cuitan
                SET cleaned_text = {placeholder}, sentiment_label = {placeholder}, confidence_score = {placeholder}, status = 'CLEANED'
                WHERE tweet_id = {placeholder}
            '''
            cursor.execute(query, (cleaned_text, sentiment_label, confidence_score, tweet_id))
        else:
            query = f'''
                UPDATE log_cuitan
                SET cleaned_text = {placeholder}, status = 'CLEANED'
                WHERE tweet_id = {placeholder}
            '''
            cursor.execute(query, (cleaned_text, tweet_id))
        conn.commit()
    except Exception as e:
        print(f"[ERROR] Gagal memperbarui status data cuitan {tweet_id}: {e}")
    finally:
        conn.close()
