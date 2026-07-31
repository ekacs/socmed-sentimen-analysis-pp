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

def init_session_credentials():
    """Inisialisasi variabel st.session_state untuk kredensial jika belum ada."""
    if KEY_APIFY not in st.session_state:
        st.session_state[KEY_APIFY] = ""
    if KEY_SUPABASE not in st.session_state:
        st.session_state[KEY_SUPABASE] = ""
    if KEY_GEMINI not in st.session_state:
        st.session_state[KEY_GEMINI] = ""

def get_active_apify_token() -> str:
    """Mengembalikan Apify token kustom pengguna jika ada, jika tidak fallback ke .env."""
    custom = st.session_state.get(KEY_APIFY, "").strip() if hasattr(st, "session_state") else ""
    return custom if custom else os.getenv("APIFY_API_TOKEN", "")

def get_active_supabase_url() -> str:
    """Mengembalikan Database URL kustom pengguna jika ada, jika tidak fallback ke .env."""
    custom = st.session_state.get(KEY_SUPABASE, "").strip() if hasattr(st, "session_state") else ""
    return custom if custom else os.getenv("DATABASE_URL", "")

def get_active_gemini_key() -> str:
    """Mengembalikan LLM API Key kustom pengguna jika ada, jika tidak fallback ke .env."""
    custom = st.session_state.get(KEY_GEMINI, "").strip() if hasattr(st, "session_state") else ""
    return custom if custom else os.getenv("GEMINI_API_KEY", "")

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
    supabase_url = get_active_supabase_url()
    
    if apify_tok:
        env_dict["APIFY_API_TOKEN"] = apify_tok
    if gemini_key:
        env_dict["GEMINI_API_KEY"] = gemini_key
    if supabase_url:
        env_dict["DATABASE_URL"] = supabase_url
        
    return env_dict
