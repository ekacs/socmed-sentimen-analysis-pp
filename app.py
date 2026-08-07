import os
import re
import sys
import json
import datetime
import subprocess
import collections
from io import BytesIO
from typing import Dict, List, Optional, Tuple

import pandas as pd
import streamlit as st
import plotly.express as px
import db_manager
import session_credentials

# Inisialisasi kredensial berbasis sesi pengguna (Session-Only)
session_credentials.init_session_credentials()

# Inisialisasi tabel database saat aplikasi Streamlit pertama kali dimuat.
try:
    db_manager.buat_tabel()
except Exception as _e:
    pass

# Impor generator NLG
from nlg_generator import generate_executive_summary

# --- Opsional: Library Export PDF (reportlab + matplotlib) & Excel ---
PDF_LIBS_OK = False
PDF_IMPORT_ERROR_MSG = ""
try:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    from matplotlib.ticker import MaxNLocator
    HAS_MATPLOTLIB = True
except Exception as e:
    HAS_MATPLOTLIB = False
    PDF_IMPORT_ERROR_MSG += f"[matplotlib] {e}. "

try:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm, mm
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Image, Table, TableStyle,
        PageBreak, KeepTogether
    )
    from reportlab.pdfbase.pdfmetrics import stringWidth
    HAS_REPORTLAB = True
except Exception as e:
    HAS_REPORTLAB = False
    PDF_IMPORT_ERROR_MSG += f"[reportlab] {e}. "

PDF_LIBS_OK = HAS_MATPLOTLIB and HAS_REPORTLAB

def kill_process_tree(proc_obj):
    """Membunuh seluruh proses dan anak prosesnya (process tree) secara paksa."""
    if not proc_obj:
        return False
    try:
        pid = proc_obj.pid
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True)
        else:
            proc_obj.kill()
        return True
    except Exception as e:
        print(f"[DEBUG] Error killing process: {e}")
        return False

def get_supabase_dashboard_url():
    db_url = session_credentials.get_active_supabase_url()
    match = re.search(r"postgres\.([a-zA-Z0-9\-]+)", db_url)
    if match:
        project_ref = match.group(1)
        return f"https://supabase.com/dashboard/project/{project_ref}/editor"
    return "https://supabase.com/dashboard"

# 1. Konfigurasi Halaman Streamlit
st.set_page_config(
    page_title="Analisis Sentimen Publik berbasis AI (v1.1)",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Styling CSS tambahan agar tabel dan chart saat di-maximize (fullscreen) memenuhi 100% lebar & tinggi layar
st.markdown("""
<style>
div[data-testid="stDataFrame"] {
    width: 100% !important;
}
div[data-testid="stDataFrame"] > div {
    width: 100% !important;
}
.element-container:has(iframe) {
    width: 100% !important;
}
/* Paksa tinggi tabel 100% saat mode Fullscreen/Maximize aktif */
div[data-st-fullscreen="true"] div[data-testid="stDataFrame"],
div[data-st-fullscreen="true"] div[data-testid="stDataFrame"] > div,
div[data-st-fullscreen="true"] div[data-testid="stDataFrame"] [role="grid"] {
    height: 85vh !important;
    max-height: 85vh !important;
}
</style>
""", unsafe_allow_html=True)

DB_FILE = 'sentimen_kebijakan.db'
CONFIG_FILE = 'target_config.json'

# ====================================================================
# [EXPORT PDF] Helper functions
# ====================================================================
def _fig_to_png_bytes(fig, dpi: int = 150) -> BytesIO:
    buf = BytesIO()
    fig.savefig(buf, format='png', dpi=dpi, bbox_inches='tight',
                facecolor='white', edgecolor='none')
    plt.close(fig)
    buf.seek(0)
    return buf

def _chart_pie_sentimen_pdf(pos: int, neu: int, neg: int) -> Optional[BytesIO]:
    if not PDF_LIBS_OK or (pos + neu + neg) <= 0:
        return None
    fig, ax = plt.subplots(figsize=(5, 4))
    labels = ['Positif', 'Netral', 'Negatif']
    sizes = [pos, neu, neg]
    warna = ['#2D6A4F', '#4682B4', '#B00020']
    data_pie = [(l, s, w) for l, s, w in zip(labels, sizes, warna) if s > 0]
    if not data_pie:
        plt.close(fig)
        return None
    labels_p = [x[0] for x in data_pie]
    sizes_p = [x[1] for x in data_pie]
    warna_p = [x[2] for x in data_pie]
    wedges, texts, autotexts = ax.pie(
        sizes_p, labels=labels_p, colors=warna_p, autopct='%1.1f%%',
        startangle=90, pctdistance=0.78,
        wedgeprops=dict(width=0.5, edgecolor='white', linewidth=2)
    )
    for t in texts: t.set_fontsize(10)
    for t in autotexts:
        t.set_fontsize(9); t.set_fontweight('bold'); t.set_color('white')
    total_pie = sum(sizes_p)
    ax.text(0, 0, f'Total: {total_pie:,}\n(Terlabel)', ha='center', va='center',
            fontsize=11, fontweight='bold', color='#333')
    ax.set_title('Distribusi Sentimen Publik (Hasil Review)', fontsize=13, fontweight='bold', pad=15)
    return _fig_to_png_bytes(fig)

def _chart_tren_harian_pdf(df_filtered: pd.DataFrame) -> Optional[BytesIO]:
    if not PDF_LIBS_OK or df_filtered.empty or 'date_parsed' not in df_filtered.columns:
        return None
    df_trend = df_filtered.groupby(['date_parsed', 'sentiment_label']).size().reset_index(name='count')
    if df_trend.empty:
        return None
    fig, ax = plt.subplots(figsize=(7.5, 3.5))
    warna_map = {'Positif': '#2D6A4F', 'Netral': '#4682B4', 'Negatif': '#B00020'}
    for label_sentimen, color in warna_map.items():
        subset = df_trend[df_trend['sentiment_label'] == label_sentimen]
        if not subset.empty:
            ax.plot(pd.to_datetime(subset['date_parsed']), subset['count'],
                    marker='o', markersize=4, linewidth=2, label=label_sentimen, color=color)
    ax.set_title('Tren Sentimen Publik Harian', fontsize=13, fontweight='bold', pad=10)
    ax.set_xlabel('Tanggal'); ax.set_ylabel('Jumlah Konten')
    ax.legend(title='Sentimen'); ax.grid(alpha=0.3, linestyle='--')
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%d-%b'))
    fig.autofmt_xdate(); ax.yaxis.set_major_locator(MaxNLocator(integer=True))
    return _fig_to_png_bytes(fig)

def _chart_platform_pdf(df_filtered: pd.DataFrame) -> Optional[BytesIO]:
    if not PDF_LIBS_OK or df_filtered.empty or 'source_platform' not in df_filtered.columns:
        return None
    df_plat = df_filtered['source_platform'].value_counts().reset_index()
    df_plat.columns = ['platform', 'count']
    if df_plat.empty:
        return None
    fig, ax = plt.subplots(figsize=(7.5, 3))
    bars = ax.barh(df_plat['platform'], df_plat['count'],
                    color=['#1f77b4', '#2ca02c', '#ff7f0e', '#d62728'][:len(df_plat)])
    ax.set_title('Volume Data per Platform Sumber', fontsize=13, fontweight='bold', pad=10)
    ax.set_xlabel('Jumlah Konten')
    for bar in bars:
        w = bar.get_width()
        ax.text(w + max(1, w*0.01), bar.get_y() + bar.get_height()/2,
                f'{int(w):,}', va='center', fontsize=10, fontweight='bold')
    ax.grid(alpha=0.3, axis='x', linestyle='--')
    return _fig_to_png_bytes(fig)

# Injeksi CSS Kustom
st.markdown("""
    <style>
        footer {visibility: hidden;}
        @media (min-width: 768px) {
            [data-testid="collapsedControl"] { display: none !important; }
        }
        html, body, [class*="css"] {
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background-color: var(--background-color);
            color: var(--text-color);
        }
        .metric-card {
            background-color: var(--secondary-background-color);
            border: 1px solid rgba(128, 128, 128, 0.2);
            border-radius: 8px;
            padding: 1.5rem;
            box-shadow: 0 1px 3px rgba(0,0,0,0.02);
            text-align: center;
        }
        .metric-value {
            font-size: 2.2rem;
            font-weight: 700;
            color: var(--text-color);
            margin-bottom: 0.2rem;
        }
        .metric-label {
            font-size: 0.9rem;
            font-weight: 500;
            color: var(--text-color);
            opacity: 0.8;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        .stTabs [data-baseweb="tab-list"] {
            gap: 16px;
        }
        .stTabs [data-baseweb="tab"] {
            height: 50px;
            font-weight: 600;
            font-size: 1rem;
            background-color: transparent;
            border-bottom: 2px solid transparent;
            color: var(--text-color);
            opacity: 0.7;
        }
        .stTabs [aria-selected="true"] {
            opacity: 1 !important;
            border-bottom-color: var(--primary-color) !important;
        }
        .stButton>button {
            border-radius: 6px !important;
            font-weight: 600 !important;
        }
    </style>
""", unsafe_allow_html=True)

# 3. Fungsi Basis Data
def load_data_from_db():
    return db_manager.baca_data_untuk_streamlit()

def check_db_storage_full():
    if session_credentials.get_active_db_mode() == "sqlite" or session_credentials.is_custom_supabase():
        return False
    try:
        if hasattr(db_manager, 'is_storage_full'):
            return db_manager.is_storage_full()
    except Exception as _e:
        pass
    return False

def check_apify_quota_exhausted():
    if session_credentials.is_custom_apify():
        return False
    try:
        if hasattr(db_manager, 'is_apify_quota_exhausted'):
            return db_manager.is_apify_quota_exhausted()
    except Exception as _e:
        pass
    return False

if hasattr(st, "dialog"):
    @st.dialog("🔑 Token API Apify Wajib Diisi!")
    def show_apify_token_required_dialog():
        st.error("❌ **Token API Apify (`APIFY_API_TOKEN`) Belum Dikonfigurasi!**")
        st.warning(
            "Penarikan data dari media sosial & website publik **wajib** menggunakan **API Token Apify** "
            "karena scraping dilakukan melalui Actor cloud Apify."
        )
        st.markdown(
            "**Cara Pengisian Token:**\n"
            "1. Dapatkan Token API gratis/berbayar dari akun Apify Anda: [console.apify.com](https://console.apify.com/account/integrations)\n"
            "2. Buka **Sidebar (Pengaturan Kredensial)** di sebelah kiri.\n"
            "3. Masukkan token Anda pada kolom **🔑 Apify API Token**.\n"
            "4. Klik tombol **💾 Simpan Sesi** atau atur di file `.env` (`APIFY_API_TOKEN=...`)."
        )
        if st.button("👌 Saya Mengerti / Buka Sidebar", type="primary", use_container_width=True):
            st.rerun()
else:
    def show_apify_token_required_dialog():
        pass

def check_gemini_quota_exhausted():
    if session_credentials.is_custom_gemini():
        return False
    try:
        if hasattr(db_manager, 'is_gemini_quota_exhausted'):
            return db_manager.is_gemini_quota_exhausted()
    except Exception as _e:
        pass
    return False


# Set Stopwords Lengkap Bahasa Indonesia & Artefak Web / URL Noise
STOPWORDS_INDONESIA = {
    # Artefak URL & Web Noise
    'https', 'http', 'www', 'com', 'org', 'net', 'co', 'id', 'html', 'htm', 'amp', 't', 'bit', 'ly', 'link', 
    'href', 'url', 'pic', 'twitter', 'instagram', 'linkedin', 'status', 'photo', 'video', 'post', 'posts',
    'rt', 'via', 'user', 'repor', 'admin', 'page', 'pages', 'site', 'click', 'download', 'share',
    # Kata Hubung, Kata Tugas, & Stopwords Indonesia
    'dan', 'di', 'ke', 'dari', 'ini', 'itu', 'yang', 'saya', 'kamu', 'dia', 'kami', 'kita', 'mereka', 
    'adalah', 'ada', 'dengan', 'untuk', 'pada', 'atau', 'juga', 'sudah', 'telah', 'bisa', 'dapat', 'akan', 
    'ingin', 'hari', 'nih', 'dah', 'sangat', 'sekali', 'saja', 'karena', 'tapi', 'namun', 'semua', 'banyak', 
    'tidak', 'gak', 'enggak', 'pun', 'lah', 'kok', 'sih', 'ya', 'aja', 'dgn', 'yg', 'utk', 'klo', 'kalo', 
    'lu', 'gw', 'gua', 'buat', 'bgt', 'pas', 'jadi', 'bila', 'jika', 'oleh', 'maka', 'lagi', 'deh', 'dong', 
    'kan', 'kah', 'apa', 'siapa', 'mana', 'kenapa', 'mengapa', 'bagaimana', 'hal', 'secara', 'harus', 
    'setiap', 'bahkan', 'bukan', 'serta', 'tersebut', 'hanya', 'tahun', 'bikin', 'sama', 'sampai', 'hingga',
    'tentang', 'terhadap', 'menjadi', 'sebagai', 'secara', 'antara', 'seperti', 'selain', 'secara', 'membuat',
    'bisa', 'bahkan', 'berada', 'melalui', 'yaitu', 'yakni', 'sehingga', 'sebab', 'kalian'
}

def clean_and_extract_words(text_list):
    """
    Pembersihan mendalam untuk mengekstrak kata kunci bersih:
    1. Menghapus URL https://... dan http://... secara penuh.
    2. Menghapus karakter khusus, simbol, dan tanda baca.
    3. Eliminasi kata-kata noise URL/Web (https, http, www, com, amp, dsb.) dan Stopwords Bahasa Indonesia.
    4. Mengabaikan kata berbentuk angka murni atau bernilai <= 2 karakter.
    """
    words = []
    for text in text_list:
        if not text or str(text).lower() == 'nan':
            continue
        # 1. Hapus URL lengkap
        clean_t = re.sub(r'https?://\S+|www\.\S+', '', str(text), flags=re.IGNORECASE)
        # 2. Hapus karakter non-alphanumeric (hanya pertahankan huruf & spasi)
        clean_t = re.sub(r'[^a-zA-Z\s]', ' ', clean_t)
        # 3. Tokenisasi kata
        for word in clean_t.lower().split():
            word = word.strip()
            if (
                word 
                and len(word) > 2 
                and not word.isdigit() 
                and word not in STOPWORDS_INDONESIA
            ):
                words.append(word)
    return words

def extract_top_keywords(df, num_words=5):
    if df is None or df.empty:
        return "Tidak ada kata kunci dominan"
        
    text_list = []
    for _, row in df.iterrows():
        val_cleaned = row.get('cleaned_text')
        val_raw = row.get('raw_text')
        if pd.notna(val_cleaned) and val_cleaned is not None:
            text_list.append(str(val_cleaned))
        elif pd.notna(val_raw) and val_raw is not None:
            text_list.append(str(val_raw))
            
    words = clean_and_extract_words(text_list)
    counter = collections.Counter(words)
    top_common = counter.most_common(num_words)
    return ", ".join([f"{w[0]} ({w[1]})" for w in top_common]) if top_common else "Tidak ada kata kunci dominan"

def get_top_keywords_df(df, top_n=10):
    if df is None or df.empty:
        return pd.DataFrame(columns=['Kata Kunci', 'Frekuensi'])
        
    text_list = []
    for _, row in df.iterrows():
        val_cleaned = row.get('cleaned_text')
        val_raw = row.get('raw_text')
        if pd.notna(val_cleaned) and val_cleaned is not None:
            text_list.append(str(val_cleaned))
        elif pd.notna(val_raw) and val_raw is not None:
            text_list.append(str(val_raw))
            
    words = clean_and_extract_words(text_list)
    counter = collections.Counter(words)
    top_common = counter.most_common(top_n)
    if not top_common:
        return pd.DataFrame(columns=['Kata Kunci', 'Frekuensi'])
    
    df_res = pd.DataFrame(top_common, columns=['Kata Kunci', 'Frekuensi'])
    df_res = df_res.sort_values(by='Frekuensi', ascending=True)
    return df_res

# Dashboard Header
st.title("🏛️ Aplikasi Analisis Sentimen Publik")
st.markdown("Dasbor eksekutif berbasis AI untuk merangkum sentimen publik sebagai bahan pertimbangan kebijakan.")
st.divider()

# Load All Data
df_all = load_data_from_db()
if df_all.empty:
    df_all = pd.DataFrame(columns=[
        'platform_id', 'date', 'username', 'raw_text', 'cleaned_text', 
        'sentiment_label', 'confidence_score', 'likes', 'retweets', 'views', 
        'status', 'source_platform', 'log_activity', 'user_app'
    ])

# =====================================================================
# SIDEBAR
# =====================================================================
st.sidebar.markdown("### 🎨 Pengaturan Sistem")

# 1. Popover Disclaimer Keamanan Data
with st.sidebar.popover("🔒 Disclaimer Keamanan & Kerahasiaan Data", use_container_width=True):
    st.markdown("### 🛡️ Disclaimer Keamanan dan Kerahasiaan Data")
    st.info(
        "**Keamanan & Etika Data:**\n\n"
        "1. **Hak Cipta & Privasi:** Seluruh data yang ditarik berasal dari ruang publik media sosial dan portal berita. Data digunakan semata-mata untuk kepentingan penelitian dan analisis sentimen publik.\n"
        "2. **Kerahasiaan Identitas:** Sistem tidak menyimpan kredensial akun pribadi pengguna. Identitas publik hanya berupa username publik yang dikumpulkan sesuai ketersediaan API.\n"
        "3. **Penyimpanan:** Data tersimpan secara aman di Supabase PostgreSQL dengan enkripsi standar industri.\n"
        "4. **Penggunaan AI:** Pembersihan teks oleh LLM AI dilakukan tanpa menyimpan histori pribadi pengguna luar."
    )

# 1b. Popover Pengaturan API Key & Storage Database
with st.sidebar.popover("🔐 Pengaturan API & Database", use_container_width=True):
    st.markdown("### 🔐 Pengaturan API Key & Storage Database")
    st.caption(
        "Kunci API dan pengaturan database yang Anda masukkan di sini akan disinkronkan ke sesi aplikasi "
        "dan tersimpan secara otomatis di berkas `.env` agar tidak hilang saat halaman di-refresh."
    )
    
    cur_apify = session_credentials.get_active_apify_token()
    cur_gemini = session_credentials.get_active_gemini_key()
    cur_model = session_credentials.get_active_gemini_model()
    cur_supabase = session_credentials.get_active_supabase_url()
    cur_db_mode = session_credentials.get_active_db_mode()
    
    has_custom_apify = bool(st.session_state.get(session_credentials.KEY_APIFY, "").strip())
    has_custom_gemini = bool(st.session_state.get(session_credentials.KEY_GEMINI, "").strip())
    has_custom_supabase = bool(st.session_state.get(session_credentials.KEY_SUPABASE, "").strip())
    
    st.markdown("**Status Kredensial & Storage Aktif:**")
    st.text(f"• Apify: {'🟢 Terdeteksi (' + session_credentials.mask_credential(cur_apify) + ')' if cur_apify else '🔴 Belum Diisi'}")
    st.text(f"• LLM Gemini: {'🟢 Terdeteksi (' + session_credentials.mask_credential(cur_gemini) + ')' if cur_gemini else '🔴 Belum Diisi'}")
    st.text(f"• Varian Model: 🤖 {cur_model}")
    st.text(f"• Storage DB: {'🔵 Lokal (SQLite)' if cur_db_mode == 'sqlite' else '🟢 Awan (PostgreSQL / Supabase)'}")
    if cur_db_mode == "postgresql":
        st.text(f"  URL Cloud DB: {'🟢 Terdeteksi (' + session_credentials.mask_credential(cur_supabase) + ')' if cur_supabase else '🔴 Belum Diisi'}")
    
    st.divider()
    
    with st.form("form_session_credentials", clear_on_submit=False):
        st.markdown("**Pilihan Mode Database & Storage:**")
        selected_db_mode = st.radio(
            "Mode Penyimpanan Data:",
            options=["Lokal (SQLite)", "Awan (PostgreSQL / Supabase)"],
            index=0 if cur_db_mode == "sqlite" else 1,
            help="Lokal: simpan ke sentimen_kebijakan.db. Awan: simpan ke database PostgreSQL cloud."
        )
        
        st.markdown("**Update Kredensial Sesi (Input Tersamarkan):**")
        input_apify = st.text_input("🔑 Apify API Token:", type="password", placeholder=session_credentials.mask_credential(cur_apify) or "Masukkan Apify Token...", help="Token Apify untuk penarikan data publik.")
        
        st.markdown("---")
        st.markdown("**🧠 Pengaturan LLM AI Gemini:**")
        input_gemini = st.text_input("🧠 LLM API Key:", type="password", placeholder=session_credentials.mask_credential(cur_gemini) or "Masukkan LLM API Key...", help="Kunci API LLM untuk pembersihan EYD dan NLG Laporan.")
        
        model_options = [
            "gemini-1.5-flash",
            "gemini-2.5-flash",
            "gemini-3.1-flash-lite",
            "gemini-2.5-flash-lite",
            "gemini-1.5-pro",
            "Varian Model Kustom..."
        ]
        default_model_idx = model_options.index(cur_model) if cur_model in model_options else (len(model_options) - 1)
        selected_model_option = st.selectbox(
            "🤖 Varian Model Gemini AI:",
            options=model_options,
            index=default_model_idx,
            help="Pilih versi model Gemini AI resmi dari Google yang ingin digunakan."
        )
        if selected_model_option == "Varian Model Kustom...":
            input_model_custom = st.text_input("✍️ Ketik Identifier Model Kustom:", value=cur_model if cur_model not in model_options else "", placeholder="misal: gemini-3.1-flash-lite", help="Ketik identifier resmi nama model Gemini baru saat menginput API LLM Key.")
            chosen_gemini_model = input_model_custom.strip() if input_model_custom.strip() else cur_model
        else:
            chosen_gemini_model = selected_model_option

        st.markdown("---")
        input_supabase = st.text_input("🗄️ Cloud PostgreSQL DATABASE_URL:", type="password", placeholder=session_credentials.mask_credential(cur_supabase) or "postgresql://postgres:...@db...", help="URL PostgreSQL kustom.")
        
        c_btn_cred1, c_btn_cred2, c_btn_cred3 = st.columns([1.2, 1, 1])
        with c_btn_cred1:
            btn_test_db = st.form_submit_button("🧪 Uji DB", use_container_width=True)
        with c_btn_cred2:
            btn_save_cred = st.form_submit_button("💾 Simpan", use_container_width=True)
        with c_btn_cred3:
            btn_reset_cred = st.form_submit_button("🗑️ Reset", use_container_width=True)
            
        if btn_test_db:
            if selected_db_mode == "Lokal (SQLite)":
                ok_conn, msg_conn = db_manager.test_db_connection("sqlite")
                if ok_conn:
                    st.success(f"✅ {msg_conn}")
                else:
                    st.error(f"❌ {msg_conn}")
            else:
                target_test_url = input_supabase.strip() if input_supabase.strip() else cur_supabase
                if not target_test_url:
                    st.warning("⚠️ Silakan masukkan URL PostgreSQL Cloud terlebih dahulu untuk diuji.")
                else:
                    ok_conn, msg_conn = db_manager.test_db_connection(target_test_url)
                    if ok_conn:
                        st.success(f"✅ {msg_conn}")
                    else:
                        st.error(f"❌ {msg_conn}")

        if btn_save_cred:
            new_db_mode = "sqlite" if selected_db_mode == "Lokal (SQLite)" else "postgresql"
            st.session_state[session_credentials.KEY_DB_MODE] = new_db_mode
            st.session_state[session_credentials.KEY_GEMINI_MODEL] = chosen_gemini_model
            
            apify_val = input_apify.strip() if input_apify.strip() else None
            gemini_val = input_gemini.strip() if input_gemini.strip() else None
            supabase_val = input_supabase.strip() if input_supabase.strip() else None

            if apify_val:
                st.session_state[session_credentials.KEY_APIFY] = apify_val
            if gemini_val:
                st.session_state[session_credentials.KEY_GEMINI] = gemini_val
            if supabase_val:
                st.session_state[session_credentials.KEY_SUPABASE] = supabase_val
            
            # Reset flag kuota di database setiap kali kredensial diperbarui/disimpan
            try:
                db_manager.set_gemini_quota_flag(False)
                db_manager.set_apify_quota_flag(False)
            except Exception:
                pass
            
            # Simpan secara persisten ke file .env
            session_credentials.save_credentials_to_env(
                apify_tok=apify_val,
                gemini_key=gemini_val,
                supabase_url=supabase_val,
                gemini_model=chosen_gemini_model
            )
            
            # Pastikan tabel terinisialisasi untuk database yang baru dipilih
            try:
                db_manager.buat_tabel()
            except Exception:
                pass
                
            st.success("✅ Pengaturan database, model AI, & kredensial berhasil diperbarui dan disimpan ke file `.env`!")
            st.rerun()
            
        if btn_reset_cred:
            st.session_state[session_credentials.KEY_APIFY] = ""
            st.session_state[session_credentials.KEY_GEMINI] = ""
            st.session_state[session_credentials.KEY_GEMINI_MODEL] = "gemini-1.5-flash"
            st.session_state[session_credentials.KEY_SUPABASE] = ""
            st.session_state[session_credentials.KEY_DB_MODE] = "sqlite"
            session_credentials.save_credentials_to_env(apify_tok="", gemini_key="", supabase_url="", gemini_model="gemini-1.5-flash")
            st.info("ℹ️ Pengaturan dikembalikan ke nilai default (SQLite Lokal & gemini-1.5-flash).")
            st.rerun()

# # 1c. Popover Tools Migrasi Data (Lokal ↔ Cloud)
# with st.sidebar.popover("🔄 Migrasi Data (Lokal ↔ Cloud)", use_container_width=True):
#     st.markdown("### 🔄 Tools Migrasi Data")
#     st.caption("Menyalin seluruh record (log cuitan, sistem konfigurasi, riwayat keysearch) antara SQLite Lokal dan Cloud PostgreSQL.")
#     
#     cloud_url_for_mig = session_credentials.get_active_supabase_url()
#     
#     if not cloud_url_for_mig:
#         st.warning("⚠️ Database URL Cloud belum dikonfigurasi. Atur DATABASE_URL di menu Pengaturan API & Database terlebih dahulu.")
#     else:
#         st.info(f"Target Cloud DB: `{session_credentials.mask_credential(cloud_url_for_mig)}`")
#         
#         c_mig1, c_mig2 = st.columns(2)
#         with c_mig1:
#             btn_mig_to_cloud = st.button("📤 Lokal ➔ Cloud", use_container_width=True, help="Unggah seluruh data SQLite lokal ke Cloud PostgreSQL.")
#         with c_mig2:
#             btn_mig_to_local = st.button("📥 Cloud ➔ Lokal", use_container_width=True, help="Unduh seluruh data Cloud PostgreSQL ke SQLite lokal.")
#             
#         if btn_mig_to_cloud:
#             with st.spinner("Mengunggah data dari SQLite lokal ke Cloud PostgreSQL..."):
#                 ok_m, stats_m, msg_m = db_manager.migrate_database("", cloud_url_for_mig)
#                 if ok_m:
#                     st.success(f"✅ {msg_m}")
#                     st.rerun()
#                 else:
#                     st.error(f"❌ {msg_m}")
#                     
#         if btn_mig_to_local:
#             with st.spinner("Mengunduh data dari Cloud PostgreSQL ke SQLite lokal..."):
#                 ok_m, stats_m, msg_m = db_manager.migrate_database(cloud_url_for_mig, "")
#                 if ok_m:
#                     st.success(f"✅ {msg_m}")
#                     st.rerun()
#                 else:
#                     st.error(f"❌ {msg_m}")

# 2. Akses Database
st.sidebar.divider()
st.sidebar.markdown("### 🗄️ Status & Akses Database")
col_db1, col_db2 = st.sidebar.columns([1, 1])
with col_db1:
    if session_credentials.get_active_db_mode() == "sqlite":
        with st.popover("🗄️ Database", use_container_width=True, help="Informasi & File Database SQLite Lokal"):
            st.markdown("#### 📂 Database Lokal (SQLite)")
            st.write("Mode database aktif: **Lokal (SQLite)**")
            st.code("sentimen_kebijakan.db", language="text")
            db_size_str = "0 KB"
            if os.path.exists("sentimen_kebijakan.db"):
                size_bytes = os.path.getsize("sentimen_kebijakan.db")
                db_size_str = f"{size_bytes / 1024:.1f} KB" if size_bytes < 1024*1024 else f"{size_bytes / (1024*1024):.2f} MB"
            st.caption(f"Ukuran Berkas DB: {db_size_str}")
            if os.path.exists("sentimen_kebijakan.db"):
                with open("sentimen_kebijakan.db", "rb") as f:
                    st.download_button(
                        label="📥 Unduh File DB (SQLite)",
                        data=f.read(),
                        file_name="sentimen_kebijakan.db",
                        mime="application/x-sqlite3",
                        use_container_width=True
                    )
    else:
        st.link_button(
            "🗄️ Database",
            get_supabase_dashboard_url(),
            use_container_width=True,
            help="Buka editor tabel PostgreSQL Supabase secara instan."
        )
with col_db2:
    if st.button("🔄 Muat Ulang", use_container_width=True, help="Muat ulang seluruh data dari basis data aktif.", key="btn_reload_db_sidebar"):
        try:
            st.cache_data.clear()
        except Exception:
            pass
        st.toast(f"🔄 Data berhasil dimuat ulang dari Database ({session_credentials.get_active_db_mode().upper()})!")
        st.rerun()

if check_db_storage_full():
    st.sidebar.error("🚨 Status Storage DB: Penyimpanan Penuh (Hubungi Developer untuk Pembersihan Storage)")

if check_apify_quota_exhausted():
    st.sidebar.error("🚨 Status APIFY: Quota/Saldo Habis (Hubungi Developer / Top-up Quota)")

if check_gemini_quota_exhausted():
    c_q1, c_q2 = st.sidebar.columns([3, 1])
    with c_q1:
        st.error("🚨 Status LLM AI: Quota Token Habis")
    with c_q2:
        if st.button("🔄 Reset", key="btn_reset_gemini_quota_badge", help="Klik untuk memulihkan status kuota Gemini AI"):
            db_manager.set_gemini_quota_flag(False)
            st.rerun()

# 📌 Sidebar: Pengelolaan Topik Sentimen
st.sidebar.divider()
st.sidebar.markdown("### 📌 Pengelolaan Topik Sentimen")

def get_all_combined_history_terms():
    """
    Mengambil gabungan seluruh istilah kata kunci/profil/tagar dari:
    1. Database keysearch_history
    2. File target_config.json
    3. Session state input saat ini (tw_kw, ig_kw, li_kw, web_kw, dll)
    """
    terms_set = set()
    
    # 1. Dari database
    try:
        if hasattr(db_manager, 'ambil_riwayat_gabungan'):
            for t in db_manager.ambil_riwayat_gabungan():
                if t and t != "ALL (Semua Data)":
                    terms_set.add(t)
    except Exception:
        pass
        
    # 2. Dari target_config.json
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r') as f_cfg:
                c_data = json.load(f_cfg)
                c_root = c_data.get("config", {})
                for sub_key in ["general", "twitter", "instagram", "linkedin", "portal_berita", "website"]:
                    sub_c = c_root.get(sub_key, {})
                    if isinstance(sub_c, dict):
                        for item in sub_c.get("keywords", []) + sub_c.get("profiles", []) + sub_c.get("hashtags", []):
                            if item and str(item).strip() and str(item).strip() != "ALL (Semua Data)":
                                terms_set.add(str(item).strip())
    except Exception:
        pass

    # 3. Dari session_state input aktif pengguna
    for ss_key in ["tw_kw", "tw_prof", "tw_hash", "ig_kw", "ig_prof", "li_kw", "web_kw", "web_urls"]:
        raw_val = str(st.session_state.get(ss_key, "")).strip()
        if raw_val:
            for sub in raw_val.split(","):
                sub_clean = sub.strip()
                if sub_clean and sub_clean != "ALL (Semua Data)":
                    terms_set.add(sub_clean)

    return sorted(list(terms_set))

# Sinkronisasi otomatis kata kunci dari file konfigurasi tersimpan ke keysearch_history
try:
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as f_cfg:
            c_data = json.load(f_cfg)
            c_root = c_data.get("config", {})
            syn_kw, syn_prof, syn_hash = [], [], []
            for sub_key in ["general", "twitter", "instagram", "linkedin", "portal_berita", "website"]:
                sub_c = c_root.get(sub_key, {})
                if isinstance(sub_c, dict):
                    syn_kw.extend(sub_c.get("keywords", []))
                    syn_prof.extend(sub_c.get("profiles", []))
                    syn_hash.extend(sub_c.get("hashtags", []))
            if syn_kw or syn_prof or syn_hash:
                db_manager.simpan_keysearch_history(syn_kw, syn_prof, syn_hash)
except Exception:
    pass

raw_history_sb = get_all_combined_history_terms()

try:
    if hasattr(db_manager, 'ambil_semua_bookmark'):
        existing_bookmarks_sb = db_manager.ambil_semua_bookmark()
    else:
        existing_bookmarks_sb = []
except Exception:
    existing_bookmarks_sb = []

with st.sidebar.expander("➕ Buat / Rename Topik Sentimen Baru", expanded=False):
    bm_selected_terms = st.multiselect(
        "Pilih Kata/Istilah Riwayat:",
        options=raw_history_sb,
        key="sb_bm_multiselect",
        help="Pilih satu atau beberapa istilah kata kunci untuk digabungkan menjadi Topik."
    )
    bm_custom_name = st.text_input(
        "Nama Topik Sentimen:",
        placeholder="misal: Isu MBG, Monitoring IKN",
        key="sb_bm_textinput",
        help="Beri nama unik untuk Topik Sentimen ini."
    )
    if st.sidebar.button("📌 Simpan Topik Sentimen", type="primary", use_container_width=True, key="btn_save_bookmark"):
        if not bm_selected_terms:
            st.sidebar.warning("⚠️ Silakan pilih minimal 1 istilah.")
        elif not bm_custom_name.strip():
            st.sidebar.warning("⚠️ Masukkan nama Topik Sentimen terlebih dahulu.")
        else:
            ok_bm, msg_bm = db_manager.simpan_bookmark(bm_custom_name, bm_selected_terms)
            if ok_bm:
                st.sidebar.success(f"✅ {msg_bm}")
                st.rerun()
            else:
                st.sidebar.error(f"❌ {msg_bm}")

if existing_bookmarks_sb:
    st.sidebar.markdown("**Daftar Topik Sentimen Aktif:**")
    for bm in existing_bookmarks_sb:
        col_bmn, col_bmd = st.sidebar.columns([3, 1])
        with col_bmn:
            st.markdown(f"**{bm['bookmark_name']}**")
            st.caption(f"_{bm['terms_str']}_")
        with col_bmd:
            if st.button("🗑️", key=f"del_bm_{bm['id']}", help=f"Hapus {bm['bookmark_name']}"):
                ok_del, msg_del = db_manager.hapus_bookmark(bm['id'])
                if ok_del:
                    st.rerun()

st.sidebar.divider()
st.sidebar.info("💡 **Tips Tema:** Klik ikon **⋮** di sudut kanan atas layar > **Settings > Theme** untuk memilih *Light* atau *Dark Mode*.")

# =====================================================================
# UTAMA: 4 TAB TAHAPAN KERJA
# =====================================================================
tab_scrape, tab_ml, tab_review, tab_viz = st.tabs([
    "📥 1. Penarikan Data", 
    "🧠 2. Proses AI & ML", 
    "📋 3. Review Data", 
    "📊 4. Visualisasi & Analisis"
])

# =====================================================================
# TAB 1: PENARIKAN DATA (SCRAPER)
# =====================================================================
with tab_scrape:
    st.subheader("📥 Tahapan 1: Penarikan Data (Scraper)")
    st.markdown("Tentukan parameter target penarikan data publik dari Twitter (X), Instagram, LinkedIn, dan Website / Dokumen Publik.")
    
    # 3.1 Cek Kapasitas Storage Database (Real-Time Error Detection)
    try:
        if hasattr(db_manager, 'hitung_total_baris'):
            total_db_rows = db_manager.hitung_total_baris()
        else:
            total_db_rows = len(df_all) if not df_all.empty else 0
    except Exception:
        total_db_rows = len(df_all) if not df_all.empty else 0

    db_is_full = check_db_storage_full()
    apify_is_out = check_apify_quota_exhausted()
    
    if db_is_full:
        st.error(
            "🚨 **Mohon maaf untuk sementara waktu mesin tidak dapat digunakan karena penyimpanan database telah penuh "
            "untuk penggunaan lebih lanjut dapat menghubungi Mrs Prof. Tuti Rachmawati, PhD - Universitas Parahyangan**"
        )
        st.caption(f"📦 Status Storage Database: 🚨 **Penyimpanan Penuh / Gagal Menulis Data ke Supabase** ({total_db_rows:,} baris tersimpan).")
    elif apify_is_out:
        st.error(
            "🚨 **Mohon maaf untuk sementara waktu mesin penarikan data tidak dapat digunakan karena saldo/kuota paket APIFY telah HABIS "
            "untuk penggunaan lebih lanjut dapat menghubungi Mrs Prof. Tuti Rachmawati, PhD - Universitas Parahyangan**"
        )
        st.caption(f"📦 Status Storage Database: 🟢 **Normal** ({total_db_rows:,} baris tersimpan) | 🚨 **Kuota APIFY Habis**")
    else:
        st.caption(f"📦 Status Storage Database: 🟢 **Normal** ({total_db_rows:,} baris tersimpan).")
    
    # Muat Konfigurasi Target dari target_config.json
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                current_config = json.load(f)
        except Exception:
            current_config = {}
    else:
        current_config = {}
        
    cfg_all_root = current_config.get("config", {})
    general_cfg = cfg_all_root.get("general", {})
    twitter_cfg = cfg_all_root.get("twitter", general_cfg)
    instagram_cfg = cfg_all_root.get("instagram", general_cfg)
    linkedin_cfg = cfg_all_root.get("linkedin", general_cfg)
    website_cfg = cfg_all_root.get("website", general_cfg)

    raw_source_list = current_config.get("source_types")
    if not raw_source_list:
        single = current_config.get("source_type", "")
        raw_source_list = [single] if single else []
    elif isinstance(raw_source_list, str):
        raw_source_list = [raw_source_list]
    
    mapping_source_types = {
        "twitter": "Twitter (X)",
        "twitter_": "Twitter (X)",
        "instagram": "Instagram",
        "linkedin": "LinkedIn",
        "website": "Website / Dokumen Publik"
    }
    rev_mapping = {
        "Twitter (X)": "twitter",
        "Instagram": "instagram",
        "LinkedIn": "linkedin",
        "Website / Dokumen Publik": "website"
    }
    platform_options = ["Twitter (X)", "Instagram", "LinkedIn", "Website / Dokumen Publik"]
    
    # Default awal: Ikuti konfigurasi tersimpan (kosong jika belum ada yang dipilih)
    default_selected = [mapping_source_types.get(s) for s in raw_source_list if mapping_source_types.get(s)]

    selected_platforms = st.multiselect(
        "Pilih Platform Sasaran Scraping (bisa pilih lebih dari satu):",
        options=platform_options,
        default=default_selected
    )

    def save_platform_config(platform_key: str, plat_obj: dict):
        """Helper untuk menguji & menyimpan konfigurasi per platform ke target_config.json"""
        if not selected_platforms:
            st.error("❌ Pilih setidaknya satu platform sasaran pada multiselect di atas.")
            return False
        
        source_types_to_save = [rev_mapping[sp] for sp in selected_platforms if sp in rev_mapping]
        
        # Baca ulang konfigurasi terkini dari berkas
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r') as f:
                    cfg_store = json.load(f)
            except Exception:
                cfg_store = {}
        else:
            cfg_store = {}

        if "config" not in cfg_store or not isinstance(cfg_store["config"], dict):
            cfg_store["config"] = {}

        cfg_store["source_types"] = source_types_to_save
        cfg_store["config"][platform_key] = plat_obj

        # Update general fallback agar backward-compatible
        if "general" not in cfg_store["config"]:
            cfg_store["config"]["general"] = {}
        cfg_store["config"]["general"].update(plat_obj)

        with open(CONFIG_FILE, 'w') as f:
            json.dump(cfg_store, f, indent=4)
        return True

    def _parse_date(d_str, fallback_days=7):
        if d_str:
            try: return datetime.datetime.strptime(str(d_str), "%Y-%m-%d").date()
            except Exception: pass
        return datetime.date.today() - datetime.timedelta(days=fallback_days)

    # -----------------------------------------------------------------
    # 1. FORM TWITTER (X)
    # -----------------------------------------------------------------
    # Helper untuk simpan semua konfigurasi platform aktif saat ini dari session state
    def do_save_all_current_configs(show_toast=False):
        saved_count = 0
        all_kw, all_prof, all_hash = [], [], []
        try:
            if "Twitter (X)" in selected_platforms:
                tw_kw_raw = str(st.session_state.get("tw_kw", ""))
                tw_prof_raw = str(st.session_state.get("tw_prof", ""))
                tw_hash_raw = str(st.session_state.get("tw_hash", ""))
                tw_start_d = st.session_state.get("tw_start")
                tw_end_d = st.session_state.get("tw_end")
                tw_max_num = int(st.session_state.get("tw_max", 500))

                tw_kw_list = [k.strip() for k in tw_kw_raw.split(",") if k.strip()]
                tw_prof_list = [p.strip() for p in tw_prof_raw.split(",") if p.strip()]
                tw_hash_list = [h.strip() for h in tw_hash_raw.split(",") if h.strip()]

                all_kw.extend(tw_kw_list)
                all_prof.extend(tw_prof_list)
                all_hash.extend(tw_hash_list)

                tw_obj = {
                    "start_date": tw_start_d.strftime("%Y-%m-%d") if hasattr(tw_start_d, 'strftime') else str(tw_start_d or ""),
                    "end_date": tw_end_d.strftime("%Y-%m-%d") if hasattr(tw_end_d, 'strftime') else str(tw_end_d or ""),
                    "keywords": tw_kw_list,
                    "profiles": tw_prof_list,
                    "hashtags": tw_hash_list,
                    "max_results": tw_max_num,
                    "max_results_twitter": tw_max_num
                }
                if save_platform_config("twitter", tw_obj):
                    saved_count += 1

            if "Instagram" in selected_platforms:
                ig_kw_raw = str(st.session_state.get("ig_kw", ""))
                ig_prof_raw = str(st.session_state.get("ig_prof", ""))
                ig_start_d = st.session_state.get("ig_start")
                ig_mode_val = str(st.session_state.get("ig_profile_mode_radio", "username"))
                ig_max_num = int(st.session_state.get("ig_max", 100))

                ig_kw_list = [k.strip() for k in ig_kw_raw.split(",") if k.strip()]
                ig_prof_list = [p.strip() for p in ig_prof_raw.split(",") if p.strip()]

                all_kw.extend(ig_kw_list)
                all_prof.extend(ig_prof_list)

                ig_obj = {
                    "start_date": ig_start_d.strftime("%Y-%m-%d") if hasattr(ig_start_d, 'strftime') else str(ig_start_d or ""),
                    "keywords": ig_kw_list,
                    "hashtags": [k.lstrip("#") for k in ig_kw_list],
                    "profiles": ig_prof_list,
                    "profile_mode": ig_mode_val,
                    "max_results": ig_max_num,
                    "max_results_instagram": ig_max_num
                }
                if save_platform_config("instagram", ig_obj):
                    saved_count += 1

            if "LinkedIn" in selected_platforms:
                li_kw_raw = str(st.session_state.get("li_kw", ""))
                li_start_d = st.session_state.get("li_start")
                li_max_num = int(st.session_state.get("li_max", 100))

                li_kw_list = [k.strip() for k in li_kw_raw.split(",") if k.strip()]
                all_kw.extend(li_kw_list)

                li_obj = {
                    "start_date": li_start_d.strftime("%Y-%m-%d") if hasattr(li_start_d, 'strftime') else str(li_start_d or ""),
                    "keywords": li_kw_list,
                    "max_results": li_max_num,
                    "max_results_linkedin": li_max_num
                }
                if save_platform_config("linkedin", li_obj):
                    saved_count += 1

            if "Website / Dokumen Publik" in selected_platforms:
                web_urls_raw = str(st.session_state.get("web_urls", ""))
                web_kw_raw = str(st.session_state.get("web_kw", ""))
                web_start_d = st.session_state.get("web_start")
                web_end_d = st.session_state.get("web_end")
                web_max_num = int(st.session_state.get("web_max", 100))

                web_urls_list = [u.strip() for u in web_urls_raw.split(",") if u.strip()]
                web_kw_list = [k.strip() for k in web_kw_raw.split(",") if k.strip()]
                all_kw.extend(web_kw_list)
                all_prof.extend(web_urls_list)

                web_obj = {
                    "start_date": web_start_d.strftime("%Y-%m-%d") if hasattr(web_start_d, 'strftime') else str(web_start_d or ""),
                    "end_date": web_end_d.strftime("%Y-%m-%d") if hasattr(web_end_d, 'strftime') else str(web_end_d or ""),
                    "website_urls": web_urls_list,
                    "start_urls": web_urls_list,
                    "keywords": web_kw_list,
                    "max_results": web_max_num,
                    "max_results_website": web_max_num
                }
                if save_platform_config("website", web_obj):
                    saved_count += 1

            # Simpan kata kunci/istilah pencarian ke tabel keysearch_history di database secara instan
            if all_kw or all_prof or all_hash:
                try:
                    db_manager.simpan_keysearch_history(all_kw, all_prof, all_hash)
                except Exception as _e_hist:
                    pass

            st.session_state["config_saved_at"] = datetime.datetime.now().strftime("%H:%M:%S UTC")

            if show_toast and saved_count > 0:
                st.success(f"✅ Seluruh konfigurasi ({saved_count} platform) berhasil disimpan!")
                st.rerun()
        except Exception as _e_save:
            if show_toast:
                st.error(f"❌ Gagal menyimpan konfigurasi: {_e_save}")

    def render_active_config_summary_card():
        """Menampilkan rangkuman status konfigurasi aktif per platform secara konsisten dan meyakinkan."""
        if not selected_platforms:
            return
        
        last_saved = st.session_state.get("config_saved_at")
        save_badge = f" (Tersimpan: {last_saved})" if last_saved else " (Siap Diberlakukan)"
        
        try:
            if os.path.exists(CONFIG_FILE):
                with open(CONFIG_FILE, 'r') as f:
                    c_store = json.load(f)
            else: c_store = {}
        except Exception: c_store = {}
        
        c_root = c_store.get("config", {})
        gen_c = c_root.get("general", {})
        
        tw_c = c_root.get("twitter", gen_c)
        ig_c = c_root.get("instagram", gen_c)
        li_c = c_root.get("linkedin", gen_c)
        web_c = c_root.get("website", gen_c)

        with st.container(border=True):
            st.markdown(f"#### 📌 Status Konfigurasi Terpasang & Siap Digunakan {save_badge}")
            st.caption("Berikut adalah rangkuman parameter pencarian per platform yang aktif dan tersimpan saat ini:")
            
            cols = st.columns(len(selected_platforms))
            for idx, sp in enumerate(selected_platforms):
                with cols[idx]:
                    if sp == "Twitter (X)":
                        st.markdown("##### 🐦 Twitter (X)")
                        kw = ", ".join(tw_c.get("keywords", [])) or "*(Kosong)*"
                        prof = ", ".join(tw_c.get("profiles", [])) or "*(Kosong)*"
                        hash_t = ", ".join(tw_c.get("hashtags", [])) or "*(Kosong)*"
                        mx = tw_c.get("max_results_twitter") or tw_c.get("max_results", 500)
                        st.markdown(f"• **Kata Kunci:** `{kw}`\n• **Profil:** `{prof}`\n• **Hashtag:** `{hash_t}`\n• **Batas Max:** `{mx}` cuitan")
                    elif sp == "Instagram":
                        st.markdown("##### 📸 Instagram")
                        kw = ", ".join(ig_c.get("keywords", [])) or "*(Kosong)*"
                        prof = ", ".join(ig_c.get("profiles", [])) or "*(Kosong)*"
                        mode = ig_c.get("profile_mode", "username")
                        mx = ig_c.get("max_results_instagram") or ig_c.get("max_results", 100)
                        st.markdown(f"• **Kata Kunci:** `{kw}`\n• **Username:** `{prof}`\n• **Mode:** `{mode}`\n• **Batas Max:** `{mx}` posting")
                    elif sp == "LinkedIn":
                        st.markdown("##### 💼 LinkedIn")
                        kw = ", ".join(li_c.get("keywords", [])) or "*(Kosong)*"
                        mx = li_c.get("max_results_linkedin") or li_c.get("max_results", 100)
                        st.markdown(f"• **Kata Kunci:** `{kw}`\n• **Batas Max:** `{mx}` posting")
                    elif sp == "Website / Dokumen Publik":
                        st.markdown("##### 🌐 Website")
                        urls = ", ".join(web_c.get("website_urls", [])) or "Semua Portal Berita"
                        kw = ", ".join(web_c.get("keywords", [])) or "*(Kosong)*"
                        mx = web_c.get("max_results_website") or web_c.get("max_results", 100)
                        st.markdown(f"• **Target Domain:** `{urls}`\n• **Frasa Cari:** `{kw}`\n• **Batas Max:** `{mx}` artikel")

    # -----------------------------------------------------------------
    # 1. KONFIGURASI TWITTER (X)
    # -----------------------------------------------------------------
    if "Twitter (X)" in selected_platforms:
        with st.container(border=True):
            st.markdown("### 🐦 Konfigurasi Penarikan Twitter (X)")
            col_tw1, col_tw2 = st.columns(2)
            with col_tw1:
                tw_start_val = _parse_date(twitter_cfg.get("start_date"), 7)
                tw_start_input = st.date_input("Tanggal Mulai Target (Twitter)", value=tw_start_val, key="tw_start")
            with col_tw2:
                tw_end_val = _parse_date(twitter_cfg.get("end_date"), 0)
                tw_end_input = st.date_input("Tanggal Akhir Target (Twitter)", value=tw_end_val, key="tw_end")

            tw_kw_val = ", ".join(twitter_cfg.get("keywords", []))
            tw_prof_val = ", ".join(twitter_cfg.get("profiles", []))
            tw_hash_val = ", ".join(twitter_cfg.get("hashtags", []))
            tw_max_val = int(twitter_cfg.get("max_results_twitter") or twitter_cfg.get("max_results", 500))

            tw_kw_input = st.text_input("Target Kata Kunci / Search Key (Twitter):", value=tw_kw_val, help="Dapat menggunakan operator pencarian lanjutan Twitter seperti tabel panduan di atas.", key="tw_kw")
            tw_prof_input = st.text_input("Target Profil Akun (Twitter):", value=tw_prof_val, key="tw_prof")
            tw_hash_input = st.text_input("Target Tagar/Hashtag (Twitter):", value=tw_hash_val, key="tw_hash")
            tw_max_input = st.slider("Batas maksimal cuitan (Twitter):", 10, 5000, tw_max_val, 10, key="tw_max")

    # -----------------------------------------------------------------
    # 2. KONFIGURASI INSTAGRAM
    # -----------------------------------------------------------------
    if "Instagram" in selected_platforms:
        with st.container(border=True):
            st.markdown("### 📸 Konfigurasi Penarikan Instagram")
            ig_start_val = _parse_date(instagram_cfg.get("start_date"), 14)
            ig_start_input = st.date_input("Tanggal Posting Terlama (Instagram) — Mandatory jika Username diisi", value=ig_start_val, key="ig_start")

            ig_kw_val = ", ".join(instagram_cfg.get("keywords", instagram_cfg.get("hashtags", [])))
            ig_prof_val = ", ".join(instagram_cfg.get("profiles", []))
            ig_max_val = int(instagram_cfg.get("max_results_instagram") or instagram_cfg.get("max_results", 100))

            ig_kw_input = st.text_input("Kata Kunci / Hashtag (Instagram):", value=ig_kw_val, key="ig_kw")

            ig_prof_input = st.text_input("Username Instagram (pisahkan koma):", value=ig_prof_val, key="ig_prof")

            # Mode Target Profil Instagram
            ig_profile_mode_val = instagram_cfg.get("profile_mode", "username")
            ig_profile_mode = st.radio(
                "Mode Target Profil Instagram (Aktor: apify/instagram-post-scraper):",
                options=["username", "profiles"],
                index=0 if ig_profile_mode_val == "username" else 1,
                help="Pilih 'username' untuk daftar handle username, atau 'profiles' untuk target URL profil.",
                key="ig_profile_mode_radio"
            )

            ig_max_input = st.slider("Batas maksimal data yang discrape (Instagram):", 5, 500, ig_max_val, 5, key="ig_max")

    # -----------------------------------------------------------------
    # 3. KONFIGURASI LINKEDIN
    # -----------------------------------------------------------------
    if "LinkedIn" in selected_platforms:
        with st.container(border=True):
            st.markdown("### 💼 Konfigurasi Penarikan LinkedIn")
            li_start_val = _parse_date(linkedin_cfg.get("start_date"), 30)
            li_start_input = st.date_input("Tanggal Posting Terlama (LinkedIn)", value=li_start_val, key="li_start")

            li_kw_val = ", ".join(linkedin_cfg.get("keywords", []))
            li_max_val = int(linkedin_cfg.get("max_results_linkedin") or linkedin_cfg.get("max_results", 100))

            li_kw_input = st.text_input("Kata Kunci / Search Terms (LinkedIn — Aktor: harvestapi/linkedin-post-search):", value=li_kw_val, key="li_kw")
            li_max_input = st.slider("Batas maksimal data yang discrape (LinkedIn):", 5, 500, li_max_val, 5, key="li_max")

    # -----------------------------------------------------------------
    # 4. KONFIGURASI WEBSITE / DOKUMEN PUBLIK
    # -----------------------------------------------------------------
    if "Website / Dokumen Publik" in selected_platforms:
        with st.container(border=True):
            st.markdown("### 🌐 Konfigurasi Penarikan Website / Dokumen Publik")
            col_w_d1, col_w_d2 = st.columns(2)
            with col_w_d1:
                web_start_val = _parse_date(website_cfg.get("start_date"), 30)
                web_start_input = st.date_input("Tanggal Mulai Target (Website):", value=web_start_val, key="web_start")
            with col_w_d2:
                web_end_val = _parse_date(website_cfg.get("end_date"), 0)
                web_end_input = st.date_input("Tanggal Akhir Target (Website):", value=web_end_val, key="web_end")

            web_urls_raw = website_cfg.get("website_urls", website_cfg.get("start_urls", []))
            web_urls_str = ", ".join(web_urls_raw) if isinstance(web_urls_raw, list) else str(web_urls_raw)
            web_url_input = st.text_input("Target Domain / URL Website (Opsional — pisahkan koma):", value=web_urls_str, help="Contoh: kompas.com, detik.com, kemendagri.go.id (Kosongkan jika ingin mencakup seluruh situs berita)", key="web_urls")

            web_kw_val = ", ".join(website_cfg.get("keywords", []))
            web_kw_input = st.text_input("Kata Kunci / Frasa Pencarian (Searchbar — Mendukung sintaks Google Dork):", value=web_kw_val, help='Mendukung kaidah Google Dork! Contoh: "makan bergizi gratis", intitle:"stunting", inurl:nasional, atau -politik', key="web_kw")

            web_max_val = int(website_cfg.get("max_results_website") or website_cfg.get("max_results", 100))
            web_max_input = st.slider("Batas Maksimal Artikel Berita (Max Results):", 10, 1000, web_max_val, 10, key="web_max")

    st.divider()
    render_active_config_summary_card()
    st.markdown("### 🚀 Eksekusi & Pengaturan Penarikan Data")

    active_apify_tok = session_credentials.get_active_apify_token()
    has_valid_apify_tok = bool(active_apify_tok and active_apify_tok != "YOUR_APIFY_API_TOKEN_HERE")

    if not has_valid_apify_tok:
        st.warning(
            "⚠️ **Perhatian (Mandatory):** Token API Apify (`APIFY_API_TOKEN`) belum diisi!\n\n"
            "Penarikan data dari media sosial & website publik **wajib** menggunakan API Token Apify valid. "
            "Silakan masukkan token Anda pada **Sidebar (Pengaturan Kredensial)** di sebelah kiri."
        )

    c_s1_save, c_s1_run, c_s1_stop = st.columns([2.5, 3.5, 2])
    with c_s1_save:
        btn_save_all = st.button("💾 Simpan Semua Konfigurasi", key="btn_save_all_configs", use_container_width=True, help="Simpan seluruh parameter tanpa menjalankan proses penarikan data.")
    with c_s1_stop:
        btn_stop_s1 = st.button("🛑 STOP / Hentikan Paksa", key="btn_stop_scraper_s1", use_container_width=True, help="Hentikan proses penarikan data yang sedang berjalan secara paksa.")
    with c_s1_run:
        if db_is_full:
            st.button("🚀 Jalankan Penarikan Data Sekarang", type="primary", disabled=True, use_container_width=True, help="Penyimpanan database penuh (gagal menyimpan data ke Supabase). Penarikan data dinonaktifkan sementara.")
            btn_run_s1 = False
        elif apify_is_out:
            st.button("🚀 Jalankan Penarikan Data Sekarang", type="primary", disabled=True, use_container_width=True, help="Saldo/kuota paket APIFY habis. Penarikan data dinonaktifkan sementara.")
            btn_run_s1 = False
        else:
            btn_run_s1 = st.button("🚀 Jalankan Penarikan Data Sekarang", type="primary", use_container_width=True, key="btn_run_scraper_main")

    if btn_save_all:
        do_save_all_current_configs(show_toast=True)

    if btn_stop_s1:
        proc_s1 = st.session_state.get("proc_scraper_obj")
        if proc_s1 and proc_s1.poll() is None:
            kill_process_tree(proc_s1)
            st.session_state["proc_scraper_obj"] = None
            st.warning("⏹️ Penarikan data (Tahapan 1) telah dihentikan secara paksa oleh pengguna!")
        else:
            st.info("ℹ️ Tidak ada proses penarikan data yang sedang berjalan.")

    if btn_run_s1:
        if not has_valid_apify_tok:
            show_apify_token_required_dialog()
            st.error("❌ **Penarikan data dibatalkan:** Token API Apify (`APIFY_API_TOKEN`) wajib diisi terlebih dahulu pada sidebar kredensial!")
        else:
            st.session_state["last_run_summary_s1"] = None
            do_save_all_current_configs(show_toast=False)

            import queue
            import threading
            import time
            import re

            initial_raw_count = len(db_manager.ambil_cuitan_mentah())
            start_time = datetime.datetime.now()
            start_str = start_time.strftime("%H:%M:%S UTC")

            with st.status("⚡ Menghubungkan ke Apify Cloud & menarik data mentah (SIMULTAN)...", expanded=True) as status_s:
                try:
                    proc = subprocess.Popen(
                        [sys.executable, "01_run_scraper.py"],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        bufsize=1,
                        env=session_credentials.get_session_env_dict()
                    )
                    st.session_state["proc_scraper_obj"] = proc

                    log_queue = queue.Queue()
                    log_lines = []

                    def enqueue_output(out_stream, q):
                        try:
                            for line in iter(out_stream.readline, ''):
                                q.put(line)
                        except Exception:
                            pass
                        finally:
                            try:
                                if out_stream and not out_stream.closed:
                                    out_stream.close()
                            except Exception:
                                pass

                    t_out = threading.Thread(target=enqueue_output, args=(proc.stdout, log_queue))
                    t_out.daemon = True
                    t_out.start()

                    t_err = threading.Thread(target=enqueue_output, args=(proc.stderr, log_queue))
                    t_err.daemon = True
                    t_err.start()

                    info_placeholder = st.empty()
                    log_placeholder = st.empty()

                    while proc.poll() is None:
                        # Ambil baris log baru dari queue
                        while True:
                            try:
                                line = log_queue.get_nowait()
                                log_lines.append(line)
                            except queue.Empty:
                                break

                        now = datetime.datetime.now()
                        elapsed_seconds = int((now - start_time).total_seconds())
                        mins, secs = divmod(elapsed_seconds, 60)
                        time_str = f"{mins:02d}:{secs:02d}"

                        with info_placeholder.container():
                            m1, m2, m3 = st.columns(3)
                            m1.metric("🕒 Waktu Mulai (UTC)", start_str)
                            m2.metric("⏱️ Waktu Berjalan", f"{time_str} ({elapsed_seconds}s)")
                            m3.metric("⚡ Status Mesin", "Proses Scraping Aktif...")
                            st.caption(f"🎯 **Platform Target (Simultan):** {', '.join(selected_platforms)}")

                        if log_lines:
                            with log_placeholder.container():
                                st.markdown("**📋 Live Terminal Output:**")
                                st.code("".join(log_lines[-12:]), language="text")

                        time.sleep(0.5)

                    # Tunggu thread pembaca selesai flushing
                    t_out.join(timeout=2.0)
                    t_err.join(timeout=2.0)

                    # Kuras sisa queue log
                    while True:
                        try:
                            line = log_queue.get_nowait()
                            log_lines.append(line)
                        except queue.Empty:
                            break

                    stderr_text = ""
                    if proc.stderr:
                        try:
                            if not proc.stderr.closed:
                                stderr_text = proc.stderr.read()
                        except Exception:
                            stderr_text = ""
                    st.session_state["proc_scraper_obj"] = None

                    end_time = datetime.datetime.now()
                    end_str = end_time.strftime("%H:%M:%S UTC")
                    total_sec = (end_time - start_time).total_seconds()
                    t_mins, t_secs = divmod(int(total_sec), 60)
                    dur_str = f"{t_mins} menit {t_secs} detik" if t_mins > 0 else f"{total_sec:.1f} detik"

                    info_placeholder.empty()
                    log_placeholder.empty()

                    full_log_str = "".join(log_lines) or stderr_text

                    if proc.returncode != 0:
                        status_s.update(label=f"❌ Penarikan Data Gagal (Exit Code: {proc.returncode})", state="error", expanded=True)
                    else:
                        status_s.update(label="✅ Penarikan Data Mentah Selesai!", state="complete", expanded=False)

                    # Parse log untuk ekstrak jumlah data per platform & total data ditarik
                    platform_counts = {}
                    for line_str in log_lines:
                        m_p = re.search(r"Platform '([^']+)'[^\d]+(\d+)\s+baris data", line_str, re.IGNORECASE)
                        if m_p:
                            p_name = m_p.group(1).lower()
                            p_count = int(m_p.group(2))
                            if "twitter" in p_name:
                                p_name = "twitter"
                            elif "instagram" in p_name:
                                p_name = "instagram"
                            elif "linkedin" in p_name:
                                p_name = "linkedin"
                            elif "website" in p_name or "news" in p_name or "berita" in p_name:
                                p_name = "website"
                            platform_counts[p_name] = p_count

                    m_tot = re.search(r"Total gabungan (\d+) baris data", full_log_str, re.IGNORECASE)
                    if m_tot:
                        total_data_fetched = int(m_tot.group(1))
                    else:
                        total_data_fetched = sum(platform_counts.values())

                    st.session_state["last_run_summary_s1"] = {
                        "is_success": (proc.returncode == 0),
                        "start_str": start_str,
                        "end_str": end_str,
                        "dur_str": dur_str,
                        "total_data_fetched": total_data_fetched,
                        "platform_counts": platform_counts,
                        "selected_platforms": list(selected_platforms),
                        "full_log_str": full_log_str,
                        "stderr_text": stderr_text,
                        "returncode": proc.returncode
                    }
                except Exception as e_s1:
                    status_s.update(label=f"❌ Gagal memproses: {e_s1}", state="error", expanded=True)
                    st.error(f"❌ Terjadi kesalahan saat menjalankan scraper: {e_s1}")

    # Tampilkan rangkuman eksekusi penarikan data secara persisten (tidak hilang sampai tombol diklik lagi)
    if st.session_state.get("last_run_summary_s1"):
        s1 = st.session_state["last_run_summary_s1"]
        st.markdown("---")
        if s1["is_success"]:
            st.success(f"✅ **Penarikan data mentah selesai!** Berhasil menarik total **{s1['total_data_fetched']:,} baris data** dalam waktu **{s1['dur_str']}**.")
            
            m_res1, m_res2, m_res3, m_res4 = st.columns(4)
            m_res1.metric("🕒 Waktu Mulai (UTC)", s1["start_str"])
            m_res2.metric("🏁 Waktu Selesai", s1["end_str"])
            m_res3.metric("⏱️ Total Durasi", s1["dur_str"])
            m_res4.metric("📦 Total Data Ditarik", f"{s1['total_data_fetched']:,} Baris")
            
            with st.container(border=True):
                st.markdown("#### 📊 Rincian Perolehan Data Per Platform")
                sp_list = s1.get("selected_platforms", [])
                if sp_list:
                    cols_p = st.columns(len(sp_list))
                    for idx, sp in enumerate(sp_list):
                        with cols_p[idx]:
                            if sp == "Twitter (X)":
                                cnt = s1["platform_counts"].get("twitter", 0)
                                if cnt == 0 and len(sp_list) == 1 and s1.get("total_data_fetched", 0) > 0:
                                    cnt = s1["total_data_fetched"]
                                st.metric("🐦 Twitter (X)", f"{cnt:,} cuitan")
                            elif sp == "Instagram":
                                cnt = s1["platform_counts"].get("instagram", 0)
                                if cnt == 0 and len(sp_list) == 1 and s1.get("total_data_fetched", 0) > 0:
                                    cnt = s1["total_data_fetched"]
                                st.metric("📸 Instagram", f"{cnt:,} posting")
                            elif sp == "LinkedIn":
                                cnt = s1["platform_counts"].get("linkedin", 0)
                                if cnt == 0 and len(sp_list) == 1 and s1.get("total_data_fetched", 0) > 0:
                                    cnt = s1["total_data_fetched"]
                                st.metric("💼 LinkedIn", f"{cnt:,} posting")
                            elif sp == "Website / Dokumen Publik":
                                cnt = s1["platform_counts"].get("website", s1["platform_counts"].get("portal_berita", 0))
                                if cnt == 0 and len(sp_list) == 1 and s1.get("total_data_fetched", 0) > 0:
                                    cnt = s1["total_data_fetched"]
                                st.metric("🌐 Website", f"{cnt:,} artikel")

            with st.expander("📋 Log Lengkap Scraper"):
                st.code(s1["full_log_str"], language="text")
        else:
            st.error(f"❌ **Penarikan Data Dihentikan / Gagal (Exit code: {s1['returncode']})**")
            m_res1, m_res2, m_res3, m_res4 = st.columns(4)
            m_res1.metric("🕒 Waktu Mulai (UTC)", s1["start_str"])
            m_res2.metric("🏁 Waktu Selesai", s1["end_str"])
            m_res3.metric("⏱️ Durasi Berjalan", s1["dur_str"])
            m_res4.metric("📦 Total Data Ditarik", f"{s1['total_data_fetched']:,} Baris")

            if s1['returncode'] in [-9, 15, 1] and ("taskkill" in s1['stderr_text'].lower() or "keyboardinterrupt" in s1['stderr_text'].lower()):
                st.warning("⏹️ Penarikan data dihentikan secara paksa oleh pengguna.")
            else:
                st.error("❌ Penarikan data gagal atau dihentikan. Cek token APIFY_API_TOKEN di sesi / file .env.")
            
            with st.expander("📋 Log Kesalahan"):
                st.code(s1["full_log_str"], language="text")

# =====================================================================
# TAB 2: PROSES AI & KLASIFIKASI ML
# =====================================================================
with tab_ml:
    st.subheader("🧠 Tahapan 2: Proses AI (EYD Bahasa Indonesia) & Klasifikasi ML (SVM)")
    st.info(
        "ℹ️ **Ketentuan Prapemrosesan Otomatis:**\n\n"
        "**pembersihan data duplikat** (data dengan `username`, `raw_text`, dan `date` yang persis sama). Jika ada duplikat, "
        "sistem mempertahankan data dengan **informasi engagement paling tinggi**, dan jika engagement sama maka mempertahankan **urutan terakhir yang masuk scraping**)."
    )
    
    # Hitung data RAW yang tersedia
    rows_raw = db_manager.ambil_cuitan_mentah()
    raw_count = len(rows_raw)
    
    c_raw1, c_raw2 = st.columns([3, 1])
    with c_raw1:
        st.markdown(f"📦 Total Data Mentah (`RAW`) yang Siap Diproses: **{raw_count:,}** baris.")
    with c_raw2:
        if st.button("🔄 Cek Data RAW Baru", use_container_width=True):
            st.rerun()

    gemini_is_out = check_gemini_quota_exhausted()
    if gemini_is_out:
        st.error(
            "🚨 **Mohon maaf untuk sementara waktu fitur pemrosesan AI tidak dapat digunakan karena kuota token LLM AI telah HABIS "
            "untuk penggunaan lebih lanjut dapat menghubungi Mrs Prof. Tuti Rachmawati, PhD - Universitas Parahyangan**"
        )

    st.divider()
    c_s2_run, c_s2_stop = st.columns([3, 1])
    with c_s2_stop:
        btn_stop_s2 = st.button("🛑 STOP / Hentikan Paksa", key="btn_stop_pipeline_s2", use_container_width=True, help="Hentikan proses AI & ML yang sedang berjalan secara paksa.")
    with c_s2_run:
        if gemini_is_out:
            st.button("🧠 Jalankan Proses AI & ML Sekarang", type="primary", disabled=True, use_container_width=True, help="Kuota token LLM AI habis. Pemrosesan AI dinonaktifkan sementara.")
            btn_run_pipeline = False
        else:
            btn_run_pipeline = st.button("🧠 Jalankan Proses AI & ML Sekarang", type="primary", use_container_width=True, key="btn_run_pipeline_tab2")

    if btn_stop_s2:
        proc_s2 = st.session_state.get("proc_pipeline_obj")
        if proc_s2 and proc_s2.poll() is None:
            kill_process_tree(proc_s2)
            st.session_state["proc_pipeline_obj"] = None
            st.warning("⏹️ Pemrosesan AI & ML (Tahapan 2) telah dihentikan secara paksa oleh pengguna!")
        else:
            st.info("ℹ️ Tidak ada proses AI & ML yang sedang berjalan.")
    
    if btn_run_pipeline:
        st.session_state["last_run_summary_s2"] = None
        import queue
        import threading
        import time

        initial_clean_count = len(db_manager.baca_data_untuk_streamlit())
        start_time_ml = datetime.datetime.now()
        start_str_ml = start_time_ml.strftime("%H:%M:%S UTC")

        with st.status("🧠 Melakukan pembersihan duplikat RAW, standardisasi EYD (LLM), & klasifikasi SVM...", expanded=True) as status_ml:
            try:
                proc = subprocess.Popen(
                    [sys.executable, "01_pipeline_data.py"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    bufsize=1,
                    env=session_credentials.get_session_env_dict()
                )
                st.session_state["proc_pipeline_obj"] = proc

                log_queue_ml = queue.Queue()
                log_lines_ml = []

                def enqueue_output_ml(out_stream, q):
                    try:
                        for line in iter(out_stream.readline, ''):
                            q.put(line)
                    except Exception:
                        pass
                    finally:
                        try:
                            if out_stream and not out_stream.closed:
                                out_stream.close()
                        except Exception:
                            pass

                t_out_ml = threading.Thread(target=enqueue_output_ml, args=(proc.stdout, log_queue_ml))
                t_out_ml.daemon = True
                t_out_ml.start()

                t_err_ml = threading.Thread(target=enqueue_output_ml, args=(proc.stderr, log_queue_ml))
                t_err_ml.daemon = True
                t_err_ml.start()

                info_placeholder_ml = st.empty()
                log_placeholder_ml = st.empty()

                while proc.poll() is None:
                    # Ambil baris log baru dari queue
                    while True:
                        try:
                            line = log_queue_ml.get_nowait()
                            log_lines_ml.append(line)
                        except queue.Empty:
                            break

                    now = datetime.datetime.now()
                    elapsed_seconds = int((now - start_time_ml).total_seconds())
                    mins, secs = divmod(elapsed_seconds, 60)
                    time_str = f"{mins:02d}:{secs:02d}"

                    with info_placeholder_ml.container():
                        m1, m2, m3 = st.columns(3)
                        m1.metric("🕒 Waktu Mulai (UTC)", start_str_ml)
                        m2.metric("⏱️ Waktu Berjalan", f"{time_str} ({elapsed_seconds}s)")
                        m3.metric("⚡ Status Mesin", "Proses AI & ML Aktif...")

                    if log_lines_ml:
                        with log_placeholder_ml.container():
                            st.markdown("**📋 Live Terminal Output (Pipeline AI & ML):**")
                            st.code("".join(log_lines_ml[-12:]), language="text")

                    time.sleep(0.5)

                # Tunggu thread pembaca selesai flushing
                t_out_ml.join(timeout=2.0)
                t_err_ml.join(timeout=2.0)

                # Kuras sisa queue log
                while True:
                    try:
                        line = log_queue_ml.get_nowait()
                        log_lines_ml.append(line)
                    except queue.Empty:
                        break

                stderr_text = ""
                if proc.stderr:
                    try:
                        if not proc.stderr.closed:
                            stderr_text = proc.stderr.read()
                    except Exception:
                        stderr_text = ""
                st.session_state["proc_pipeline_obj"] = None

                end_time_ml = datetime.datetime.now()
                end_str_ml = end_time_ml.strftime("%H:%M:%S UTC")
                total_sec_ml = (end_time_ml - start_time_ml).total_seconds()
                t_mins_ml, t_secs_ml = divmod(int(total_sec_ml), 60)
                dur_str_ml = f"{t_mins_ml} menit {t_secs_ml} detik" if t_mins_ml > 0 else f"{total_sec_ml:.1f} detik"

                info_placeholder_ml.empty()
                log_placeholder_ml.empty()

                full_log_ml = "".join(log_lines_ml) or stderr_text
                final_clean_count = len(db_manager.baca_data_untuk_streamlit())

                st.session_state["last_run_summary_s2"] = {
                    "is_success": (proc.returncode == 0),
                    "start_str_ml": start_str_ml,
                    "end_str_ml": end_str_ml,
                    "dur_str_ml": dur_str_ml,
                    "final_clean_count": final_clean_count,
                    "full_log_ml": full_log_ml,
                    "stderr_text": stderr_text,
                    "returncode": proc.returncode
                }
            except Exception as e_s2:
                status_ml.update(label=f"❌ Gagal memproses: {e_s2}", state="error", expanded=True)
                st.error(f"❌ Terjadi kesalahan saat menjalankan pipeline AI & ML: {e_s2}")

    # Tampilkan rangkuman eksekusi proses AI & ML secara persisten (tidak hilang sampai tombol diklik lagi)
    if st.session_state.get("last_run_summary_s2"):
        s2 = st.session_state["last_run_summary_s2"]
        st.markdown("---")
        if s2["is_success"]:
            st.success(f"✅ **Proses prapemrosesan AI & klasifikasi ML selesai dengan sukses!** Data siap di-review di Tahapan 3.")

            m_ml1, m_ml2, m_ml3, m_ml4 = st.columns(4)
            m_ml1.metric("🕒 Waktu Mulai (UTC)", s2["start_str_ml"])
            m_ml2.metric("🏁 Waktu Selesai", s2["end_str_ml"])
            m_ml3.metric("⏱️ Total Durasi", s2["dur_str_ml"])
            m_ml4.metric("📦 Total Data Terolah", f"{s2['final_clean_count']:,} Baris")

            with st.expander("📋 Log Detail Pemrosesan Pipeline"):
                st.code(s2["full_log_ml"], language="text")
        else:
            if s2['returncode'] == 2:
                st.info("ℹ️ **Pemrosesan AI & ML Tidak Mengubah Data (Exit code: 2)**")
            else:
                st.error(f"❌ **Pemrosesan AI & ML Dihentikan / Gagal (Exit code: {s2['returncode']})**")
            
            m_ml1, m_ml2, m_ml3, m_ml4 = st.columns(4)
            m_ml1.metric("🕒 Waktu Mulai (UTC)", s2["start_str_ml"])
            m_ml2.metric("🏁 Waktu Selesai", s2["end_str_ml"])
            m_ml3.metric("⏱️ Durasi Berjalan", s2["dur_str_ml"])
            m_ml4.metric("📦 Total Data Terolah", f"{s2['final_clean_count']:,} Baris")

            if s2['returncode'] in [-9, 15, 1] and ("taskkill" in (s2['stderr_text'] or "").lower() or "keyboardinterrupt" in (s2['stderr_text'] or "").lower()):
                st.warning("⏹️ Pemrosesan AI & ML dihentikan secara paksa oleh pengguna.")
            elif s2['returncode'] == 2:
                st.info("💡 **Informasi:** Tidak ada data cuitan mentah baru (status `RAW`) di database yang perlu diproses. Seluruh data di database sudah selesai diproses sebelumnya, atau belum ada penarikan data baru di Tahapan 1.")
            else:
                st.error("❌ Gagal memproses pipeline data. Silakan cek detail pada Log Kesalahan di bawah. (Pastikan kunci GEMINI_API_KEY terisi jika ingin menggunakan pembersihan EYD AI dan model SVM tersedia).")

            with st.expander("📋 Log Detail & Kesalahan"):
                st.code(s2["full_log_ml"], language="text")

# =====================================================================
# TAB 3: REVIEW DATA
# =====================================================================
with tab_review:
    c_tab3_h1, c_tab3_h2 = st.columns([4, 1])
    with c_tab3_h1:
        st.subheader("📋 Tahapan 3: Review Data & Kontrol Kualitas")
        st.markdown("Transparansi data lengkap dari platform sumber beserta fasilitas pemulihan (*restore*) file cadangan data database.")
    with c_tab3_h2:
        if st.button("🔄 Muat Ulang Data", key="btn_refresh_tab3_top", use_container_width=True, help="Segarkan seluruh data live dari database"):
            st.rerun()

    # =====================================================================
    # FITUR RESTORE BACKUP DATA (DINONAKTIFKAN SEMENTARA - DAPAT DIAKTIFKAN KEMBALI)
    # =====================================================================
    # st.divider()
    # st.markdown("### 📦 Restore Backup & Memulihkan Data ke Basis Data Supabase")
    # st.info("💡 **Gunakan fitur ini untuk memulihkan (*restore*) file cadangan data `log_cuitan` hasil backup lokal (.csv, .xlsx, .sql) langsung ke tabel database Supabase/SQLite.**")
    #
    # col_b1, col_b2 = st.columns([3, 1])
    # with col_b1:
    #     up_backup_file = st.file_uploader(
    #         "Upload File Backup (Format: CSV, XLSX, atau SQL Insert):",
    #         type=['csv', 'xlsx', 'xls', 'sql'],
    #         key="up_backup_db_file_top",
    #         help="Pilih file backup lokal yang berisi data log_cuitan."
    #     )
    # with col_b2:
    #     st.markdown("<br>", unsafe_allow_html=True)
    #     btn_restore_db = st.button("📥 Import Data ke Database", type="primary", key="btn_restore_db_exec_top", use_container_width=True)
    #
    # if btn_restore_db:
    #     if up_backup_file is None:
    #         st.warning("⚠️ Silakan pilih file cadangan (.csv, .xlsx, atau .sql) terlebih dahulu.")
    #     else:
    #         ext = up_backup_file.name.split(".")[-1].lower()
    #         with st.spinner("Memproses impor data cadangan ke basis data Supabase..."):
    #             try:
    #                 import importlib
    #                 importlib.reload(db_manager)
    #             except Exception:
    #                 pass
    #
    #             if hasattr(db_manager, 'import_backup_log_cuitan'):
    #                 ok_imp, cnt_imp, msg_imp = db_manager.import_backup_log_cuitan(up_backup_file, ext)
    #             else:
    #                 ok_imp, cnt_imp, msg_imp = _fallback_import_backup(up_backup_file, ext)
    #
    #             if ok_imp:
    #                 st.success(f"✅ {msg_imp}")
    #                 st.rerun()
    #             else:
    #                 st.error(f"❌ {msg_imp}")

    # Formasi Tabel Live Lengkap (13 Kolom)
    _all_cols_needed = [
        'platform_id', 'username', 'date', 'raw_text', 'cleaned_text',
        'sentiment_label', 'confidence_score', 'source_platform',
        'likes', 'retweets', 'views', 'log_activity', 'user_app'
    ]
    
    df_live_full = df_all.copy()
    for col in _all_cols_needed:
        if col not in df_live_full.columns:
            df_live_full[col] = "-"
            
    df_live_display = df_live_full[_all_cols_needed].copy()
    col_rename_map = {
        'platform_id': 'ID Platform',
        'username': 'Username',
        'date': 'Tanggal Pembuatan',
        'raw_text': 'Teks Mentah',
        'cleaned_text': 'Teks Baku (EYD)',
        'sentiment_label': 'Label Sentimen',
        'confidence_score': 'Skor Keyakinan',
        'source_platform': 'Platform',
        'likes': 'Likes',
        'retweets': 'Retweets',
        'views': 'Tayangan',
        'log_activity': 'Log Aktivitas Scraping',
        'user_app': 'User Aplikasi'
    }
    df_live_display.rename(columns=col_rename_map, inplace=True)

    # 5.1 Kontrol Penerimaan Data & Excel
    st.divider()
    st.markdown("### ⚙️ Pengaturan Koreksi & Ambang Keyakinan Data")
    
    mode_review = st.radio(
        "Pilih Metode Review & Filter Data:",
        options=[
            "A. Filter Otomatis via Ambang Keyakinan (Confidence Score Threshold)",
            "B. Upload Tabel Live Terkoreksi via Excel (.xlsx / .csv)"
        ],
        index=0
    )
    
    df_reviewed_final = pd.DataFrame()
    
    if "A." in mode_review:
        col_thresh1, col_thresh2, col_thresh3 = st.columns(3)
        with col_thresh1:
            th_pos = st.slider("Min Confidence Sentimen POSITIF:", 0.0, 1.0, 0.0, 0.05)
        with col_thresh2:
            th_neu = st.slider("Min Confidence Sentimen NETRAL:", 0.0, 1.0, 0.0, 0.05)
        with col_thresh3:
            th_neg = st.slider("Min Confidence Sentimen NEGATIF:", 0.0, 1.0, 0.0, 0.05)
            
        # Filter berdasarkan threshold
        def _filter_conf(row):
            lbl = str(row.get('sentiment_label', ''))
            score = float(row.get('confidence_score', 0.0) or 0.0)
            if lbl == 'Positif' and score < th_pos: return False
            if lbl == 'Netral' and score < th_neu: return False
            if lbl == 'Negatif' and score < th_neg: return False
            return True

        mask = df_live_full.apply(_filter_conf, axis=1)
        df_reviewed_final = df_live_full[mask].copy()
        
    else:
        st.markdown("#### 📥 Download & 📤 Upload File Koreksi Excel")
        c_ex1, c_ex2 = st.columns(2)
        with c_ex1:
            buf_ex = BytesIO()
            try:
                with pd.ExcelWriter(buf_ex, engine='openpyxl') as writer:
                    df_live_display.to_excel(writer, index=False, sheet_name='Tabel_Live_Review')
                mime_type = "application/vnd.openpyxlformats-officedocument.spreadsheetml.sheet"
                file_ext = "xlsx"
            except Exception:
                buf_ex = BytesIO(df_live_display.to_csv(index=False).encode('utf-8'))
                mime_type = "text/csv"
                file_ext = "csv"
                
            st.download_button(
                label="📥 Download Tabel Live (Excel/CSV)",
                data=buf_ex.getvalue(),
                file_name=f"Tabel_Live_Review_Scraping.{file_ext}",
                mime=mime_type,
                use_container_width=True
            )
            
        with c_ex2:
            uploaded_file = st.file_uploader("📤 Upload Tabel Live Terkoreksi (Excel/CSV):", type=['xlsx', 'xls', 'csv'])
            if uploaded_file is not None:
                try:
                    if uploaded_file.name.endswith('.csv'):
                        df_up = pd.read_csv(uploaded_file)
                    else:
                        df_up = pd.read_excel(uploaded_file)
                    
                    inv_map = {v: k for k, v in col_rename_map.items()}
                    df_up.rename(columns=inv_map, inplace=True)
                    df_reviewed_final = df_up.copy()
                    st.success(f"✅ Berhasil mengunggah tabel terkoreksi ({len(df_reviewed_final):,} baris data). Data ini menjadi acuan final!")
                except Exception as e_up:
                    st.error(f"❌ Gagal membaca file yang diunggah: {e_up}")
                    df_reviewed_final = df_live_full.copy()
            else:
                st.info("Upload file Excel yang sudah dikoreksi di sini. Jika belum ada, seluruh data live digunakan.")
                df_reviewed_final = df_live_full.copy()

    st.session_state['df_reviewed_final'] = df_reviewed_final

    # 5.2 Visualisasi Hasil Review Data
    st.divider()
    st.markdown("### 📊 Ringkasan Visualisasi Hasil Review Data")
    
    total_volume_rev = len(df_reviewed_final)
    unique_users_rev = df_reviewed_final['username'].nunique() if 'username' in df_reviewed_final.columns and not df_reviewed_final.empty else 0
    
    pos_cnt_r = int((df_reviewed_final['sentiment_label'] == 'Positif').sum()) if 'sentiment_label' in df_reviewed_final.columns else 0
    neg_cnt_r = int((df_reviewed_final['sentiment_label'] == 'Negatif').sum()) if 'sentiment_label' in df_reviewed_final.columns else 0
    neu_cnt_r = int((df_reviewed_final['sentiment_label'] == 'Netral').sum()) if 'sentiment_label' in df_reviewed_final.columns else 0
    
    tot_sent_r = pos_cnt_r + neg_cnt_r + neu_cnt_r
    pct_pos_r = (pos_cnt_r / tot_sent_r * 100) if tot_sent_r > 0 else 0.0
    pct_neg_r = (neg_cnt_r / tot_sent_r * 100) if tot_sent_r > 0 else 0.0
    pct_neu_r = (neu_cnt_r / tot_sent_r * 100) if tot_sent_r > 0 else 0.0

    # 5 KPI Metric Cards
    cr1, cr2, cr3, cr4, cr5 = st.columns(5)
    with cr1: st.metric("📦 Total Data", f"{total_volume_rev:,}")
    with cr2: st.metric("👥 Akun Unik", f"{unique_users_rev:,}")
    with cr3: st.metric("🟢 Sentimen Positif", f"{pct_pos_r:.1f}%", delta=f"{pos_cnt_r:,} data")
    with cr4: st.metric("🔴 Sentimen Negatif", f"{pct_neg_r:.1f}%", delta=f"{neg_cnt_r:,} data", delta_color="inverse")
    with cr5: st.metric("🔵 Sentimen Netral", f"{pct_neu_r:.1f}%", delta=f"{neu_cnt_r:,} data", delta_color="off")

    # Distribusi Data per Platform Sumber (dengan Logo/Icon)
    if 'source_platform' in df_reviewed_final.columns and not df_reviewed_final.empty:
        tw_cnt_r = int(df_reviewed_final['source_platform'].astype(str).str.contains('Twitter', case=False, na=False).sum())
        ig_cnt_r = int(df_reviewed_final['source_platform'].astype(str).str.contains('Instagram', case=False, na=False).sum())
        li_cnt_r = int(df_reviewed_final['source_platform'].astype(str).str.contains('LinkedIn', case=False, na=False).sum())
        web_cnt_r = int(df_reviewed_final['source_platform'].astype(str).str.contains('Website|News|Portal|http|\.com|\.go\.id|\.id', case=False, na=False).sum())
        tot_p_r = total_volume_rev if total_volume_rev > 0 else 1
        
        tw_pct_r = tw_cnt_r / tot_p_r * 100
        ig_pct_r = ig_cnt_r / tot_p_r * 100
        li_pct_r = li_cnt_r / tot_p_r * 100
        web_pct_r = web_cnt_r / tot_p_r * 100
        
        st.markdown("<div style='margin-top: 10px; margin-bottom: 2px; font-weight: 600; font-size: 0.9em; color: #444;'>🌐 Distribusi Volume Data per Platform:</div>", unsafe_allow_html=True)
        cp1, cp2, cp3, cp4 = st.columns(4)
        with cp1: st.metric("𝕏 Twitter / X", f"{tw_pct_r:.1f}%", delta=f"{tw_cnt_r:,} data", delta_color="off")
        with cp2: st.metric("📸 Instagram", f"{ig_pct_r:.1f}%", delta=f"{ig_cnt_r:,} data", delta_color="off")
        with cp3: st.metric("💼 LinkedIn", f"{li_pct_r:.1f}%", delta=f"{li_cnt_r:,} data", delta_color="off")
        with cp4: st.metric("🌐 Website / Dokumen Publik", f"{web_pct_r:.1f}%", delta=f"{web_cnt_r:,} data", delta_color="off")

    if not df_reviewed_final.empty:
        st.markdown("<br>", unsafe_allow_html=True)
        col_c1, col_c2, col_c3 = st.columns([4, 3, 3])
        
        # Grafik 1: Tren Sentimen Harian
        with col_c1:
            st.markdown("**📈 Tren Sentimen Publik Harian**")
            if 'date' in df_reviewed_final.columns and not df_reviewed_final.empty:
                try:
                    df_rev_copy = df_reviewed_final.copy()
                    
                    def _parse_robust_date(val):
                        if pd.isna(val) or val is None or str(val).strip() in ["", "-", "None", "NaT"]:
                            return None
                        val_s = str(val).strip()
                        try:
                            dt = pd.to_datetime(val_s, utc=True, errors='coerce')
                            if pd.notna(dt):
                                return dt.date()
                        except Exception:
                            pass
                        import re
                        m = re.search(r'(\d{4}-\d{2}-\d{2})', val_s)
                        if m:
                            try:
                                return datetime.strptime(m.group(1), "%Y-%m-%d").date()
                            except Exception:
                                pass
                        return None

                    df_rev_copy['date_parsed'] = df_rev_copy['date'].apply(_parse_robust_date)
                    v_df = df_rev_copy.dropna(subset=['date_parsed'])
                    total_rev_all = len(df_reviewed_final)
                    valid_date_cnt = len(v_df)
                    missing_date_cnt = total_rev_all - valid_date_cnt

                    if not v_df.empty:
                        df_trend = v_df.groupby(['date_parsed', 'sentiment_label']).size().reset_index(name='count')
                        if not df_trend.empty:
                            fig_tr = px.line(
                                df_trend, x='date_parsed', y='count', color='sentiment_label',
                                color_discrete_map={'Positif': '#2D6A4F', 'Netral': '#4682B4', 'Negatif': '#B00020'},
                                line_shape='spline', height=260
                            )
                            fig_tr.update_layout(margin=dict(l=10, r=10, t=10, b=10))
                            st.plotly_chart(fig_tr, use_container_width=True, key="chart_tab3_trend")
                            st.caption(f"ℹ️ *Informasi Tanggal: Dari total {total_rev_all:,} data, {valid_date_cnt:,} data memiliki tanggal valid dan {missing_date_cnt:,} data tanpa tanggal (diabaikan pada grafik tren).*")
                        else:
                            st.info("Belum ada data tren sentimen terklasifikasi.")
                    else:
                        st.info(f"Tidak ada data dengan tanggal pembuatan valid untuk grafik tren ({total_rev_all:,} data diabaikan).")
                except Exception as e_tr:
                    st.info(f"Format tanggal belum dapat diproses untuk grafik tren: {e_tr}")
            else:
                st.info("Data tanggal tidak tersedia.")

        # Grafik 2: Komposisi Sentimen (Donut Chart)
        with col_c2:
            st.markdown("**🍩 Komposisi Sentimen**")
            sent_rev_counts = df_reviewed_final['sentiment_label'].value_counts().reset_index()
            sent_rev_counts.columns = ['Sentimen', 'Jumlah']
            fig_rev_pie = px.pie(
                sent_rev_counts, names='Sentimen', values='Jumlah', hole=0.4,
                color='Sentimen', color_discrete_map={'Positif': '#2D6A4F', 'Netral': '#4682B4', 'Negatif': '#B00020'}
            )
            fig_rev_pie.update_layout(margin=dict(l=10, r=10, t=10, b=10), height=260)
            st.plotly_chart(fig_rev_pie, use_container_width=True, key="chart_tab3_pie")

        # Grafik 3: Top Kata Kunci / Tagar (Horizontal Bar Chart)
        with col_c3:
            st.markdown("**🏷️ Top 10 Kata Kunci / Tagar**")
            df_top_kw = get_top_keywords_df(df_reviewed_final, top_n=10)
            if not df_top_kw.empty:
                fig_kw = px.bar(
                    df_top_kw, x='Frekuensi', y='Kata Kunci', orientation='h',
                    color_discrete_sequence=['#4B6CB7'], height=260
                )
                fig_kw.update_layout(margin=dict(l=10, r=10, t=10, b=10), yaxis=dict(autorange="reversed"))
                st.plotly_chart(fig_kw, use_container_width=True, key="chart_tab3_kw")
            else:
                st.info("Belum ada kata kunci dominan.")

        # Tabel Feed Live Interaktif (Baris Bawah)
        st.markdown("<br>", unsafe_allow_html=True)
        c_tbl_lbl, c_tbl_btn = st.columns([3, 1])
        with c_tbl_lbl:
            st.markdown("**📋 Tabel Live Interaktif (13 Kolom Lengkap):**")
        with c_tbl_btn:
            if st.button("🔄 Segarkan", key="btn_refresh_live_table", use_container_width=True, help="Muat ulang data terbaru dari database"):
                st.rerun()
        df_disp = df_reviewed_final[[c for c in _all_cols_needed if c in df_reviewed_final.columns]].copy()
        df_disp.rename(columns=col_rename_map, inplace=True)
        st.dataframe(
            df_disp,
            use_container_width=True,
            height=550,
            column_config={
                "Teks Mentah": st.column_config.TextColumn("Teks Mentah", width="large"),
                "Teks Baku (EYD)": st.column_config.TextColumn("Teks Baku (EYD)", width="large"),
                "ID Platform": st.column_config.TextColumn("ID Platform", width="medium"),
                "Tanggal Pembuatan": st.column_config.TextColumn("Tanggal Pembuatan", width="medium"),
                "Username": st.column_config.TextColumn("Username", width="medium"),
                "Label Sentimen": st.column_config.SelectboxColumn("Label Sentimen", width="small", options=["Positif", "Negatif", "Netral"]),
                "Platform": st.column_config.TextColumn("Platform", width="small"),
            }
        )

def _fallback_import_backup(file_obj, file_format: str = "csv"):
    """Fungsi cadangan impor file backup jika modul db_manager di memori belum ter-refresh."""
    try:
        if file_format == "csv":
            df = pd.read_csv(file_obj)
        elif file_format in ["xlsx", "xls"]:
            df = pd.read_excel(file_obj)
        elif file_format == "sql":
            content = file_obj.read().decode("utf-8") if hasattr(file_obj, "read") else str(file_obj)
            conn = db_manager.get_connection()
            cursor = conn.cursor()
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
            'tweet_id': 'platform_id', 'ID Platform': 'platform_id', 'Username': 'username',
            'Tanggal Pembuatan': 'date', 'Teks Mentah': 'raw_text', 'Teks Baku (EYD)': 'cleaned_text',
            'Label Sentimen': 'sentiment_label', 'Skor Keyakinan': 'confidence_score',
            'Platform': 'source_platform', 'Likes': 'likes', 'Retweets': 'retweets',
            'Tayangan': 'views', 'Log Aktivitas Scraping': 'log_activity', 'User Aplikasi': 'user_app'
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

        conn = db_manager.get_connection()
        cursor = conn.cursor()
        placeholder = db_manager.get_placeholder()
        db_type = db_manager.get_db_type()

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


# =====================================================================
# TAB 4: VISUALISASI & ANALISIS DASHBOARD
# =====================================================================
with tab_viz:
    st.subheader("📊 Tahapan 4: Visualisasi & Analisis Dashboard Eksekutif")
    st.markdown("Pengaturan kriteria analisis sentimen, perumusan narasi AI 250+ kata, dan cetak laporan resmi berformat PDF.")
    
    df_base_viz = st.session_state.get('df_reviewed_final', df_all).copy()
    
    # 6.1 Pengaturan Analisis
    st.markdown("### ⚙️ Pengaturan Parameter Analisis")
    
    # Ambil riwayat gabungan unik dan daftar Topik (bookmark)
    try:
        if hasattr(db_manager, 'ambil_riwayat_gabungan'):
            unified_history = db_manager.ambil_riwayat_gabungan()
        elif hasattr(db_manager, 'ambil_riwayat_terpisah'):
            hist_sep = db_manager.ambil_riwayat_terpisah()
            unified_history = hist_sep.get("unified", [])
        else:
            unified_history = []
    except Exception:
        unified_history = []

    try:
        if hasattr(db_manager, 'ambil_semua_bookmark'):
            bookmarks_list = db_manager.ambil_semua_bookmark()
        else:
            bookmarks_list = []
    except Exception:
        bookmarks_list = []

    bookmark_map = {bm['bookmark_name']: bm['terms'] for bm in bookmarks_list}
    bm_names = list(bookmark_map.keys())

    # Opsi dropdown: ALL + Topik Sentimen Aktif + Istilah Riwayat Unik (tanpa duplikasi dengan nama topik)
    raw_term_options = [str(term) for term in unified_history if str(term) != "ALL (Semua Data)" and str(term) not in bm_names]
    keysearch_options = ["ALL (Semua Data)"] + bm_names + raw_term_options

    selected_keysearch = st.multiselect(
        "🔍 Riwayat Keysearch (Kata Kunci, Tagar, Profil & Topik Sentimen):",
        options=keysearch_options,
        default=["ALL (Semua Data)"],
        help="Pilih istilah riwayat, 'ALL (Semua Data)', atau Topik Sentimen yang Anda buat di Sidebar."
    )

    # Validasi Pemilihan Target Analisis
    is_all_selected = "ALL (Semua Data)" in (selected_keysearch or [])
    specific_terms = [t for t in (selected_keysearch or []) if t != "ALL (Semua Data)"]
    has_specific_selected = bool(specific_terms)

    is_target_valid = is_all_selected or has_specific_selected

    # Rentang tanggal
    if not df_base_viz.empty and 'date' in df_base_viz.columns:
        try:
            df_base_viz['date_parsed'] = df_base_viz['date'].apply(_parse_robust_date)
            v_dates = df_base_viz['date_parsed'].dropna()
            if not v_dates.empty:
                min_d = v_dates.min()
                max_d = v_dates.max()
            else:
                df_base_viz['date_parsed'] = datetime.date.today()
                min_d = datetime.date.today() - datetime.timedelta(days=30)
                max_d = datetime.date.today()
        except Exception:
            df_base_viz['date_parsed'] = datetime.date.today()
            min_d = datetime.date.today() - datetime.timedelta(days=30)
            max_d = datetime.date.today()
    else:
        df_base_viz['date_parsed'] = datetime.date.today()
        min_d = datetime.date.today() - datetime.timedelta(days=30)
        max_d = datetime.date.today()
        
    col_dt1, col_dt2 = st.columns([2, 1])
    with col_dt1:
        viz_date_range = st.date_input("Rentang Periode Data Scraping:", value=(min_d, max_d))
    with col_dt2:
        st.markdown("<br>", unsafe_allow_html=True)
        btn_exec_analysis = st.button("🔍 Jalankan Analisis Sekarang", type="primary", key="btn_exec_viz", use_container_width=True)

    df_viz_filtered = df_base_viz.copy()
    selected_search_terms = []

    if not is_target_valid:
        st.divider()
        st.warning(
            "⚠️ **Analisis belum dapat dikerjakan.** Silakan pilih minimal salah satu target pencarian "
            "(Kata Kunci, Tagar, Profil Akun, atau Topik Sentimen) atau pilih **'ALL (Semua Data)'** untuk melakukan "
            "analisis komprehensif yang merepresentasikan seluruh data."
        )
    else:
        # Filter berdasarkan rentang tanggal
        if isinstance(viz_date_range, tuple) and len(viz_date_range) == 2:
            date_mask = (
                (df_viz_filtered['date_parsed'] >= viz_date_range[0]) & 
                (df_viz_filtered['date_parsed'] <= viz_date_range[1])
            ) | df_viz_filtered['date_parsed'].isna()
            df_viz_filtered = df_viz_filtered[date_mask]

        # Gabungkan istilah pencarian spesifik (termasuk membongkar istilah di dalam bookmark)
        if has_specific_selected and not is_all_selected:
            for term in specific_terms:
                if str(term).startswith("📌") and term in bookmark_map:
                    # Urai istilah di dalam bookmark
                    for sub_t in bookmark_map[term]:
                        ck = str(sub_t).strip().lower().lstrip("#@")
                        if ck and ck not in selected_search_terms:
                            selected_search_terms.append(ck)
                else:
                    ck = str(term).strip().lower().lstrip("#@")
                    if ck and ck not in selected_search_terms:
                        selected_search_terms.append(ck)

        if selected_search_terms and not df_viz_filtered.empty:
            def _matches_keysearch(row):
                txt = (str(row.get('cleaned_text') or '') + ' ' + str(row.get('raw_text') or '') + ' ' + str(row.get('username') or '')).lower()
                return any(st_term in txt for st_term in selected_search_terms)

            df_filtered_by_key = df_viz_filtered[df_viz_filtered.apply(_matches_keysearch, axis=1)]
            if not df_filtered_by_key.empty:
                df_viz_filtered = df_filtered_by_key

    df_viz_cleaned = df_viz_filtered[df_viz_filtered['status'] == 'CLEANED'] if 'status' in df_viz_filtered.columns else df_viz_filtered

    st.divider()

    total_volume_viz = len(df_viz_filtered)
    total_cleaned_viz = len(df_viz_cleaned) if not df_viz_cleaned.empty else total_volume_viz
    
    # Hitung sentimen langsung dari df_viz_filtered agar konsisten 100% dengan Tab 3 Review Data
    sentiment_target_df = df_viz_filtered if 'sentiment_label' in df_viz_filtered.columns else df_viz_cleaned
    total_labelled_viz = sentiment_target_df['sentiment_label'].notna().sum() if not sentiment_target_df.empty else 0
    sentiment_counts_viz = sentiment_target_df['sentiment_label'].value_counts() if not sentiment_target_df.empty else pd.Series()
    
    if total_labelled_viz > 0:
        persen_pos_v = (sentiment_target_df['sentiment_label'] == 'Positif').sum() / total_labelled_viz * 100
        persen_neu_v = (sentiment_target_df['sentiment_label'] == 'Netral').sum() / total_labelled_viz * 100
        persen_neg_v = (sentiment_target_df['sentiment_label'] == 'Negatif').sum() / total_labelled_viz * 100
        
        pos_cnt_v = int((sentiment_target_df['sentiment_label'] == 'Positif').sum())
        neu_cnt_v = int((sentiment_target_df['sentiment_label'] == 'Netral').sum())
        neg_cnt_v = int((sentiment_target_df['sentiment_label'] == 'Negatif').sum())
        
        max_idx_v = sentiment_counts_viz.idxmax()
        max_val_v = sentiment_counts_viz.max() / total_labelled_viz * 100
        dominant_viz = f"{max_idx_v} ({max_val_v:.1f}%)"
    else:
        persen_pos_v = persen_neu_v = persen_neg_v = 0.0
        pos_cnt_v = neu_cnt_v = neg_cnt_v = 0
        dominant_viz = "Belum Ada Data Cleaned"

    tot_likes_v = int(df_viz_filtered['likes'].sum() if 'likes' in df_viz_filtered.columns else 0)
    tot_retweets_v = int(df_viz_filtered['retweets'].sum() if 'retweets' in df_viz_filtered.columns else 0)
    tot_engagement_v = tot_likes_v + tot_retweets_v

    unique_users_v = df_viz_filtered['username'].nunique() if 'username' in df_viz_filtered.columns and not df_viz_filtered.empty else 0

    mv1, mv2, mv3, mv4, mv5 = st.columns(5)
    with mv1: st.metric("📦 Total Data", f"{total_volume_viz:,}")
    with mv2: st.metric("👥 Akun Unik", f"{unique_users_v:,}")
    with mv3: st.metric("🟢 Sentimen Positif", f"{persen_pos_v:.1f}%", delta=f"{pos_cnt_v:,} data")
    with mv4: st.metric("🔴 Sentimen Negatif", f"{persen_neg_v:.1f}%", delta=f"{neg_cnt_v:,} data", delta_color="inverse")
    with mv5: st.metric("🔵 Sentimen Netral", f"{persen_neu_v:.1f}%", delta=f"{neu_cnt_v:,} data", delta_color="off")

    # Distribusi Data per Platform Sumber (dengan Logo/Icon)
    if 'source_platform' in df_viz_filtered.columns and not df_viz_filtered.empty:
        tw_cnt_v = int(df_viz_filtered['source_platform'].astype(str).str.contains('Twitter', case=False, na=False).sum())
        ig_cnt_v = int(df_viz_filtered['source_platform'].astype(str).str.contains('Instagram', case=False, na=False).sum())
        li_cnt_v = int(df_viz_filtered['source_platform'].astype(str).str.contains('LinkedIn', case=False, na=False).sum())
        web_cnt_v = int(df_viz_filtered['source_platform'].astype(str).str.contains('Website|News|Portal|http|\.com|\.go\.id|\.id', case=False, na=False).sum())
        tot_p_v = total_volume_viz if total_volume_viz > 0 else 1
        
        tw_pct_v = tw_cnt_v / tot_p_v * 100
        ig_pct_v = ig_cnt_v / tot_p_v * 100
        li_pct_v = li_cnt_v / tot_p_v * 100
        web_pct_v = web_cnt_v / tot_p_v * 100
        
        st.markdown("<div style='margin-top: 10px; margin-bottom: 2px; font-weight: 600; font-size: 0.9em; color: #444;'>🌐 Distribusi Volume Data per Platform:</div>", unsafe_allow_html=True)
        cp1, cp2, cp3, cp4 = st.columns(4)
        with cp1: st.metric("𝕏 Twitter / X", f"{tw_pct_v:.1f}%", delta=f"{tw_cnt_v:,} data", delta_color="off")
        with cp2: st.metric("📸 Instagram", f"{ig_pct_v:.1f}%", delta=f"{ig_cnt_v:,} data", delta_color="off")
        with cp3: st.metric("💼 LinkedIn", f"{li_pct_v:.1f}%", delta=f"{li_cnt_v:,} data", delta_color="off")
        with cp4: st.metric("🌐 Website / Dokumen Publik", f"{web_pct_v:.1f}%", delta=f"{web_cnt_v:,} data", delta_color="off")

    st.markdown("<br>", unsafe_allow_html=True)

    # 6.2 Visualisasi Grafik & Narasi AI (NLG)
    col_chart_l, col_chart_m, col_chart_r = st.columns([4, 3, 3])
    with col_chart_l:
        st.markdown("**📈 Tren Sentimen Publik Harian**")
        if 'date_parsed' in df_viz_cleaned.columns and not df_viz_cleaned.empty:
            v_df_viz = df_viz_cleaned.dropna(subset=['date_parsed'])
            tot_viz_all = len(df_viz_cleaned)
            valid_viz_cnt = len(v_df_viz)
            missing_viz_cnt = tot_viz_all - valid_viz_cnt

            if not v_df_viz.empty:
                df_tr = v_df_viz.groupby(['date_parsed', 'sentiment_label']).size().reset_index(name='count')
                fig_tr = px.line(df_tr, x='date_parsed', y='count', color='sentiment_label',
                                 color_discrete_map={'Positif': '#2D6A4F', 'Netral': '#4682B4', 'Negatif': '#B00020'},
                                 line_shape='spline', height=260)
                fig_tr.update_layout(margin=dict(l=10, r=10, t=10, b=10))
                st.plotly_chart(fig_tr, use_container_width=True, key="chart_tab4_trend")
                st.caption(f"ℹ️ *Informasi Tanggal: Dari total {tot_viz_all:,} data cleaned, {valid_viz_cnt:,} data memiliki tanggal valid dan {missing_viz_cnt:,} data tanpa tanggal (diabaikan pada grafik tren).*")
            else:
                st.info("Belum ada data dengan tanggal valid untuk membentuk grafik tren.")
        else:
            st.info("Belum ada data sentimen terklasifikasi untuk membentuk grafik tren.")
            
    with col_chart_m:
        st.markdown("**🍩 Komposisi Sentimen**")
        if total_labelled_viz > 0:
            df_p = pd.DataFrame({'Sentimen': ['Positif', 'Netral', 'Negatif'], 'Jumlah': [pos_cnt_v, neu_cnt_v, neg_cnt_v]})
            fig_p = px.pie(df_p, names='Sentimen', values='Jumlah', hole=0.4,
                           color='Sentimen', color_discrete_map={'Positif': '#2D6A4F', 'Netral': '#4682B4', 'Negatif': '#B00020'},
                           height=260)
            fig_p.update_layout(margin=dict(l=10, r=10, t=10, b=10))
            st.plotly_chart(fig_p, use_container_width=True, key="chart_tab4_pie")
        else:
            st.info("Belum ada data sentimen terklasifikasi.")

    with col_chart_r:
        st.markdown("**🏷️ Top 10 Kata Kunci / Tagar**")
        df_top_kw_viz = get_top_keywords_df(df_viz_cleaned, top_n=10)
        if not df_top_kw_viz.empty:
            fig_kw_v = px.bar(
                df_top_kw_viz, x='Frekuensi', y='Kata Kunci', orientation='h',
                color_discrete_sequence=['#4B6CB7'], height=260
            )
            fig_kw_v.update_layout(margin=dict(l=10, r=10, t=10, b=10), yaxis=dict(autorange="reversed"))
            st.plotly_chart(fig_kw_v, use_container_width=True, key="chart_tab4_kw")
        else:
            st.info("Belum ada kata kunci dominan.")

    st.divider()

    # 6.2 Narasi AI (NLG)
    st.subheader("📝 Ringkasan Eksekutif Narasi AI (NLG)")
    st.markdown("Penulisan narasi otomatis berbasis AI minimal 250 kata dengan syarat minimal 100 baris data CLEANED.")
    st.caption("ℹ️ *Catatan Konteks Sentimen: Sentimen positif bukan berarti menandakan emosi yang positif namun bisa juga diartikan pembenaran atas suatu peristiwa dan sebaliknya.*")

    top_kw_str = extract_top_keywords(df_viz_cleaned, 5)
    neg_tweets = df_viz_cleaned[df_viz_cleaned['sentiment_label'] == 'Negatif'] if not df_viz_cleaned.empty else pd.DataFrame()
    contoh_suara = f"'{neg_tweets['raw_text'].iloc[0]}'" if not neg_tweets.empty else "Tidak ada cuitan negatif dominan."

    if 'ai_narratives_history' not in st.session_state:
        st.session_state['ai_narratives_history'] = []
    if 'ai_narrative_selected_idx' not in st.session_state:
        st.session_state['ai_narrative_selected_idx'] = 0
    if 'ai_narrative_viz_cache' not in st.session_state:
        st.session_state['ai_narrative_viz_cache'] = ""

    if total_cleaned_viz < 100:
        st.warning(
            "⚠️ **Data tidak cukup untuk menghasilkan narasi analisis. Minimal dibutuhkan 100 baris data yang relevan.** "
            f"(Jumlah data CLEANED saat ini: **{total_cleaned_viz}** baris).\n\n"
            "**Rekomendasi:** Silakan jalankan penarikan data baru di Tahapan 1 dan proses AI di Tahapan 2."
        )
        st.session_state['ai_narrative_viz_cache'] = ""
        st.session_state['ai_narratives_history'] = []
    else:
        if selected_search_terms:
            fokus_kebijakan_txt = ", ".join(selected_search_terms)
        else:
            fokus_kebijakan_txt = f"isu publik dengan kata kunci ({top_kw_str})"

        history = st.session_state['ai_narratives_history']
        count_generated = len(history)

        if gemini_is_out:
            st.error(
                "🚨 **Mohon maaf untuk sementara waktu fitur pemrosesan AI tidak dapat digunakan karena kuota token LLM AI telah HABIS "
                "untuk penggunaan lebih lanjut dapat menghubungi Mrs Prof. Tuti Rachmawati, PhD - Universitas Parahyangan**"
            )
            st.button("🔄 Perbarui Analisis Narasi (AI)", type="primary", disabled=True, help="Kuota token LLM AI habis. Fitur AI dinonaktifkan sementara.")
        else:
            c_btn_nlg, c_info_nlg = st.columns([2.5, 3.5])
            with c_btn_nlg:
                btn_disabled = (count_generated >= 3)
                btn_label = f"🔄 Perbarui Analisis Narasi (AI) [{count_generated}/3]" if count_generated > 0 else "🔄 Perbarui Analisis Narasi (AI)"
                btn_help = "Batas maksimal 3 versi perbarui narasi telah tercapai." if btn_disabled else f"Hasilkan versi narasi baru ({count_generated+1}/3)."
                
                if st.button(btn_label, type="primary", disabled=btn_disabled, help=btn_help, key="btn_gen_nlg_tab4"):
                    with st.spinner(f"Menganalisis isu '{fokus_kebijakan_txt}' & menyusun narasi versi {count_generated+1}..."):
                        narrative_res = generate_executive_summary(
                            total_data=total_cleaned_viz,
                            persen_negatif=round(persen_neg_v, 1),
                            persen_positif=round(persen_pos_v, 1),
                            persen_netral=round(persen_neu_v, 1),
                            top_keywords=top_kw_str,
                            contoh_cuitan=contoh_suara,
                            kebijakan_fokus=fokus_kebijakan_txt,
                            api_key=session_credentials.get_active_gemini_key()
                        )
                        st.session_state['ai_narratives_history'].append(narrative_res)
                        st.session_state['ai_narrative_selected_idx'] = len(st.session_state['ai_narratives_history']) - 1
                        st.session_state['ai_narrative_viz_cache'] = narrative_res
                        st.rerun()

            with c_info_nlg:
                if count_generated >= 3:
                    st.caption("🔒 **Batas Maksimal 3 Versi Narasi Tercapai.** Silakan pilih versi 1, 2, atau 3 di bawah ini yang paling sesuai.")
                elif count_generated > 0:
                    st.caption(f"💡 Anda telah menghasilkan **{count_generated} dari 3** batas versi narasi.")

        # Pilihan Versi Narasi (1, 2, 3) jika sudah ada narasi yang dihasilkan
        curr_history = st.session_state['ai_narratives_history']
        if curr_history:
            st.markdown("---")
            ver_labels = [f"Versi {i+1}" for i in range(len(curr_history))]
            
            curr_idx = min(st.session_state.get('ai_narrative_selected_idx', 0), len(curr_history) - 1)
            
            selected_ver = st.radio(
                "📌 **Pilih Versi Narasi yang Sesuai (Versi 1, 2, atau 3):**",
                options=ver_labels,
                index=curr_idx,
                horizontal=True,
                key="radio_select_narrative_ver",
                help="Pilih versi narasi yang paling sesuai untuk ditampilkan di dasbor dan diekspor ke laporan PDF."
            )
            
            sel_idx = ver_labels.index(selected_ver)
            st.session_state['ai_narrative_selected_idx'] = sel_idx
            st.session_state['ai_narrative_viz_cache'] = curr_history[sel_idx]

            with st.container(border=True):
                st.markdown(f"### 📝 Hasil Narasi Ringkasan Eksekutif ({selected_ver})")
                st.markdown(curr_history[sel_idx])
        else:
            st.info("Klik tombol **🔄 Perbarui Analisis Narasi** di atas untuk menghasilkan ringkasan eksekutif.")

    st.divider()

    # 6.3 Cetak Laporan PDF Resmi
    st.subheader("📄 Cetak Laporan Eksekutif (PDF)")
    st.markdown("Ekspor dokumen laporan analisis sentimen publik lengkap dalam bentuk file PDF yang siap dicetak dan didistribusikan.")

    if st.button("📥 Download Laporan Eksekutif PDF", type="primary", key="btn_gen_pdf_tab4"):
        if not PDF_LIBS_OK:
            st.error(f"🚨 Modul ReportLab/Matplotlib belum siap di server: {PDF_IMPORT_ERROR_MSG}")
        else:
            with st.spinner("Menyusun dokumen PDF eksekutif..."):
                try:
                    pdf_buf = BytesIO()
                    doc_pdf = SimpleDocTemplate(
                        pdf_buf, pagesize=A4,
                        rightMargin=1.5*cm, leftMargin=1.5*cm,
                        topMargin=1.5*cm, bottomMargin=1.5*cm
                    )
                    story_p = []
                    styles_p = getSampleStyleSheet()

                    sTitle = ParagraphStyle('DocTitle', parent=styles_p['Heading1'], fontSize=16, leading=20, alignment=1, textColor=colors.HexColor('#1a365d'))
                    sH1 = ParagraphStyle('SectionH1', parent=styles_p['Heading2'], fontSize=12, leading=16, textColor=colors.HexColor('#1a365d'), spaceBefore=10, spaceAfter=6)
                    sH2 = ParagraphStyle('SectionH2', parent=styles_p['Heading3'], fontSize=10, leading=14, textColor=colors.HexColor('#2c5282'), spaceBefore=8, spaceAfter=4)
                    sB = ParagraphStyle('BodyTextCustom', parent=styles_p['Normal'], fontSize=9, leading=13)
                    sBodyJustified = ParagraphStyle('BodyJustified', parent=styles_p['Normal'], fontSize=9, leading=14, alignment=4)

                    tgl_s = datetime.date.today().strftime('%d %B %Y')
                    story_p.append(Paragraph('LAPORAN HASIL ANALISIS SENTIMEN PUBLIK', sTitle))
                    story_p.append(Spacer(1, 0.2*cm))
                    story_p.append(Paragraph(f'Tanggal Laporan: <b>{tgl_s}</b>', ParagraphStyle('Sub', parent=styles_p['Normal'], alignment=1)))
                    story_p.append(Spacer(1, 0.8*cm))
                    
                    t_m = Table([
                        ['Total Volume Data', 'Jumlah Akun Unik', 'Total Engagement'],
                        [f"{total_volume_viz:,}", f"{unique_users_v:,}", f"{tot_engagement_v:,}"],
                        ['Sentimen Positif', 'Sentimen Negatif', 'Sentimen Netral'],
                        [f"{persen_pos_v:.1f}% ({pos_cnt_v:,} data)", f"{persen_neg_v:.1f}% ({neg_cnt_v:,} data)", f"{persen_neu_v:.1f}% ({neu_cnt_v:,} data)"]
                    ], colWidths=[5.5*cm, 5.5*cm, 5.5*cm], style=TableStyle([
                        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#1a365d')),
                        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
                        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
                        ('BACKGROUND', (0,2), (-1,2), colors.HexColor('#1a365d')),
                        ('TEXTCOLOR', (0,2), (-1,2), colors.white),
                        ('FONTNAME', (0,2), (-1,2), 'Helvetica-Bold'),
                        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
                        ('GRID', (0,0), (-1,-1), 0.3, colors.lightgrey),
                        ('FONTSIZE', (0,0), (-1,-1), 9),
                        ('BOTTOMPADDING', (0,0), (-1,-1), 5),
                        ('TOPPADDING', (0,0), (-1,-1), 5)
                    ]))
                    story_p.append(t_m)

                    story_p.append(Paragraph('BAB I — PENGATURAN TARGET SCRAPING & KEYSEARCH', sH1))
                    story_p.append(Paragraph('Ringkasan konfigurasi target scraping dan pilihan riwayat keysearch:', sB))
                    story_p.append(Spacer(1, 0.2*cm))
                    
                    clean_ks_list = []
                    if selected_keysearch:
                        for item in selected_keysearch:
                            item_str = str(item).strip()
                            if item_str in bookmark_map:
                                bm_title = item_str.replace("📌", "").strip()
                                sub_terms = ", ".join([str(t).strip() for t in bookmark_map[item_str] if str(t).strip()])
                                display_entry = f"{bm_title} ({sub_terms})" if sub_terms else bm_title
                            elif item_str.startswith("📌"):
                                display_entry = item_str.replace("📌", "").strip()
                            else:
                                display_entry = item_str

                            if display_entry and display_entry not in clean_ks_list:
                                clean_ks_list.append(display_entry)

                    ks_disp = ", ".join(clean_ks_list) if clean_ks_list else ("ALL (Semua Data)" if is_all_selected else "-")

                    t_cfg_p = Table([
                        [Paragraph('<b>Target Keysearch / Riwayat</b>', sB), Paragraph(ks_disp, sB)],
                        [Paragraph('<b>Rentang Waktu Periode</b>', sB), Paragraph(f"{viz_date_range[0]} s/d {viz_date_range[1]}" if isinstance(viz_date_range, tuple) else "-", sB)],
                    ], colWidths=[5*cm, 11*cm], style=TableStyle([('GRID',(0,0),(-1,-1),0.3,colors.lightgrey)]))
                    story_p.append(t_cfg_p)

                    story_p.append(Paragraph('BAB II — RINGKASAN REVIEW DATA', sH1))
                    story_p.append(Spacer(1, 0.2*cm))
                    
                    pie_bytes_p = _chart_pie_sentimen_pdf(pos_cnt_v, neu_cnt_v, neg_cnt_v)
                    if pie_bytes_p:
                        story_p.append(Image(pie_bytes_p, width=12*cm, height=9*cm, hAlign='CENTER'))
                    story_p.append(PageBreak())

                    story_p.append(Paragraph('BAB III — VISUALISASI ANALISIS DASHBOARD', sH1))
                    tr_bytes_p = _chart_tren_harian_pdf(df_viz_cleaned)
                    if tr_bytes_p:
                        story_p.append(Paragraph('3.1 Grafik Tren Sentimen Harian', sH2))
                        story_p.append(Image(tr_bytes_p, width=16*cm, height=7.5*cm, hAlign='CENTER'))
                        
                        v_df_pdf_cnt = len(df_viz_cleaned.dropna(subset=['date_parsed'])) if 'date_parsed' in df_viz_cleaned.columns else 0
                        tot_pdf_cnt = len(df_viz_cleaned)
                        no_date_pdf_cnt = tot_pdf_cnt - v_df_pdf_cnt
                        story_p.append(Spacer(1, 0.1*cm))
                        story_p.append(Paragraph(
                            f'<i>Informasi Tanggal: Dari total {tot_pdf_cnt:,} data cleaned, {v_df_pdf_cnt:,} data memiliki tanggal valid dan {no_date_pdf_cnt:,} data tanpa tanggal (diabaikan pada grafik tren).</i>',
                            ParagraphStyle('CaptionPDF', parent=styles_p['Italic'], fontSize=8, leading=11, textColor=colors.HexColor('#4a5568'), alignment=1)
                        ))
                    pl_bytes_p = _chart_platform_pdf(df_viz_cleaned)
                    if pl_bytes_p:
                        story_p.append(Paragraph('3.2 Volume Data per Platform', sH2))
                        story_p.append(Image(pl_bytes_p, width=16*cm, height=6.5*cm, hAlign='CENTER'))
                    story_p.append(PageBreak())

                    sBodyJustified = ParagraphStyle(
                        'BodyJustified', 
                        parent=styles_p['Normal'],
                        fontName='Helvetica',
                        fontSize=9.5,
                        leading=14,
                        alignment=4, # TA_JUSTIFY (Rata Kiri-Kanan)
                        spaceAfter=8,
                        textColor=colors.HexColor('#2d3748')
                    )
                    sHeading2Styled = ParagraphStyle(
                        'Heading2Styled',
                        parent=styles_p['Heading2'],
                        fontName='Helvetica-Bold',
                        fontSize=11,
                        leading=15,
                        textColor=colors.HexColor('#1a365d'),
                        spaceBefore=12,
                        spaceAfter=4,
                        keepWithNext=True
                    )

                    story_p.append(Paragraph('BAB IV — RINGKASAN EKSEKUTIF', sH1))
                    narasi_pdf_txt = st.session_state.get('ai_narrative_viz_cache', '')
                    if not narasi_pdf_txt:
                        story_p.append(Paragraph('<i>Narasi belum di-generate di dashboard. Silakan klik tombol Perbarui Analisis Narasi terlebih dahulu.</i>', sBodyJustified))
                    else:
                        raw_blocks = [b.strip() for b in narasi_pdf_txt.replace('\r\n', '\n').split('\n') if b.strip()]
                        
                        for block in raw_blocks:
                            # Format Markdown bold **text** -> <b>text</b>, *text* -> <i>text</i>
                            formatted_block = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', block)
                            formatted_block = re.sub(r'\*(.*?)\*', r'<i>\1</i>', formatted_block)
                            
                            if formatted_block.startswith('###') or formatted_block.startswith('##'):
                                clean_h = formatted_block.lstrip('#').strip()
                                story_p.append(Paragraph(clean_h, sHeading2Styled))
                            else:
                                story_p.append(Paragraph(formatted_block, sBodyJustified))

                    def _pn(canvas, doc):
                        canvas.saveState()
                        canvas.setFont('Helvetica', 8)
                        canvas.setFillColor(colors.HexColor('#718096'))
                        page_num = canvas.getPageNumber()
                        canvas.drawRightString(A4[0] - 1.5*cm, 1.0*cm, f"Halaman {page_num}")
                        canvas.drawString(1.5*cm, 1.0*cm, "Laporan Hasil Analisis Sentimen Publik")
                        canvas.restoreState()

                    doc_pdf.build(story_p, onFirstPage=_pn, onLaterPages=_pn)
                    pdf_buf.seek(0)
                    _pdf_report_buf = pdf_buf
                except Exception as e_pdf_gen:
                    st.error(f"❌ Gagal menyusun PDF: {e_pdf_gen}")
                    _pdf_report_buf = None

        if _pdf_report_buf is not None:
            st.download_button(
                label="⬇️ Unduh PDF Laporan Resmi",
                data=_pdf_report_buf.getvalue(),
                file_name=f"Laporan_Sentimen_Publik_{datetime.datetime.now().strftime('%Y%m%d_%H%M')}.pdf",
                mime="application/pdf",
                type="primary",
                key="btn_dl_pdf_tab4_final"
            )
