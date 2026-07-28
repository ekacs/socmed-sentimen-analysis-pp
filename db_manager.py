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
    if db_url and ("postgresql://" in db_url or "postgres://" in db_url) and "YOUR_DATABASE_URL" not in db_url:
        return "postgresql"
    return "sqlite"

def get_connection():
    """
    Mendapatkan koneksi database yang sesuai (sqlite3 atau psycopg2).
    """
    db_type = get_db_type()
    db_url = os.getenv("DATABASE_URL", "")
    
    if db_type == "postgresql":
        import psycopg2
        # Menghapus bracket literal jika ada di placeholder kata sandi
        if "[" in db_url and "]" in db_url:
            db_url = db_url.replace("[", "").replace("]", "")
        if db_url.startswith("postgres://"):
            db_url = "postgresql://" + db_url[len("postgres://"):]
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
    Membuat skema tabel 'log_cuitan' dan 'system_config' yang kompatibel dengan SQLite dan PostgreSQL.
    Skema terbaru (v2): mengganti tweet_id → platform_id, menambah views, log_activity, user_app.
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        # Skema tabel log_cuitan (versi 2)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS log_cuitan (
                platform_id TEXT PRIMARY KEY,           -- ID unik konten dari platform sumber (pengganti tweet_id lama)
                date TEXT NOT NULL,                     -- Tanggal pembuatan konten (dari created_at platform)
                username TEXT NOT NULL,                 -- Nama akun pembuat konten (screen_name untuk Twitter)
                raw_text TEXT NOT NULL,                 -- Teks mentah asli dari platform
                cleaned_text TEXT,                      -- Teks hasil standardisasi EYD oleh Gemini API
                sentiment_label TEXT,                   -- Hasil klasifikasi: 'Positif', 'Negatif', atau 'Netral'
                confidence_score REAL,                  -- Tingkat akurasi/keyakinan model klasifikasi (0.0 - 1.0)
                likes INTEGER DEFAULT 0,                -- Jumlah suka/reaksi
                retweets INTEGER DEFAULT 0,             -- Jumlah bagikan/repost
                views INTEGER DEFAULT 0,                -- Jumlah tayangan konten (tersedia di Twitter/X)
                status TEXT DEFAULT 'RAW',              -- Status pemrosesan data ('RAW' / 'CLEANED')
                source_platform TEXT NOT NULL,          -- Keterangan sumber: 'Twitter / X', 'Instagram', 'LinkedIn', 'News'
                log_activity TEXT,                      -- Timestamp aktivitas scraping (format: DD-MMMM-YYYY HH:MM:SS)
                user_app TEXT                           -- Username pengguna aplikasi Streamlit yang memicu scraping
            )
        ''')
        
        # Skema tabel system_config
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS system_config (
                config_key TEXT PRIMARY KEY,
                config_value TEXT NOT NULL
            )
        ''')
        
        # Cek dan seed nilai default jika kosong
        cursor.execute("SELECT COUNT(*) FROM system_config WHERE config_key = 'scraping_mode'")
        if cursor.fetchone()[0] == 0:
            cursor.execute("INSERT INTO system_config (config_key, config_value) VALUES ('scraping_mode', 'auto')")
            
        conn.commit()
        print(f"[OK] Basis data ({get_db_type()}) dan tabel-tabel sistem berhasil diselaraskan!")
    except Exception as e:
        print(f"[ERROR] Gagal menyelaraskan tabel: {e}")
    finally:
        conn.close()

def simpan_data_ke_db(data_cuitan):
    """
    Menyimpan data cuitan ke database menggunakan pendekatan UPSERT yang disesuaikan
    dengan tipe database aktif (ON CONFLICT untuk PostgreSQL, INSERT OR IGNORE untuk SQLite).
    Menggunakan skema v2: platform_id sebagai primary key, dengan field views, log_activity, user_app.
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
                    platform_id, date, username, raw_text, cleaned_text, 
                    sentiment_label, confidence_score, likes, retweets, views,
                    status, source_platform, log_activity, user_app
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (platform_id) DO NOTHING
            '''
        else:
            query = '''
                INSERT OR IGNORE INTO log_cuitan (
                    platform_id, date, username, raw_text, cleaned_text, 
                    sentiment_label, confidence_score, likes, retweets, views,
                    status, source_platform, log_activity, user_app
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            '''
            
        data_tuple = [
            (
                d['platform_id'], 
                d['date'], 
                d['username'], 
                d['raw_text'], 
                d.get('cleaned_text', None), 
                d.get('sentiment_label', None), 
                d.get('confidence_score', 0.0),
                d.get('likes', 0),
                d.get('retweets', 0),
                d.get('views', 0),
                d.get('status', 'RAW'),
                d.get('source_platform', 'Twitter / X'),
                d.get('log_activity', None),
                d.get('user_app', None)
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
    Menggunakan SQLAlchemy untuk PostgreSQL agar kompatibel dengan Pandas,
    dengan fallback otomatis ke SQLite jika PostgreSQL tidak mengembalikan data / terkendala.
    """
    db_type = get_db_type()
    db_url = os.getenv("DATABASE_URL", "")
    df = pd.DataFrame()
    
    if db_type == "postgresql" and db_url:
        if "[" in db_url and "]" in db_url:
            db_url = db_url.replace("[", "").replace("]", "")
        
        sqlalchemy_url = db_url
        if sqlalchemy_url.startswith("postgres://"):
            sqlalchemy_url = "postgresql://" + sqlalchemy_url[len("postgres://"):]
            
        from sqlalchemy import create_engine
        try:
            engine = create_engine(sqlalchemy_url)
            df = pd.read_sql_query("SELECT * FROM log_cuitan ORDER BY date DESC", engine)
            if not df.empty:
                return df
            print("[INFO] PostgreSQL Supabase terhubung tetapi belum memiliki data (0 baris). Memeriksa SQLite lokal...")
        except Exception as e:
            print(f"[ERROR] Gagal memuat data dari PostgreSQL via SQLAlchemy: {e}")

    if os.path.exists(DB_FILE):
        try:
            conn = sqlite3.connect(DB_FILE)
            df_sqlite = pd.read_sql_query("SELECT * FROM log_cuitan ORDER BY date DESC", conn)
            conn.close()
            if not df_sqlite.empty:
                print(f"[INFO] Menggunakan data dari SQLite lokal ({len(df_sqlite)} baris).")
                return df_sqlite
        except Exception as e:
            print(f"[ERROR] Gagal memuat data dari SQLite: {e}")
            
    return df

def ambil_cuitan_mentah():
    """
    Mengambil konten mentah (status = 'RAW') dari database untuk diproses di pipeline AI.
    Mengembalikan (platform_id, raw_text) untuk setiap baris RAW.
    """
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT platform_id, raw_text FROM log_cuitan WHERE status = 'RAW'")
        rows = cursor.fetchall()
        return rows
    except Exception as e:
        print(f"[ERROR] Gagal mengambil data cuitan mentah: {e}")
        return []
    finally:
        conn.close()

def perbarui_cuitan_setelah_proses(platform_id, cleaned_text, sentiment_label, confidence_score):
    """
    Memperbarui baris data cuitan setelah dibersihkan oleh Gemini dan diprediksi oleh SVM.
    Menggunakan platform_id sebagai identifier (pengganti tweet_id lama).
    """
    conn = get_connection()
    cursor = conn.cursor()
    placeholder = get_placeholder()
    
    try:
        if sentiment_label:
            query = f'''
                UPDATE log_cuitan
                SET cleaned_text = {placeholder}, sentiment_label = {placeholder}, confidence_score = {placeholder}, status = 'CLEANED'
                WHERE platform_id = {placeholder}
            '''
            cursor.execute(query, (cleaned_text, sentiment_label, confidence_score, platform_id))
        else:
            query = f'''
                UPDATE log_cuitan
                SET cleaned_text = {placeholder}, status = 'CLEANED'
                WHERE platform_id = {placeholder}
            '''
            cursor.execute(query, (cleaned_text, platform_id))
        conn.commit()
    except Exception as e:
        print(f"[ERROR] Gagal memperbarui status data cuitan {platform_id}: {e}")
    finally:
        conn.close()

def get_scraping_mode():
    """
    Mengambil mode penarikan data ('auto' atau 'manual') dari tabel system_config.
    Default-nya adalah 'auto'.
    """
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT config_value FROM system_config WHERE config_key = 'scraping_mode'")
        row = cursor.fetchone()
        if row:
            return row[0]
        else:
            return 'auto'
    except Exception as e:
        print(f"[ERROR] Gagal mengambil scraping mode: {e}")
        return 'auto'
    finally:
        conn.close()

def set_scraping_mode(mode):
    """
    Memperbarui mode penarikan data ('auto' atau 'manual') ke tabel system_config.
    """
    if mode not in ['auto', 'manual']:
        raise ValueError("Mode harus berupa 'auto' atau 'manual'")
        
    conn = get_connection()
    cursor = conn.cursor()
    placeholder = get_placeholder()
    try:
        cursor.execute("SELECT COUNT(*) FROM system_config WHERE config_key = 'scraping_mode'")
        if cursor.fetchone()[0] == 0:
            cursor.execute(f"INSERT INTO system_config (config_key, config_value) VALUES ('scraping_mode', {placeholder})", (mode,))
        else:
            cursor.execute(f"UPDATE system_config SET config_value = {placeholder} WHERE config_key = 'scraping_mode'", (mode,))
        conn.commit()
        print(f"[OK] Mode scraping diperbarui ke: {mode}")
    except Exception as e:
        print(f"[ERROR] Gagal memperbarui scraping mode: {e}")
    finally:
        conn.close()
