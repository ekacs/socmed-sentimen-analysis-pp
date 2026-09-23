"""
session_credentials.py
----------------------
Modul pembantu untuk mengelola API Key & Kredensial berbasis sesi pengguna (Session-Only).
Memungkinkan setiap pengguna memasukkan API Key Apify, Supabase, dan LLM kustom.
Jika pengguna tidak memasukkan API Key (kosong), sistem secara otomatis mengembalikan
kunci default dari variabel lingkungan (.env).
"""

import os
import streamlit as st

KEY_APIFY = "user_apify_api_token"
KEY_SUPABASE = "user_supabase_db_url"
KEY_GEMINI = "user_gemini_api_key"
KEY_GEMINI_MODEL = "user_gemini_model"
KEY_DB_MODE = "user_db_mode"

def init_session_credentials():
    """Inisialisasi variabel st.session_state untuk kredensial jika belum ada."""
    if KEY_APIFY not in st.session_state:
        st.session_state[KEY_APIFY] = ""
    if KEY_SUPABASE not in st.session_state:
        st.session_state[KEY_SUPABASE] = ""
    if KEY_GEMINI not in st.session_state:
        st.session_state[KEY_GEMINI] = ""
    if KEY_GEMINI_MODEL not in st.session_state:
        st.session_state[KEY_GEMINI_MODEL] = os.getenv("GEMINI_MODEL_NAME", "gemini-1.5-flash")
    if KEY_DB_MODE not in st.session_state:
        # Default mode utama aplikasi: Database Lokal (SQLite)
        st.session_state[KEY_DB_MODE] = "sqlite"

def get_active_db_mode() -> str:
    """
    Mengembalikan mode DB aktif ('sqlite' atau 'postgresql').
    Default awal: 'sqlite' (Database Lokal).
    Jika pengguna memilih 'sqlite' atau mode default, gunakan penyimpanan lokal (sqlite).
    Hanya jika pengguna secara eksplisit memilih 'postgresql' dan alamat Supabase terisi/tersedia, gunakan cloud (postgresql).
    """
    if hasattr(st, "session_state"):
        explicit_mode = st.session_state.get(KEY_DB_MODE, "sqlite")
        if explicit_mode == "sqlite":
            return "sqlite"
        if explicit_mode == "postgresql":
            url = get_active_supabase_url()
            return "postgresql" if url else "sqlite"
            
    # Di luar session Streamlit (misal script CLI mandiri), cek env var DB_MODE atau default ke sqlite
    env_db_mode = os.getenv("DB_MODE", "").lower()
    if env_db_mode == "postgresql":
        url = get_active_supabase_url()
        return "postgresql" if url else "sqlite"
    return "sqlite"

def get_active_apify_token() -> str:
    """Mengembalikan Apify token kustom pengguna jika ada, jika tidak fallback ke .env."""
    custom = st.session_state.get(KEY_APIFY, "").strip() if hasattr(st, "session_state") else ""
    return custom if custom else os.getenv("APIFY_API_TOKEN", "")

def get_active_supabase_url() -> str:
    """Mengembalikan Database URL kustom pengguna jika ada, jika tidak fallback ke .env."""
    custom = st.session_state.get(KEY_SUPABASE, "").strip() if hasattr(st, "session_state") else ""
    return custom if custom else os.getenv("DATABASE_URL", "")

def get_active_database_url() -> str:
    """
    Mengembalikan URL koneksi database aktif berdasarkan DB_MODE.
    Jika mode 'sqlite', kembalikan string kosong (menggunakan SQLite file lokal).
    Jika mode 'postgresql', kembalikan Database URL aktif.
    """
    mode = get_active_db_mode()
    if mode == "sqlite":
        return ""
    return get_active_supabase_url()

def get_active_gemini_key() -> str:
    """Mengembalikan LLM API Key kustom pengguna jika ada, jika tidak fallback ke .env."""
    custom = st.session_state.get(KEY_GEMINI, "").strip() if hasattr(st, "session_state") else ""
    return custom if custom else os.getenv("GEMINI_API_KEY", "")

_AUTO_MODEL_CACHE = {}

def auto_detect_gemini_model(api_key: str = None) -> str:
    """
    Mendeteksi secara otomatis varian model Gemini terbaik yang didukung oleh API key pengguna.
    Pengguna tidak perlu menentukan nama model secara manual.
    """
    if not api_key:
        api_key = get_active_gemini_key()
    if not api_key:
        return os.getenv("GEMINI_MODEL_NAME", "gemini-3.6-flash")

    cache_key = api_key.strip()
    if cache_key in _AUTO_MODEL_CACHE:
        return _AUTO_MODEL_CACHE[cache_key]

    try:
        from google import genai
        client = genai.Client(api_key=api_key)
        available = []
        for m in client.models.list():
            if hasattr(m, 'name') and m.name:
                name_clean = m.name.replace('models/', '')
                if 'gemini' in name_clean.lower() and ('flash' in name_clean.lower() or 'pro' in name_clean.lower()):
                    available.append(name_clean)

        # Skema prioritas model Google Gemini dari yang paling mutakhir, stabil, dan cepat
        priority = [
            'gemini-3.6-flash',
            'gemini-3.5-flash',
            'gemini-2.5-flash',
            'gemini-flash-latest',
            'gemini-3.1-flash-lite',
            'gemini-2.5-flash-lite',
            'gemini-1.5-flash',
            'gemini-pro-latest'
        ]

        chosen = None
        for p in priority:
            if p in available:
                chosen = p
                break

        if not chosen:
            # Cari model apa pun yang mengandung 'flash' non-audio/image
            flash_models = [m for m in available if 'flash' in m.lower() and not m.endswith('-tts') and not m.endswith('-image')]
            chosen = flash_models[0] if flash_models else (available[0] if available else 'gemini-3.6-flash')

        _AUTO_MODEL_CACHE[cache_key] = chosen
        return chosen
    except Exception as e:
        print(f"[DEBUG] Gagal mendeteksi model otomatis dari API Key: {e}")
        return os.getenv("GEMINI_MODEL_NAME", "gemini-3.6-flash")

def get_active_gemini_model() -> str:
    """
    Mengembalikan nama model Gemini aktif. 
    Sistem secara otomatis mendeteksi model resmi terbaik yang didukung oleh API Key pengguna,
    sehingga pengguna cukup memasukkan API Key tanpa perlu memikirkan penamaan model.
    """
    # Jika pengguna atau environment memiliki setting eksplisit, gunakan
    env_m = os.getenv("GEMINI_MODEL_NAME", "").strip()
    key = get_active_gemini_key()
    if key:
        return auto_detect_gemini_model(key)
    return env_m if env_m else "gemini-3.6-flash"

def fetch_available_gemini_models(api_key: str = None) -> list:
    """
    Mengambil daftar model Gemini yang secara aktif didukung oleh API Key pengguna langsung dari server Google GenAI API.
    """
    if not api_key:
        api_key = get_active_gemini_key()
    if not api_key:
        return []
    try:
        from google import genai
        client = genai.Client(api_key=api_key)
        models = []
        for m in client.models.list():
            if hasattr(m, 'name') and m.name:
                name_clean = m.name.replace('models/', '')
                if 'gemini' in name_clean.lower():
                    models.append(name_clean)
        return models
    except Exception as e:
        print(f"[DEBUG] Gagal mengambil daftar model dari Google API: {e}")
        return []

def is_custom_gemini() -> bool:
    """Memeriksa apakah pengguna menginput LLM API Key kustom di sesi UI."""
    custom = st.session_state.get(KEY_GEMINI, "").strip() if hasattr(st, "session_state") else ""
    return bool(custom)

def is_custom_apify() -> bool:
    """Memeriksa apakah pengguna menginput Apify Token kustom di sesi UI."""
    custom = st.session_state.get(KEY_APIFY, "").strip() if hasattr(st, "session_state") else ""
    return bool(custom)

def is_custom_supabase() -> bool:
    """Memeriksa apakah pengguna menginput Database URL Supabase kustom di sesi UI."""
    custom = st.session_state.get(KEY_SUPABASE, "").strip() if hasattr(st, "session_state") else ""
    return bool(custom)

def mask_credential(val: str, visible_suffix_len: int = 4) -> str:
    """
    Menyamarkan nilai kredensial dengan karakter asterisk.
    Contoh: 'apify_api_123456789' -> '************6789'
    Jika string pendek atau kosong, kembalikan '*' sejumlah karakter.
    """
    if not val:
        return ""
    val_clean = val.strip()
    if len(val_clean) <= visible_suffix_len:
        return "*" * len(val_clean)
    masked_part = "*" * (len(val_clean) - visible_suffix_len)
    suffix_part = val_clean[-visible_suffix_len:]
    return f"{masked_part}{suffix_part}"

def get_session_env_dict() -> dict:
    """
    Menghasilkan dictionary environment bertipe string untuk disuntikkan
    ke subprocess.run([sys.executable, ...], env=env).
    """
    env_dict = os.environ.copy()
    apify_tok = get_active_apify_token()
    gemini_key = get_active_gemini_key()
    active_db_url = get_active_database_url()
    
    if apify_tok:
        env_dict["APIFY_API_TOKEN"] = apify_tok
    if gemini_key:
        env_dict["GEMINI_API_KEY"] = gemini_key
    env_dict["GEMINI_MODEL_NAME"] = get_active_gemini_model()
    # Set DATABASE_URL sesuai mode aktif (kosong untuk SQLite, postgresql://... untuk Cloud DB)
    env_dict["DATABASE_URL"] = active_db_url
    env_dict["PYTHONUNBUFFERED"] = "1"
    env_dict["PYTHONIOENCODING"] = "utf-8"
    env_dict["PYTHONUTF8"] = "1"
        
    return env_dict

def save_credentials_to_env(apify_tok: str = None, gemini_key: str = None, supabase_url: str = None, gemini_model: str = None, env_path: str = ".env"):
    """
    Memperbarui file .env secara persisten dengan kredensial baru.
    """
    env_vars = {}
    if os.path.exists(env_path):
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line_clean = line.strip()
                    if line_clean and not line_clean.startswith("#") and "=" in line_clean:
                        k, v = line_clean.split("=", 1)
                        env_vars[k.strip()] = v.strip().strip('"\'')
        except Exception:
            pass

    if apify_tok is not None:
        val = apify_tok.strip()
        env_vars["APIFY_API_TOKEN"] = val
        os.environ["APIFY_API_TOKEN"] = val
    if gemini_key is not None:
        val = gemini_key.strip()
        env_vars["GEMINI_API_KEY"] = val
        os.environ["GEMINI_API_KEY"] = val
    if gemini_model is not None:
        val = gemini_model.strip()
        env_vars["GEMINI_MODEL_NAME"] = val
        os.environ["GEMINI_MODEL_NAME"] = val
    if supabase_url is not None:
        val = supabase_url.strip()
        env_vars["DATABASE_URL"] = val
        os.environ["DATABASE_URL"] = val

    lines = []
    for k, v in env_vars.items():
        if v:
            lines.append(f'{k}="{v}"\n')
        else:
            lines.append(f'{k}=\n')
    
    try:
        with open(env_path, "w", encoding="utf-8") as f:
            f.writelines(lines)
    except Exception as e:
        print(f"[WARNING] Gagal menulis ke berkas {env_path}: {e}")

