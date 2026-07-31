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

        # Skema tabel keysearch_history (v3 - unified search_term UNIQUE)
        db_type = get_db_type()
        if db_type == "postgresql":
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS keysearch_history (
                    id SERIAL PRIMARY KEY,
                    search_term TEXT UNIQUE NOT NULL,
                    created_at TEXT NOT NULL
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS keysearch_bookmarks (
                    id SERIAL PRIMARY KEY,
                    bookmark_name TEXT UNIQUE NOT NULL,
                    terms TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
            ''')
        else:
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS keysearch_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    search_term TEXT UNIQUE NOT NULL,
                    created_at TEXT NOT NULL
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS keysearch_bookmarks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    bookmark_name TEXT UNIQUE NOT NULL,
                    terms TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
            ''')

        # Auto-migrasi jika tabel log_cuitan / keysearch_history lama perlu diselaraskan
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
                        
                cursor.execute("""
                    SELECT column_name 
                    FROM information_schema.columns 
                    WHERE table_name='keysearch_history';
                """)
                kh_cols = [row[0] for row in cursor.fetchall()]
                if kh_cols and 'search_term' not in kh_cols:
                    cursor.execute("ALTER TABLE keysearch_history ADD COLUMN search_term TEXT;")
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

                cursor.execute("PRAGMA table_info(keysearch_history);")
                kh_cols = [row[1] for row in cursor.fetchall()]
                if kh_cols and 'search_term' not in kh_cols:
                    cursor.execute("ALTER TABLE keysearch_history ADD COLUMN search_term TEXT;")
        except Exception as mig_err:
            print(f"[WARNING] Migrasi skema otomatis log_cuitan / keysearch_history: {mig_err}")
        
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

def set_system_config_flag(key: str, is_active: bool = True, db_url=None):
    """
    Menyimpan atau memperbarui status flag pada tabel system_config.
    """
    try:
        conn = get_connection(db_url)
        cursor = conn.cursor()
        val = "TRUE" if is_active else "FALSE"
        db_type = get_db_type(db_url)
        if db_type == "postgresql":
            query = """
                INSERT INTO system_config (config_key, config_value)
                VALUES (%s, %s)
                ON CONFLICT (config_key) DO UPDATE SET config_value = EXCLUDED.config_value
            """
            cursor.execute(query, (key, val))
        else:
            query = """
                INSERT OR REPLACE INTO system_config (config_key, config_value)
                VALUES (?, ?)
            """
            cursor.execute(query, (key, val))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[WARNING] Gagal memperbarui status system_config '{key}': {e}")

def get_system_config_flag(key: str, db_url=None) -> bool:
    """
    Mengecek apakah status flag pada system_config bernilai 'TRUE'.
    """
    try:
        conn = get_connection(db_url)
        cursor = conn.cursor()
        ph = get_placeholder(db_url)
        cursor.execute(f"SELECT config_value FROM system_config WHERE config_key = {ph}", (key,))
        row = cursor.fetchone()
        conn.close()
        if row and row[0] and row[0].upper() == "TRUE":
            return True
    except Exception as e:
        print(f"[WARNING] Gagal mengecek status system_config '{key}': {e}")
    return False

def set_storage_full_flag(is_full: bool = True, db_url=None):
    set_system_config_flag('DB_STORAGE_FULL', is_full, db_url)

def is_storage_full(db_url=None) -> bool:
    return get_system_config_flag('DB_STORAGE_FULL', db_url)

def simpan_keysearch_history(keywords=None, profiles=None, hashtags=None, terms=None):
    """
    Menyimpan riwayat istilah pencarian unik ke tabel keysearch_history.
    Mendukung input tunggal/list terms atau masukan keywords, profiles, hashtags.
    """
    raw_inputs = []
    for arg in [keywords, profiles, hashtags, terms]:
        if arg:
            if isinstance(arg, list):
                raw_inputs.extend(arg)
            else:
                raw_inputs.append(str(arg))
                
    cleaned_terms = []
    seen = set()
    for item in raw_inputs:
        if not item:
            continue
        for sub_item in str(item).split(","):
            s_clean = sub_item.strip()
            if s_clean and s_clean != "ALL (Semua Data)" and s_clean.lower() not in seen:
                seen.add(s_clean.lower())
                cleaned_terms.append(s_clean)
                
    if not cleaned_terms:
        return
        
    conn = get_connection()
    cursor = conn.cursor()
    placeholder = get_placeholder()
    db_type = get_db_type()
    created_at = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")
    
    try:
        for t in cleaned_terms:
            if db_type == "postgresql":
                query = f"""
                    INSERT INTO keysearch_history (search_term, created_at)
                    VALUES ({placeholder}, {placeholder})
                    ON CONFLICT (search_term) DO NOTHING
                """
                cursor.execute(query, (t, created_at))
            else:
                query = f"""
                    INSERT OR IGNORE INTO keysearch_history (search_term, created_at)
                    VALUES ({placeholder}, {placeholder})
                """
                cursor.execute(query, (t, created_at))
        conn.commit()
    except Exception as e:
        print(f"[ERROR] Gagal menyimpan keysearch_history: {e}")
    finally:
        conn.close()

def ambil_riwayat_gabungan():
    """
    Mengambil daftar unik seluruh riwayat istilah pencarian untuk dropdown UI.
    Return: list string unik terurut (misal: ['#IKNNusantara', 'bersih2narkobapolri', 'jokowi', 'mbg'])
    """
    conn = get_connection()
    cursor = conn.cursor()
    term_set = set()
    try:
        # 1. Coba ambil dari kolom search_term
        try:
            cursor.execute("SELECT search_term FROM keysearch_history ORDER BY id DESC")
            rows = cursor.fetchall()
            for r in rows:
                if r[0]:
                    for sub in str(r[0]).split(","):
                        st = sub.strip()
                        if st and st != "ALL (Semua Data)":
                            term_set.add(st)
        except Exception:
            pass

        # 2. Coba fallback dari kolom lama (keywords, profiles, hashtags) jika ada
        try:
            cursor.execute("SELECT keywords, profiles, hashtags FROM keysearch_history ORDER BY id DESC")
            rows = cursor.fetchall()
            for r in rows:
                for cell in [r[0], r[1], r[2]]:
                    if cell and str(cell).strip() not in ["EMPTY", "None", ""]:
                        for sub in str(cell).split(","):
                            st = sub.strip()
                            if st and st != "ALL (Semua Data)":
                                term_set.add(st)
        except Exception:
            pass

        return sorted(list(term_set))
    except Exception as e:
        print(f"[ERROR] Gagal mengambil riwayat gabungan: {e}")
        return []
    finally:
        conn.close()

def ambil_riwayat_terpisah():
    """
    Fungsi kompatibilitas mundur.
    Returns: dict {'unified': [...], 'keywords': [...], 'hashtags': [...], 'profiles': [...]}
    """
    unified = ambil_riwayat_gabungan()
    return {
        "unified": unified,
        "keywords": unified,
        "hashtags": unified,
        "profiles": unified
    }

def ambil_keysearch_history():
    """
    Mengambil seluruh riwayat keysearch untuk dropdown di UI.
    Return: list of dict {'id', 'search_term', 'created_at', 'display_label'}
    """
    conn = get_connection()
    cursor = conn.cursor()
    try:
        unified_terms = ambil_riwayat_gabungan()
        result = []
        for idx, term in enumerate(unified_terms, start=1):
            result.append({
                "id": idx,
                "search_term": term,
                "keywords": term,
                "profiles": term,
                "hashtags": term,
                "created_at": "-",
                "display_label": term
            })
        return result
    except Exception as e:
        print(f"[ERROR] Gagal mengambil keysearch_history: {e}")
        return []
    finally:
        conn.close()

def simpan_bookmark(bookmark_name: str, terms: list):
    """
    Menyimpan atau memperbarui bookmark kata kunci ke database.
    terms: list string istilah (misal: ['mbg', 'makan bergizi gratis'])
    Return: (success: bool, message: str)
    """
    if not bookmark_name or not str(bookmark_name).strip():
        return False, "Nama bookmark tidak boleh kosong."
    if not terms:
        return False, "Istilah kata kunci untuk bookmark tidak boleh kosong."

    b_name = str(bookmark_name).strip()
    if not b_name.startswith("📌"):
        b_name = f"📌 {b_name}"

    clean_t_list = []
    seen = set()
    for item in terms:
        s_clean = str(item).strip()
        if s_clean and s_clean != "ALL (Semua Data)" and s_clean.lower() not in seen:
            seen.add(s_clean.lower())
            clean_t_list.append(s_clean)

    if not clean_t_list:
        return False, "Istilah kata kunci tidak valid."

    terms_str = ", ".join(clean_t_list)

    conn = get_connection()
    cursor = conn.cursor()
    placeholder = get_placeholder()
    db_type = get_db_type()
    created_at = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")

    try:
        if db_type == "postgresql":
            query = f"""
                INSERT INTO keysearch_bookmarks (bookmark_name, terms, created_at)
                VALUES ({placeholder}, {placeholder}, {placeholder})
                ON CONFLICT (bookmark_name) DO UPDATE SET
                    terms = EXCLUDED.terms,
                    created_at = EXCLUDED.created_at
            """
            cursor.execute(query, (b_name, terms_str, created_at))
        else:
            query = f"""
                INSERT OR REPLACE INTO keysearch_bookmarks (bookmark_name, terms, created_at)
                VALUES ({placeholder}, {placeholder}, {placeholder})
            """
            cursor.execute(query, (b_name, terms_str, created_at))
        conn.commit()
        return True, f"Bookmark '{b_name}' berhasil disimpan!"
    except Exception as e:
        print(f"[ERROR] Gagal menyimpan bookmark: {e}")
        return False, f"Gagal menyimpan bookmark: {e}"
    finally:
        conn.close()

def hapus_bookmark(bookmark_id_or_name):
    """
    Menghapus bookmark berdasarkan ID atau nama bookmark.
    Return: (success: bool, message: str)
    """
    conn = get_connection()
    cursor = conn.cursor()
    placeholder = get_placeholder()
    try:
        if isinstance(bookmark_id_or_name, int) or str(bookmark_id_or_name).isdigit():
            query = f"DELETE FROM keysearch_bookmarks WHERE id = {placeholder}"
            cursor.execute(query, (int(bookmark_id_or_name),))
        else:
            query = f"DELETE FROM keysearch_bookmarks WHERE bookmark_name = {placeholder}"
            cursor.execute(query, (str(bookmark_id_or_name),))
        conn.commit()
        return True, "Bookmark berhasil dihapus."
    except Exception as e:
        print(f"[ERROR] Gagal menghapus bookmark: {e}")
        return False, f"Gagal menghapus bookmark: {e}"
    finally:
        conn.close()

def ambil_semua_bookmark():
    """
    Mengambil seluruh daftar bookmark dari database.
    Return: list of dict [{'id': 1, 'bookmark_name': '📌 Isu MBG', 'terms': ['mbg', 'makan bergizi gratis'], 'terms_str': 'mbg, makan bergizi gratis'}]
    """
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id, bookmark_name, terms, created_at FROM keysearch_bookmarks ORDER BY id DESC")
        rows = cursor.fetchall()
        result = []
        for r in rows:
            t_list = [t.strip() for t in str(r[2] or "").split(",") if t.strip()]
            result.append({
                "id": r[0],
                "bookmark_name": r[1],
                "terms": t_list,
                "terms_str": r[2] or "",
                "created_at": r[3]
            })
        return result
    except Exception as e:
        print(f"[WARNING] Gagal mengambil keysearch_bookmarks: {e}")
        return []
    finally:
        conn.close()

def import_backup_log_cuitan(file_obj, file_format: str = "csv"):
    """
    Mengimpor data cadangan (backup) tabel log_cuitan dari file CSV, XLSX, atau SQL query.
    Return: (success: bool, imported_count: int, message: str)
    """
    try:
        if file_format == "csv":
            df = pd.read_csv(file_obj)
        elif file_format in ["xlsx", "xls"]:
            df = pd.read_excel(file_obj)
        elif file_format == "sql":
            content = file_obj.read().decode("utf-8") if hasattr(file_obj, "read") else str(file_obj)
            conn = get_connection()
            cursor = conn.cursor()
            # Split SQL statements
            statements = [s.strip() for s in content.split(";") if s.strip()]
            cnt = 0
            for stmt in statements:
                cursor.execute(stmt)
                cnt += 1
            conn.commit()
            conn.close()
            return True, cnt, f"Berhasil mengeksekusi {cnt} perintah SQL backup ke basis data."
        else:
            return False, 0, f"Format file '{file_format}' tidak didukung."

        if df.empty:
            return False, 0, "File cadangan kosong / tidak memiliki baris data."

        _all_cols = [
            'platform_id', 'date', 'username', 'raw_text', 'cleaned_text',
            'sentiment_label', 'confidence_score', 'likes', 'retweets', 'views',
            'status', 'source_platform', 'log_activity', 'user_app'
        ]

        column_map = {
            'tweet_id': 'platform_id',
            'ID Platform': 'platform_id',
            'Username': 'username',
            'Tanggal Pembuatan': 'date',
            'Teks Mentah': 'raw_text',
            'Teks Baku (EYD)': 'cleaned_text',
            'Label Sentimen': 'sentiment_label',
            'Skor Keyakinan': 'confidence_score',
            'Platform': 'source_platform',
            'Likes': 'likes',
            'Retweets': 'retweets',
            'Tayangan': 'views',
            'Log Aktivitas Scraping': 'log_activity',
            'User Aplikasi': 'user_app'
        }
        df.rename(columns=column_map, inplace=True)

        for col in _all_cols:
            if col not in df.columns:
                if col in ['likes', 'retweets', 'views']:
                    df[col] = 0
                elif col == 'status':
                    df[col] = 'RAW'
                elif col == 'source_platform':
                    df[col] = 'Imported'
                else:
                    df[col] = None

        df_to_import = df[_all_cols].copy()
        
        df_to_import['likes'] = df_to_import['likes'].fillna(0).astype(int)
        df_to_import['retweets'] = df_to_import['retweets'].fillna(0).astype(int)
        df_to_import['views'] = df_to_import['views'].fillna(0).astype(int)
        df_to_import['status'] = df_to_import['status'].fillna('RAW')
        df_to_import['source_platform'] = df_to_import['source_platform'].fillna('Imported')

        conn = get_connection()
        cursor = conn.cursor()
        placeholder = get_placeholder()
        db_type = get_db_type()

        records = df_to_import.to_dict(orient='records')
        inserted_count = 0

        for r in records:
            p_id = r.get('platform_id')
            if not p_id or str(p_id).strip() in ['', 'None', 'nan']:
                import hashlib
                raw_t = str(r.get('raw_text') or '')
                u_name = str(r.get('username') or '')
                p_id = f"IMP_{hashlib.md5((raw_t + u_name).encode('utf-8')).hexdigest()}"

            if db_type == "postgresql":
                q = f"""
                    INSERT INTO log_cuitan (
                        platform_id, date, username, raw_text, cleaned_text,
                        sentiment_label, confidence_score, likes, retweets, views,
                        status, source_platform, log_activity, user_app
                    ) VALUES (
                        {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder},
                        {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder},
                        {placeholder}, {placeholder}, {placeholder}, {placeholder}
                    )
                    ON CONFLICT (platform_id) DO UPDATE SET
                        cleaned_text = EXCLUDED.cleaned_text,
                        sentiment_label = EXCLUDED.sentiment_label,
                        confidence_score = EXCLUDED.confidence_score,
                        status = EXCLUDED.status
                """
            else:
                q = f"""
                    INSERT OR REPLACE INTO log_cuitan (
                        platform_id, date, username, raw_text, cleaned_text,
                        sentiment_label, confidence_score, likes, retweets, views,
                        status, source_platform, log_activity, user_app
                    ) VALUES (
                        {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder},
                        {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder},
                        {placeholder}, {placeholder}, {placeholder}, {placeholder}
                    )
                """
            
            cursor.execute(q, (
                str(p_id), str(r.get('date') or ''), str(r.get('username') or ''),
                str(r.get('raw_text') or ''), r.get('cleaned_text'), r.get('sentiment_label'),
                r.get('confidence_score'), int(r.get('likes') or 0), int(r.get('retweets') or 0),
                int(r.get('views') or 0), str(r.get('status') or 'RAW'), str(r.get('source_platform') or 'Imported'),
                r.get('log_activity'), r.get('user_app')
            ))
            inserted_count += 1

        conn.commit()
        conn.close()
        return True, inserted_count, f"Berhasil mengimpor {inserted_count:,} baris data cadangan ke basis data ({db_type})."
    except Exception as e:
        return False, 0, f"Gagal mengimpor file cadangan: {e}"

def set_apify_quota_flag(is_exhausted: bool = True, db_url=None):
    set_system_config_flag('APIFY_QUOTA_EXHAUSTED', is_exhausted, db_url)

def is_apify_quota_exhausted(db_url=None) -> bool:
    return get_system_config_flag('APIFY_QUOTA_EXHAUSTED', db_url)

def set_gemini_quota_flag(is_exhausted: bool = True, db_url=None):
    set_system_config_flag('GEMINI_QUOTA_EXHAUSTED', is_exhausted, db_url)

def is_gemini_quota_exhausted(db_url=None) -> bool:
    return get_system_config_flag('GEMINI_QUOTA_EXHAUSTED', db_url)

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
        # Jika penyisipan data sukses, kembalikan flag storage ke normal
        set_storage_full_flag(False)
    except Exception as e:
        print(f"[ERROR] Kesalahan saat menyisipkan data ke database: {e}")
        # Jika terjadi kegagalan penulisan ke database (misal: storage/disk full/quota exceeded), tandai flag storage full
        set_storage_full_flag(True)
        print("[CRITICAL] Gagal menulis ke database! Status DB_STORAGE_FULL telah diaktifkan.")
        raise e
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

