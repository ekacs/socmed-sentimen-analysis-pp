import os
import sqlite3
import pandas as pd
from dotenv import load_dotenv

# Memuat file .env — override=False agar env var sistem (GitHub Actions) tidak tertimpa
load_dotenv(override=False)

DB_FILE = 'sentimen_kebijakan.db'

def get_db_type(db_url=None):
    """
    Menentukan tipe database yang digunakan berdasarkan ketersediaan DATABASE_URL.
    """
    if not db_url:
        db_url = os.getenv("DATABASE_URL", "")
    if db_url and ("postgresql://" in db_url or "postgres://" in db_url) and "YOUR_DATABASE_URL" not in db_url:
        return "postgresql"
    return "sqlite"

def get_connection(db_url=None):
    """
    Mendapatkan koneksi database yang sesuai (sqlite3 atau psycopg2).
    """
    if not db_url:
        db_url = os.getenv("DATABASE_URL", "")
    db_type = get_db_type(db_url)
    
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

def get_placeholder(db_url=None):
    """
    Mendapatkan string placeholder parameter SQL yang sesuai (? untuk SQLite, %s untuk PostgreSQL).
    """
    return "%s" if get_db_type(db_url) == "postgresql" else "?"

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

        # Skema tabel keysearch_history
        db_type = get_db_type()
        if db_type == "postgresql":
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS keysearch_history (
                    id SERIAL PRIMARY KEY,
                    keywords TEXT,
                    profiles TEXT,
                    hashtags TEXT,
                    created_at TEXT NOT NULL
                )
            ''')
        else:
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS keysearch_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    keywords TEXT,
                    profiles TEXT,
                    hashtags TEXT,
                    created_at TEXT NOT NULL
                )
            ''')

        # Auto-migrasi jika tabel log_cuitan lama (v1) masih menggunakan tweet_id
        db_type = get_db_type()
        try:
            if db_type == "postgresql":
                cursor.execute("""
                    SELECT column_name 
                    FROM information_schema.columns 
                    WHERE table_name='log_cuitan';
                """)
                columns = [row[0] for row in cursor.fetchall()]
                if columns:
                    if 'tweet_id' in columns and 'platform_id' not in columns:
                        cursor.execute("ALTER TABLE log_cuitan RENAME COLUMN tweet_id TO platform_id;")
                    if 'views' not in columns:
                        cursor.execute("ALTER TABLE log_cuitan ADD COLUMN views INTEGER DEFAULT 0;")
                    if 'log_activity' not in columns:
                        cursor.execute("ALTER TABLE log_cuitan ADD COLUMN log_activity TEXT;")
                    if 'user_app' not in columns:
                        cursor.execute("ALTER TABLE log_cuitan ADD COLUMN user_app TEXT;")
            else:
                cursor.execute("PRAGMA table_info(log_cuitan);")
                columns = [row[1] for row in cursor.fetchall()]
                if columns:
                    if 'tweet_id' in columns and 'platform_id' not in columns:
                        cursor.execute("ALTER TABLE log_cuitan RENAME COLUMN tweet_id TO platform_id;")
                    if 'views' not in columns:
                        cursor.execute("ALTER TABLE log_cuitan ADD COLUMN views INTEGER DEFAULT 0;")
                    if 'log_activity' not in columns:
                        cursor.execute("ALTER TABLE log_cuitan ADD COLUMN log_activity TEXT;")
                    if 'user_app' not in columns:
                        cursor.execute("ALTER TABLE log_cuitan ADD COLUMN user_app TEXT;")
        except Exception as mig_err:
            print(f"[WARNING] Migrasi skema otomatis log_cuitan: {mig_err}")
        
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
        print(f"[SUCCESS] {len(data_cuitan)} data diproses. Penyisipan ke {db_type} selesai.")
    except Exception as e:
        print(f"[ERROR] Kesalahan saat menyisipkan data ke database: {e}")
    finally:
        conn.close()
        
    # Otomatis jalankan pembersihan duplikasi (username + raw_text sama, pertahankan date paling muda)
    try:
        deleted_dups = hapus_duplikasi_data_raw()
        if deleted_dups > 0:
            print(f"[INFO] Deduplikasi Tahapan 1: {deleted_dups} data duplikat (username & raw_text sama) dibersihkan, mempertahankan data tanggal paling muda.")
    except Exception as _ex:
        print(f"[WARNING] Gagal otomatis deduplikasi setelah simpan: {_ex}")

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

def perbarui_cuitan_batch(batch_updates):
    """
    Ultra-fast Bulk Update: Memperbarui sekumpulan baris cuitan sekaligus dalam 1 koneksi & transaksi SQL.
    batch_updates: list of tuple (cleaned_text, sentiment_label, confidence_score, platform_id)
    """
    if not batch_updates:
        return
    conn = get_connection()
    cursor = conn.cursor()
    ph = get_placeholder()
    
    updates_with_sent = [(c, s, float(score), pid) for c, s, score, pid in batch_updates if s is not None]
    updates_no_sent = [(c, pid) for c, s, score, pid in batch_updates if s is None]
    
    try:
        if updates_with_sent:
            query1 = f'''
                UPDATE log_cuitan
                SET cleaned_text = {ph}, sentiment_label = {ph}, confidence_score = {ph}, status = 'CLEANED'
                WHERE platform_id = {ph}
            '''
            cursor.executemany(query1, updates_with_sent)
            
        if updates_no_sent:
            query2 = f'''
                UPDATE log_cuitan
                SET cleaned_text = {ph}, status = 'CLEANED'
                WHERE platform_id = {ph}
            '''
            cursor.executemany(query2, updates_no_sent)
            
        conn.commit()
    except Exception as e:
        print(f"[ERROR] Gagal update batch ke database: {e}")
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

def hitung_total_baris():
    """
    Menghitung total baris yang ada di tabel log_cuitan.
    """
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT COUNT(*) FROM log_cuitan")
        row = cursor.fetchone()
        return row[0] if row else 0
    except Exception as e:
        print(f"[ERROR] Gagal menghitung total baris log_cuitan: {e}")
        return 0
    finally:
        conn.close()

def hapus_duplikasi_data_raw():
    """
    Menghapus data duplikat jika terdapat kesamaan (username + raw_text + date).
    Aturan Prioritas Yang Dipertahankan:
    1. Dipertahankan baris dengan total engagement (likes + retweets + views) PALING TINGGI.
    2. Jika engagement sama semua, dipertahankan urutan TERAKHIR yang masuk scraping.
    Return: jumlah baris yang dihapus.
    """
    conn = get_connection()
    cursor = conn.cursor()
    deleted_count = 0
    placeholder = get_placeholder()
    try:
        # Cari grup (username, raw_text, date) yang memiliki duplikat
        cursor.execute("""
            SELECT username, raw_text, date, COUNT(*) 
            FROM log_cuitan 
            GROUP BY username, raw_text, date 
            HAVING COUNT(*) > 1
        """)
        dup_groups = cursor.fetchall()
        
        for username, raw_text, date_val, _ in dup_groups:
            # Urutkan berdasarkan total engagement DESC, lalu platform_id DESC (penyisipan terakhir)
            query_get = f"""
                SELECT platform_id, 
                       (COALESCE(likes, 0) + COALESCE(retweets, 0) + COALESCE(views, 0)) AS total_eng
                FROM log_cuitan 
                WHERE username = {placeholder} AND raw_text = {placeholder} AND date = {placeholder}
                ORDER BY total_eng DESC, platform_id DESC
            """
            cursor.execute(query_get, (username, raw_text, date_val))
            rows = cursor.fetchall()
            if len(rows) > 1:
                # rows[0] adalah data dengan engagement tertinggi / urutan penyisipan terakhir yang DIPERTAHANKAN
                ids_to_delete = [r[0] for r in rows[1:]]
                for del_id in ids_to_delete:
                    cursor.execute(f"DELETE FROM log_cuitan WHERE platform_id = {placeholder}", (del_id,))
                    deleted_count += 1
                    
        conn.commit()
        if deleted_count > 0:
            print(f"[INFO] Deduplikasi data: berhasil menghapus {deleted_count} data duplikat (kesamaan username, text, date).")
        return deleted_count
    except Exception as e:
        print(f"[ERROR] Gagal menghapus duplikasi data: {e}")
        return 0
    finally:
        conn.close()

def simpan_keysearch_history(keywords, profiles, hashtags):
    """
    Menyimpan kombinasi pencarian kata kunci, profil, dan hashtag ke riwayat.
    """
    if not (keywords or profiles or hashtags):
        return
    conn = get_connection()
    cursor = conn.cursor()
    placeholder = get_placeholder()
    created_at = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        kw_str = ", ".join(keywords) if isinstance(keywords, list) else str(keywords or "")
        pr_str = ", ".join(profiles) if isinstance(profiles, list) else str(profiles or "")
        ht_str = ", ".join(hashtags) if isinstance(hashtags, list) else str(hashtags or "")
        
        cursor.execute(f"""
            SELECT COUNT(*) FROM keysearch_history 
            WHERE keywords = {placeholder} AND profiles = {placeholder} AND hashtags = {placeholder}
        """, (kw_str, pr_str, ht_str))
        if cursor.fetchone()[0] == 0:
            cursor.execute(f"""
                INSERT INTO keysearch_history (keywords, profiles, hashtags, created_at)
                VALUES ({placeholder}, {placeholder}, {placeholder}, {placeholder})
            """, (kw_str, pr_str, ht_str, created_at))
            conn.commit()
    except Exception as e:
        print(f"[ERROR] Gagal menyimpan keysearch_history: {e}")
    finally:
        conn.close()

def ambil_keysearch_history():
    """
    Mengambil seluruh riwayat keysearch untuk dropdown di UI.
    Return: list of dict {'id', 'keywords', 'profiles', 'hashtags', 'display_label'}
    """
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id, keywords, profiles, hashtags, created_at FROM keysearch_history ORDER BY id DESC")
        rows = cursor.fetchall()
        result = []
        for r in rows:
            kw, pr, ht = r[1] or "", r[2] or "", r[3] or ""
            parts = []
            if kw: parts.append(f"Keyword: {kw}")
            if pr: parts.append(f"Profil: {pr}")
            if ht: parts.append(f"Hashtag: {ht}")
            label = " | ".join(parts) if parts else "Pencarian Umum"
            result.append({
                "id": r[0],
                "keywords": kw,
                "profiles": pr,
                "hashtags": ht,
                "created_at": r[4],
                "display_label": label
            })
        return result
    except Exception as e:
        print(f"[ERROR] Gagal mengambil keysearch_history: {e}")
        return []
    finally:
        conn.close()

def ambil_riwayat_terpisah():
    """
    Mengambil daftar unik riwayat kata kunci, hashtag, dan user profile secara terpisah.
    Returns: dict {'keywords': [...], 'hashtags': [...], 'profiles': [...]}
    """
    conn = get_connection()
    cursor = conn.cursor()
    kw_set, ht_set, pr_set = set(), set(), set()
    try:
        cursor.execute("SELECT keywords, profiles, hashtags FROM keysearch_history ORDER BY id DESC")
        rows = cursor.fetchall()
        for r in rows:
            kw_raw, pr_raw, ht_raw = r[0] or "", r[1] or "", r[2] or ""
            for item in kw_raw.split(","):
                i = item.strip()
                if i: kw_set.add(i)
            for item in ht_raw.split(","):
                i = item.strip()
                if i: ht_set.add(i)
            for item in pr_raw.split(","):
                i = item.strip()
                if i: pr_set.add(i)
        return {
            "keywords": sorted(list(kw_set)),
            "hashtags": sorted(list(ht_set)),
            "profiles": sorted(list(pr_set))
        }
    except Exception as e:
        print(f"[ERROR] Gagal mengambil riwayat terpisah: {e}")
        return {"keywords": [], "hashtags": [], "profiles": []}
    finally:
        conn.close()

