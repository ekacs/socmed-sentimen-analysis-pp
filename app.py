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
    page_title="Analisis Sentimen Kebijakan Publik berbasis AI",
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
    try:
        if hasattr(db_manager, 'is_storage_full'):
            return db_manager.is_storage_full()
    except Exception as _e:
        pass
    return False

def check_apify_quota_exhausted():
    try:
        if hasattr(db_manager, 'is_apify_quota_exhausted'):
            return db_manager.is_apify_quota_exhausted()
    except Exception as _e:
        pass
    return False

def check_gemini_quota_exhausted():
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
st.title("🏛️ Pusat Analisis Sentimen Kebijakan Publik")
st.markdown("Dasbor eksekutif berbasis AI untuk memantau sentimen publik terhadap kebijakan publik.")
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
        "1. **Hak Cipta & Privasi:** Seluruh data yang ditarik berasal dari ruang publik media sosial dan portal berita. Data digunakan semata-mata untuk kepentingan penelitian dan analisis sentimen kebijakan publik.\n"
        "2. **Kerahasiaan Identitas:** Sistem tidak menyimpan kredensial akun pribadi pengguna. Identitas publik hanya berupa username publik yang dikumpulkan sesuai ketersediaan API.\n"
        "3. **Penyimpanan:** Data tersimpan secara aman di Supabase PostgreSQL dengan enkripsi standar industri.\n"
        "4. **Penggunaan AI:** Pembersihan teks oleh Gemini AI dilakukan tanpa menyimpan histori pribadi pengguna luar."
    )

# 1b. Popover Pengaturan API Key Sesi Pengguna
with st.sidebar.popover("🔐 Pengaturan API Key Sesi", use_container_width=True):
    st.markdown("### 🔐 Pengaturan API Key Sesi Pengguna")
    st.caption(
        "Kunci API yang Anda masukkan di sini hanya tersimpan dalam memori sesi browser Anda "
        "(Session-Only) dan **otomatis terhapus** saat tab browser ditutup. Nilai kunci tersamarkan dengan **asterisk/bullet** (`••••••••`). "
        "Jika dikosongkan/di-reset, sistem secara otomatis menggunakan kunci bawaan dari file `.env`."
    )
    
    cur_apify = session_credentials.get_active_apify_token()
    cur_gemini = session_credentials.get_active_gemini_key()
    cur_supabase = session_credentials.get_active_supabase_url()
    
    has_custom_apify = bool(st.session_state.get(session_credentials.KEY_APIFY, "").strip())
    has_custom_gemini = bool(st.session_state.get(session_credentials.KEY_GEMINI, "").strip())
    has_custom_supabase = bool(st.session_state.get(session_credentials.KEY_SUPABASE, "").strip())
    
    st.markdown("**Status Kredensial Sesi Aktif:**")
    st.text(f"• Apify: {'🟢 Kustom Sesi (' + session_credentials.mask_credential(cur_apify) + ')' if has_custom_apify else '⚪ Default (.env)'}")
    st.text(f"• Gemini: {'🟢 Kustom Sesi (' + session_credentials.mask_credential(cur_gemini) + ')' if has_custom_gemini else '⚪ Default (.env)'}")
    st.text(f"• Supabase: {'🟢 Kustom Sesi (' + session_credentials.mask_credential(cur_supabase) + ')' if has_custom_supabase else '⚪ Default (.env)'}")
    
    st.divider()
    
    with st.form("form_session_credentials", clear_on_submit=True):
        st.markdown("**Update Kredensial Sesi (Input Tersamarkan):**")
        input_apify = st.text_input("🔑 Apify API Token:", type="password", placeholder="Masukkan Apify Token kustom...", help="Token Apify untuk penarikan data publik.")
        input_gemini = st.text_input("🧠 Gemini API Key:", type="password", placeholder="Masukkan Gemini API Key kustom...", help="Kunci API Gemini untuk pembersihan EYD dan NLG Laporan.")
        input_supabase = st.text_input("🗄️ Supabase DATABASE_URL:", type="password", placeholder="postgresql://postgres:...@db...supabase.co:5432/postgres", help="URL PostgreSQL Supabase kustom.")
        
        c_btn_cred1, c_btn_cred2 = st.columns([1, 1])
        with c_btn_cred1:
            btn_save_cred = st.form_submit_button("💾 Simpan Sesi", use_container_width=True)
        with c_btn_cred2:
            btn_reset_cred = st.form_submit_button("🗑️ Reset Default", use_container_width=True)
            
        if btn_save_cred:
            if input_apify.strip():
                st.session_state[session_credentials.KEY_APIFY] = input_apify.strip()
            if input_gemini.strip():
                st.session_state[session_credentials.KEY_GEMINI] = input_gemini.strip()
            if input_supabase.strip():
                st.session_state[session_credentials.KEY_SUPABASE] = input_supabase.strip()
            st.success("✅ Kredensial sesi berhasil diperbarui!")
            st.rerun()
            
        if btn_reset_cred:
            st.session_state[session_credentials.KEY_APIFY] = ""
            st.session_state[session_credentials.KEY_GEMINI] = ""
            st.session_state[session_credentials.KEY_SUPABASE] = ""
            st.info("ℹ️ Kredensial dikembalikan ke nilai default (.env).")
            st.rerun()

# 2. Akses Database Awan
st.sidebar.divider()
st.sidebar.markdown("### 🗄️ Akses Database Awan")
col_db1, col_db2 = st.sidebar.columns([1, 1])
with col_db1:
    st.link_button(
        "🌐 Supabase",
        get_supabase_dashboard_url(),
        use_container_width=True,
        help="Buka editor tabel PostgreSQL Supabase secara instan."
    )
with col_db2:
    if st.button("🔄 Muat Ulang", use_container_width=True, help="Muat ulang data dari basis data.", key="btn_reload_db_sidebar"):
        st.rerun()

if check_db_storage_full():
    st.sidebar.error("🚨 Status Storage DB: Penyimpanan Penuh (Hubungi Developer untuk Pembersihan Storage)")

if check_apify_quota_exhausted():
    st.sidebar.error("🚨 Status APIFY: Quota/Saldo Habis (Hubungi Developer / Top-up Quota)")

if check_gemini_quota_exhausted():
    st.sidebar.error("🚨 Status Gemini AI: Quota Token Habis (Hubungi Developer / Top-up Token)")

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
        single = current_config.get("source_type", "twitter_")
        raw_source_list = [single] if single else ["twitter_"]
    elif isinstance(raw_source_list, str):
        raw_source_list = [raw_source_list]
    
    mapping_source_types = {
        "twitter_": "Twitter (X)",
        "instagram": "Instagram",
        "linkedin": "LinkedIn",
        "website": "Website / Dokumen Publik"
    }
    rev_mapping = {v: k for k, v in mapping_source_types.items()}
    platform_options = ["Twitter (X)", "Instagram", "LinkedIn", "Website / Dokumen Publik"]
    
    default_selected = [mapping_source_types.get(s) for s in raw_source_list if mapping_source_types.get(s)]
    if not default_selected: default_selected = ["Twitter (X)"]

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
    if "Twitter (X)" in selected_platforms:
        with st.form("form_config_twitter"):
            st.markdown("### 🐦 Konfigurasi Penarikan Twitter (X)")
            col_tw1, col_tw2 = st.columns(2)
            with col_tw1:
                tw_start_val = _parse_date(twitter_cfg.get("start_date"), 7)
                tw_start_input = st.date_input("Tanggal Mulai Target (Twitter)", value=tw_start_val, key="tw_start")
            with col_tw2:
                tw_end_val = _parse_date(twitter_cfg.get("end_date"), 0)
                tw_end_input = st.date_input("Tanggal Akhir Target (Twitter)", value=tw_end_val, key="tw_end")

            tw_kw_val = ", ".join(twitter_cfg.get("keywords", ["mbg"]))
            tw_prof_val = ", ".join(twitter_cfg.get("profiles", ["jokowi", "kemenpupr"]))
            tw_hash_val = ", ".join(twitter_cfg.get("hashtags", ["#IKNNusantara"]))
            tw_max_val = int(twitter_cfg.get("max_results_twitter") or twitter_cfg.get("max_results", 500))

            tw_kw_input = st.text_input("Target Kata Kunci / Search Key (Twitter):", value=tw_kw_val, help="Dapat menggunakan operator pencarian lanjutan Twitter seperti tabel panduan di atas.", key="tw_kw")
            tw_prof_input = st.text_input("Target Profil Akun (Twitter):", value=tw_prof_val, key="tw_prof")
            tw_hash_input = st.text_input("Target Tagar/Hashtag (Twitter):", value=tw_hash_val, key="tw_hash")
            tw_max_input = st.slider("Batas maksimal cuitan (Twitter):", 10, 5000, tw_max_val, 10, key="tw_max")

            btn_save_tw = st.form_submit_button("💾 Simpan Konfigurasi Twitter (X)")
            if btn_save_tw:
                tw_obj = {
                    "start_date": tw_start_input.strftime("%Y-%m-%d"),
                    "end_date": tw_end_input.strftime("%Y-%m-%d"),
                    "keywords": [k.strip() for k in tw_kw_input.split(",") if k.strip()],
                    "profiles": [p.strip() for p in tw_prof_input.split(",") if p.strip()],
                    "hashtags": [h.strip() for h in tw_hash_input.split(",") if h.strip()],
                    "max_results": tw_max_input,
                    "max_results_twitter": tw_max_input
                }
                if save_platform_config("twitter", tw_obj):
                    st.success("✅ Konfigurasi Twitter (X) berhasil disimpan!")

    # -----------------------------------------------------------------
    # 2. FORM INSTAGRAM
    # -----------------------------------------------------------------
    if "Instagram" in selected_platforms:
        with st.form("form_config_instagram"):
            st.markdown("### 📸 Konfigurasi Penarikan Instagram")
            ig_start_val = _parse_date(instagram_cfg.get("start_date"), 14)
            ig_start_input = st.date_input("Tanggal Posting Terlama (Instagram) — Mandatory jika Username diisi", value=ig_start_val, key="ig_start")

            ig_kw_val = ", ".join(instagram_cfg.get("keywords", instagram_cfg.get("hashtags", ["#IKNNusantara"])))
            ig_prof_val = ", ".join(instagram_cfg.get("profiles", ["jokowi"]))
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

            btn_save_ig = st.form_submit_button("💾 Simpan Konfigurasi Instagram")
            if btn_save_ig:
                ig_prof_list = [p.strip() for p in ig_prof_input.split(",") if p.strip()]
                if ig_prof_list and not ig_start_input:
                    st.error("⚠️ Input 'Tanggal Posting Terlama' wajib diisi apabila Username Instagram diisi!")
                else:
                    ig_kw_list = [k.strip() for k in ig_kw_input.split(",") if k.strip()]
                    ig_obj = {
                        "start_date": ig_start_input.strftime("%Y-%m-%d") if ig_start_input else "",
                        "keywords": ig_kw_list,
                        "hashtags": [k.lstrip("#") for k in ig_kw_list],
                        "profiles": ig_prof_list,
                        "profile_mode": ig_profile_mode,
                        "max_results": ig_max_input,
                        "max_results_instagram": ig_max_input
                    }
                    if save_platform_config("instagram", ig_obj):
                        st.success("✅ Konfigurasi Instagram berhasil disimpan!")

    # -----------------------------------------------------------------
    # 3. FORM LINKEDIN
    # -----------------------------------------------------------------
    if "LinkedIn" in selected_platforms:
        with st.form("form_config_linkedin"):
            st.markdown("### 💼 Konfigurasi Penarikan LinkedIn")
            li_start_val = _parse_date(linkedin_cfg.get("start_date"), 30)
            li_start_input = st.date_input("Tanggal Posting Terlama (LinkedIn)", value=li_start_val, key="li_start")

            li_kw_val = ", ".join(linkedin_cfg.get("keywords", ["kebijakan publik"]))
            li_max_val = int(linkedin_cfg.get("max_results_linkedin") or linkedin_cfg.get("max_results", 100))

            li_kw_input = st.text_input("Kata Kunci / Search Terms (LinkedIn — Aktor: harvestapi/linkedin-post-search):", value=li_kw_val, key="li_kw")
            li_max_input = st.slider("Batas maksimal data yang discrape (LinkedIn):", 5, 500, li_max_val, 5, key="li_max")

            btn_save_li = st.form_submit_button("💾 Simpan Konfigurasi LinkedIn")
            if btn_save_li:
                li_obj = {
                    "start_date": li_start_input.strftime("%Y-%m-%d"),
                    "keywords": [k.strip() for k in li_kw_input.split(",") if k.strip()],
                    "max_results": li_max_input,
                    "max_results_linkedin": li_max_input
                }
                if save_platform_config("linkedin", li_obj):
                    st.success("✅ Konfigurasi LinkedIn berhasil disimpan!")

    # -----------------------------------------------------------------
    # 4. FORM WEBSITE / DOKUMEN PUBLIK
    # -----------------------------------------------------------------
    if "Website / Dokumen Publik" in selected_platforms:
        with st.form("form_config_website"):
            st.markdown("### 🌐 Konfigurasi Penarikan Website / Dokumen Publik ")
            web_urls_raw = website_cfg.get("website_urls", website_cfg.get("start_urls", ["https://www.example.com"]))
            web_urls_str = ", ".join(web_urls_raw) if isinstance(web_urls_raw, list) else str(web_urls_raw)
            web_url_input = st.text_input("Target URL (Start URLs — pisahkan koma jika lebih dari satu):", value=web_urls_str, help="Contoh: https://www.kemendagri.go.id, https://situs.com/kebijakan", key="web_urls")

            web_kw_val = ", ".join(website_cfg.get("keywords", ["kebijakan publik"]))
            web_kw_input = st.text_input("Kata Kunci / Frasa Pencarian (Searchbar — masukkan beberapa kata atau kalimat sebagai dasar pencarian):", value=web_kw_val, help="Masukkan kata atau kalimat sebagai kriteria penyaringan konten web.", key="web_kw")

            col_web1, col_web2 = st.columns(2)
            with col_web1:
                web_max_val = int(website_cfg.get("max_results_website") or website_cfg.get("max_results", 50))
                web_max_input = st.slider("Batas maksimal halaman (Max Crawl Pages):", 5, 500, web_max_val, 5, key="web_max")
            with col_web2:
                web_depth_val = int(website_cfg.get("max_depth", 1))
                web_depth_input = st.slider("Batas Kedalaman Scraping (Max Crawl Depth):", 0, 5, web_depth_val, 1, help="0 = Hanya URL Awal, 1 = URL Awal + Link Langsung di dalamnya, dst.", key="web_depth")

            web_crawler_mode_val = website_cfg.get("crawler_type", "playwright:adaptive")
            crawler_mode_options = ["playwright:adaptive", "playwright:firefox", "cheerio"]
            crawler_mode_idx = crawler_mode_options.index(web_crawler_mode_val) if web_crawler_mode_val in crawler_mode_options else 0
            
            web_crawler_mode = st.selectbox(
                "Mode Engine Crawler (Aktor: apify/website-content-crawler):",
                options=crawler_mode_options,
                index=crawler_mode_idx,
                format_func=lambda x: {
                    "playwright:adaptive": "Adaptive (Otomatis: Cepat & Rendering JS jika diperlukan — Rekomendasi)",
                    "playwright:firefox": "Headless Browser Firefox (Renders JS penuh, Cocok untuk Web Kompleks)",
                    "cheerio": "Raw HTTP Cheerio (Sangat Cepat & Hemat Kuota, Khusus HTML Murni Tanpa JS)"
                }.get(x, x),
                help="Mode default 'adaptive' disarankan agar efisien kuota dan mendukung situs web dinamis.",
                key="web_crawler_mode_select"
            )

            btn_save_web = st.form_submit_button("💾 Simpan Konfigurasi Website")
            if btn_save_web:
                web_urls_list = [u.strip() for u in web_url_input.split(",") if u.strip()]
                if not web_urls_list:
                    st.error("⚠️ Input Target URL (Start URLs) wajib diisi!")
                else:
                    web_obj = {
                        "website_urls": web_urls_list,
                        "start_urls": web_urls_list,
                        "keywords": [k.strip() for k in web_kw_input.split(",") if k.strip()],
                        "crawler_type": web_crawler_mode,
                        "max_depth": web_depth_input,
                        "max_results": web_max_input,
                        "max_results_website": web_max_input
                    }
                    if save_platform_config("website", web_obj):
                        st.success("✅ Konfigurasi Website / Dokumen Publik berhasil disimpan!")

    st.divider()
    st.markdown("### 🚀 Eksekusi Penarikan Data")
    
    c_s1_run, c_s1_stop = st.columns([3, 1])
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

    if btn_stop_s1:
        proc_s1 = st.session_state.get("proc_scraper_obj")
        if proc_s1 and proc_s1.poll() is None:
            kill_process_tree(proc_s1)
            st.session_state["proc_scraper_obj"] = None
            st.warning("⏹️ Penarikan data (Tahapan 1) telah dihentikan secara paksa oleh pengguna!")
        else:
            st.info("ℹ️ Tidak ada proses penarikan data yang sedang berjalan.")

    if btn_run_s1:
        with st.status("🚀 Menghubungkan ke Apify Cloud & menarik data mentah...", expanded=True) as status_s:
            try:
                proc = subprocess.Popen(
                    [sys.executable, "01_run_scraper.py"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    env=session_credentials.get_session_env_dict()
                )
                st.session_state["proc_scraper_obj"] = proc
                
                import time
                while proc.poll() is None:
                    time.sleep(0.5)
                    
                stdout, stderr = proc.communicate()
                st.session_state["proc_scraper_obj"] = None
                
                if proc.returncode == 0:
                    status_s.update(label="✅ Penarikan data selesai!", state="complete", expanded=False)
                    st.success("✅ Penarikan data mentah selesai. Data siap diproses di Tahapan 2.")
                    with st.expander("📋 Log Scraper"):
                        st.code(stdout, language="text")
                else:
                    status_s.update(label=f"❌ Gagal / Dihentikan (Exit code: {proc.returncode})", state="error", expanded=True)
                    if proc.returncode in [-9, 15, 1] and ("taskkill" in (stderr or "").lower() or "keyboardinterrupt" in (stderr or "").lower()):
                        st.warning("⏹️ Penarikan data dihentikan secara paksa oleh pengguna.")
                    else:
                        st.error("❌ Penarikan data gagal atau dihentikan. Cek token APIFY_API_TOKEN di sesi / file .env.")
                    with st.expander("📋 Log Kesalahan"):
                        st.code(stdout or stderr, language="text")
            except Exception as e_s1:
                status_s.update(label=f"❌ Gagal memproses: {e_s1}", state="error", expanded=True)
                st.error(f"❌ Terjadi kesalahan saat menjalankan scraper: {e_s1}")

# =====================================================================
# TAB 2: PROSES AI & KLASIFIKASI ML
# =====================================================================
with tab_ml:
    st.subheader("🧠 Tahapan 2: Proses AI (Gemini EYD) & Klasifikasi ML (SVM)")
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
            "🚨 **Mohon maaf untuk sementara waktu fitur pemrosesan AI tidak dapat digunakan karena kuota token Gemini AI telah HABIS "
            "untuk penggunaan lebih lanjut dapat menghubungi Mrs Prof. Tuti Rachmawati, PhD - Universitas Parahyangan**"
        )

    st.divider()
    c_s2_run, c_s2_stop = st.columns([3, 1])
    with c_s2_stop:
        btn_stop_s2 = st.button("🛑 STOP / Hentikan Paksa", key="btn_stop_pipeline_s2", use_container_width=True, help="Hentikan proses AI & ML yang sedang berjalan secara paksa.")
    with c_s2_run:
        if gemini_is_out:
            st.button("🧠 Jalankan Proses AI & ML Sekarang", type="primary", disabled=True, use_container_width=True, help="Kuota token Gemini AI habis. Pemrosesan AI dinonaktifkan sementara.")
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
        with st.status("🧠 Melakukan pembersihan duplikat RAW, standardisasi EYD (Gemini), & klasifikasi SVM...", expanded=True) as status_ml:
            try:
                proc = subprocess.Popen(
                    [sys.executable, "01_pipeline_data.py"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    env=session_credentials.get_session_env_dict()
                )
                st.session_state["proc_pipeline_obj"] = proc
                
                import time
                while proc.poll() is None:
                    time.sleep(0.5)
                    
                stdout, stderr = proc.communicate()
                st.session_state["proc_pipeline_obj"] = None
                
                if proc.returncode == 0:
                    status_ml.update(label="✅ Proses AI & ML Selesai!", state="complete", expanded=False)
                    st.success("✅ Proses prapemrosesan AI & klasifikasi ML selesai dengan sukses! Data siap di-review di Tahapan 3.")
                    with st.expander("📋 Log Detail Pemrosesan Pipeline"):
                        st.code(stdout, language="text")
                        if stderr: st.code(stderr, language="text")
                else:
                    status_ml.update(label=f"❌ Gagal / Dihentikan (Exit code: {proc.returncode})", state="error", expanded=True)
                    if proc.returncode in [-9, 15, 1] and ("taskkill" in (stderr or "").lower() or "keyboardinterrupt" in (stderr or "").lower()):
                        st.warning("⏹️ Pemrosesan AI & ML dihentikan secara paksa oleh pengguna.")
                    else:
                        st.error("❌ Gagal memproses pipeline data. Cek kunci GEMINI_API_KEY di sesi / file .env dan ketersediaan model SVM.")
                    with st.expander("📋 Log Kesalahan"):
                        st.code(stdout or stderr, language="text")
            except Exception as e_s2:
                status_ml.update(label=f"❌ Gagal memproses: {e_s2}", state="error", expanded=True)
                st.error(f"❌ Terjadi kesalahan saat menjalankan pipeline AI & ML: {e_s2}")

# =====================================================================
# TAB 3: REVIEW DATA
# =====================================================================
with tab_review:
    c_tab3_h1, c_tab3_h2 = st.columns([4, 1])
    with c_tab3_h1:
        st.subheader("📋 Tahapan 3: Review Data & Kontrol Kualitas")
        st.markdown("Transparansi data lengkap dari platform sumber beserta filter batas skor keyakinan (*confidence score*) dan fasilitas ekspor/impor Excel terkoreksi.")
    with c_tab3_h2:
        if st.button("🔄 Muat Ulang Data", key="btn_refresh_tab3_top", use_container_width=True, help="Segarkan seluruh data live dari database"):
            st.rerun()
    
    # 5.0 Formasi Tabel Live Lengkap (13 Kolom)
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
    with cr1: st.metric("📦 Total Mention", f"{total_volume_rev:,}")
    with cr2: st.metric("👥 Akun Unik", f"{unique_users_rev:,}")
    with cr3: st.metric("🟢 Sentimen Positif", f"{pct_pos_r:.1f}%", delta=f"{pos_cnt_r:,} data")
    with cr4: st.metric("🔴 Sentimen Negatif", f"{pct_neg_r:.1f}%", delta=f"{neg_cnt_r:,} data", delta_color="inverse")
    with cr5: st.metric("🔵 Sentimen Netral", f"{pct_neu_r:.1f}%", delta=f"{neu_cnt_r:,} data", delta_color="off")

    # Distribusi Data per Platform Sumber (dengan Logo/Icon)
    if 'source_platform' in df_reviewed_final.columns and not df_reviewed_final.empty:
        tw_cnt_r = int(df_reviewed_final['source_platform'].astype(str).str.contains('Twitter', case=False, na=False).sum())
        ig_cnt_r = int(df_reviewed_final['source_platform'].astype(str).str.contains('Instagram', case=False, na=False).sum())
        li_cnt_r = int(df_reviewed_final['source_platform'].astype(str).str.contains('LinkedIn', case=False, na=False).sum())
        web_cnt_r = int(df_reviewed_final['source_platform'].astype(str).str.contains('Website|News|Portal', case=False, na=False).sum())
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
                    df_rev_copy['date_parsed'] = pd.to_datetime(df_rev_copy['date'], errors='coerce').dt.date
                    df_trend = df_rev_copy.groupby(['date_parsed', 'sentiment_label']).size().reset_index(name='count')
                    fig_tr = px.line(
                        df_trend, x='date_parsed', y='count', color='sentiment_label',
                        color_discrete_map={'Positif': '#2D6A4F', 'Netral': '#4682B4', 'Negatif': '#B00020'},
                        line_shape='spline', height=260
                    )
                    fig_tr.update_layout(margin=dict(l=10, r=10, t=10, b=10))
                    st.plotly_chart(fig_tr, use_container_width=True)
                except Exception:
                    st.info("Format tanggal belum dapat diproses untuk grafik tren.")
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
            st.plotly_chart(fig_rev_pie, use_container_width=True)

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
                st.plotly_chart(fig_kw, use_container_width=True)
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

# =====================================================================
# TAB 4: VISUALISASI & ANALISIS DASHBOARD
# =====================================================================
with tab_viz:
    st.subheader("📊 Tahapan 4: Visualisasi & Analisis Dashboard Eksekutif")
    st.markdown("Pengaturan kriteria analisis sentimen, perumusan narasi AI 250+ kata, dan cetak laporan resmi berformat PDF.")
    
    df_base_viz = st.session_state.get('df_reviewed_final', df_all).copy()
    
    # 6.1 Pengaturan Analisis
    st.markdown("### ⚙️ Pengaturan Parameter Analisis")
    
    # Ambil riwayat terpisah untuk kata kunci, hashtag, dan user profile
    try:
        if hasattr(db_manager, 'ambil_riwayat_terpisah'):
            hist_sep = db_manager.ambil_riwayat_terpisah()
        else:
            hist_sep = {"keywords": [], "hashtags": [], "profiles": []}
    except Exception:
        hist_sep = {"keywords": [], "hashtags": [], "profiles": []}

    kw_options = hist_sep.get("keywords", [])
    ht_options = hist_sep.get("hashtags", [])
    pr_options = hist_sep.get("profiles", [])

    col_h1, col_h2, col_h3 = st.columns(3)
    with col_h1:
        selected_kw = st.multiselect(
            "🔍 Riwayat Kata Kunci:",
            options=kw_options,
            default=kw_options[:1] if kw_options else None,
            help="Pilih satu atau lebih kata kunci riwayat (opsional)."
        )
    with col_h2:
        selected_ht = st.multiselect(
            "🏷️ Riwayat Tagar / Hashtag:",
            options=ht_options,
            default=None,
            help="Pilih satu atau lebih hashtag riwayat (opsional)."
        )
    with col_h3:
        selected_pr = st.multiselect(
            "👥 Riwayat User Profile:",
            options=pr_options,
            default=None,
            help="Pilih satu atau lebih username/profil riwayat (opsional)."
        )

    # Rentang tanggal
    if not df_base_viz.empty and 'date' in df_base_viz.columns:
        try:
            df_base_viz['date_parsed'] = pd.to_datetime(df_base_viz['date'], errors='coerce').dt.date
            v_dates = df_base_viz['date_parsed'].dropna()
            min_d = v_dates.min() if not v_dates.empty else datetime.date.today() - datetime.timedelta(days=30)
            max_d = v_dates.max() if not v_dates.empty else datetime.date.today()
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

    # Filter berdasarkan rentang tanggal
    if isinstance(viz_date_range, tuple) and len(viz_date_range) == 2:
        df_viz_filtered = df_viz_filtered[
            (df_viz_filtered['date_parsed'] >= viz_date_range[0]) & 
            (df_viz_filtered['date_parsed'] <= viz_date_range[1])
        ]

    # Gabungkan istilah pencarian dari 3 multiselect (opsional / tidak wajib terisi semua, cukup minimal 1)
    selected_search_terms = []
    if selected_kw:
        for k in selected_kw:
            ck = str(k).strip().lower().lstrip("#@")
            if ck and ck not in selected_search_terms:
                selected_search_terms.append(ck)
    if selected_ht:
        for h in selected_ht:
            ch = str(h).strip().lower().lstrip("#@")
            if ch and ch not in selected_search_terms:
                selected_search_terms.append(ch)
    if selected_pr:
        for p in selected_pr:
            cp = str(p).strip().lower().lstrip("#@")
            if cp and cp not in selected_search_terms:
                selected_search_terms.append(cp)

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
    total_cleaned_viz = len(df_viz_cleaned)
    sentiment_counts_viz = df_viz_cleaned['sentiment_label'].value_counts() if not df_viz_cleaned.empty else pd.Series()
    total_labelled_viz = df_viz_cleaned['sentiment_label'].notna().sum() if not df_viz_cleaned.empty else 0
    
    if total_labelled_viz > 0:
        persen_pos_v = (df_viz_cleaned['sentiment_label'] == 'Positif').sum() / total_labelled_viz * 100
        persen_neu_v = (df_viz_cleaned['sentiment_label'] == 'Netral').sum() / total_labelled_viz * 100
        persen_neg_v = (df_viz_cleaned['sentiment_label'] == 'Negatif').sum() / total_labelled_viz * 100
        
        pos_cnt_v = int((df_viz_cleaned['sentiment_label'] == 'Positif').sum())
        neu_cnt_v = int((df_viz_cleaned['sentiment_label'] == 'Netral').sum())
        neg_cnt_v = int((df_viz_cleaned['sentiment_label'] == 'Negatif').sum())
        
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
    with mv1: st.metric("📦 Total Mention", f"{total_volume_viz:,}")
    with mv2: st.metric("👥 Akun Unik", f"{unique_users_v:,}")
    with mv3: st.metric("🟢 Sentimen Positif", f"{persen_pos_v:.1f}%", delta=f"{pos_cnt_v:,} data")
    with mv4: st.metric("🔴 Sentimen Negatif", f"{persen_neg_v:.1f}%", delta=f"{neg_cnt_v:,} data", delta_color="inverse")
    with mv5: st.metric("🔵 Sentimen Netral", f"{persen_neu_v:.1f}%", delta=f"{neu_cnt_v:,} data", delta_color="off")

    # Distribusi Data per Platform Sumber (dengan Logo/Icon)
    if 'source_platform' in df_viz_filtered.columns and not df_viz_filtered.empty:
        tw_cnt_v = int(df_viz_filtered['source_platform'].astype(str).str.contains('Twitter', case=False, na=False).sum())
        ig_cnt_v = int(df_viz_filtered['source_platform'].astype(str).str.contains('Instagram', case=False, na=False).sum())
        li_cnt_v = int(df_viz_filtered['source_platform'].astype(str).str.contains('LinkedIn', case=False, na=False).sum())
        web_cnt_v = int(df_viz_filtered['source_platform'].astype(str).str.contains('Website|News|Portal', case=False, na=False).sum())
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
            df_tr = df_viz_cleaned.groupby(['date_parsed', 'sentiment_label']).size().reset_index(name='count')
            fig_tr = px.line(df_tr, x='date_parsed', y='count', color='sentiment_label',
                             color_discrete_map={'Positif': '#2D6A4F', 'Netral': '#4682B4', 'Negatif': '#B00020'},
                             line_shape='spline', height=260)
            fig_tr.update_layout(margin=dict(l=10, r=10, t=10, b=10))
            st.plotly_chart(fig_tr, use_container_width=True)
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
            st.plotly_chart(fig_p, use_container_width=True)
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
            st.plotly_chart(fig_kw_v, use_container_width=True)
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

    if 'ai_narrative_viz_cache' not in st.session_state:
        st.session_state['ai_narrative_viz_cache'] = ""

    if total_cleaned_viz < 100:
        st.warning(
            "⚠️ **Data tidak cukup untuk menghasilkan narasi analisis. Minimal dibutuhkan 100 baris data yang relevan.** "
            f"(Jumlah data CLEANED saat ini: **{total_cleaned_viz}** baris).\n\n"
            "**Rekomendasi:** Silakan jalankan penarikan data baru di Tahapan 1 dan proses AI di Tahapan 2."
        )
        st.session_state['ai_narrative_viz_cache'] = ""
    else:
        if selected_search_terms:
            fokus_kebijakan_txt = ", ".join(selected_search_terms)
        else:
            fokus_kebijakan_txt = f"isu publik dengan kata kunci ({top_kw_str})"

        if gemini_is_out:
            st.error(
                "🚨 **Mohon maaf untuk sementara waktu fitur pemrosesan AI tidak dapat digunakan karena kuota token Gemini AI telah HABIS "
                "untuk penggunaan lebih lanjut dapat menghubungi Mrs Prof. Tuti Rachmawati, PhD - Universitas Parahyangan**"
            )
            st.button("🔄 Perbarui Analisis Narasi (Gemini AI)", type="primary", disabled=True, help="Kuota token Gemini AI habis. Fitur AI dinonaktifkan sementara.")
        else:
            if st.button("🔄 Perbarui Analisis Narasi (Gemini AI)", type="primary", key="btn_gen_nlg_tab4"):
                with st.spinner(f"Menganalisis isu '{fokus_kebijakan_txt}' & menyusun narasi minimal 250 kata..."):
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
                    st.session_state['ai_narrative_viz_cache'] = narrative_res
                
        if st.session_state['ai_narrative_viz_cache']:
            st.markdown(st.session_state['ai_narrative_viz_cache'])
        else:
            st.info("Klik tombol **🔄 Perbarui Analisis Narasi** di atas untuk menghasilkan ringkasan eksekutif.")

    # 6.3 Print Hasil Analisis (PDF Export)
    st.divider()
    st.markdown("### 📄 Export Laporan PDF")
    st.markdown("Cetak laporan PDF lengkap yang mencakup Informasi Data Scraping (6.1), Visualisasi Review Data (5.2), dan Narasi Eksekutif AI (6.2).")

    if not PDF_LIBS_OK:
        st.warning(f"⚠️ Library PDF belum lengkap. Install via: `pip install reportlab matplotlib`\nDetail: {PDF_IMPORT_ERROR_MSG}")
    else:
        _pdf_report_buf = None
        if st.button("📥 Susun & Download Laporan PDF ", type="primary", key="btn_build_pdf_tab4"):
            with st.spinner("Menyusun PDF Laporan Eksekutif + Grafik Visual..."):
                pdf_metrics = {
                    "total_volume": total_volume_viz,
                    "sentiment_dominant": dominant_viz,
                    "total_engagement": tot_engagement_v,
                    "total_sentiment_labelled": total_labelled_viz,
                    "persen_pos": persen_pos_v,
                    "persen_neu": persen_neu_v,
                    "persen_neg": persen_neg_v,
                    "pos_count": pos_cnt_v,
                    "neu_count": neu_cnt_v,
                    "neg_count": neg_cnt_v,
                }
                
                try:
                    with open(CONFIG_FILE, 'r') as f:
                        cfg_pdf = json.load(f)
                except Exception:
                    cfg_pdf = {}
                    
                try:
                    from reportlab.lib.pagesizes import A4
                    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
                    from reportlab.lib.units import cm
                    from reportlab.lib import colors
                    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, Table, TableStyle, PageBreak
                    
                    buf_p = BytesIO()
                    doc_p = SimpleDocTemplate(buf_p, pagesize=A4, leftMargin=2*cm, rightMargin=2*cm, topMargin=2*cm, bottomMargin=2.5*cm, title='Laporan Analisis Sentimen Kebijakan', author='AI Sentimen App')
                    story_p = []
                    styles_p = getSampleStyleSheet()
                    
                    sT = ParagraphStyle('T', parent=styles_p['Title'], fontSize=18, alignment=1, textColor=colors.HexColor('#1a365d'))
                    sH1 = ParagraphStyle('H1', parent=styles_p['Heading1'], fontSize=14, textColor=colors.HexColor('#1a365d'), spaceBefore=10)
                    sH2 = ParagraphStyle('H2', parent=styles_p['Heading2'], fontSize=11, textColor=colors.HexColor('#2c5282'), spaceBefore=6)
                    sB = ParagraphStyle('B', parent=styles_p['BodyText'], fontSize=9, leading=13, alignment=4)

                    def _pn(canvas, d):
                        canvas.saveState()
                        canvas.setFont('Helvetica', 8); canvas.setFillColor(colors.grey)
                        canvas.drawCentredString(A4[0]/2.0, 1.2*cm, f'Halaman {d.page}')
                        canvas.drawString(2*cm, 1.2*cm, 'Laporan Analisis Sentimen Kebijakan Publik — AI Powered')
                        canvas.restoreState()

                    story_p.append(Paragraph('LAPORAN ANALISIS SENTIMEN KEBIJAKAN PUBLIK', sT))
                    story_p.append(Spacer(1, 0.4*cm))
                    tgl_s = datetime.datetime.now().strftime('%d %B %Y — %H:%M WIB')
                    story_p.append(Paragraph(f'Tanggal Laporan: <b>{tgl_s}</b>', ParagraphStyle('Sub', parent=styles_p['Normal'], alignment=1)))
                    story_p.append(Spacer(1, 0.8*cm))
                    
                    t_m = Table([
                        ['Total Volume Data', 'Sentimen Dominan', 'Total Engagement'],
                        [f"{pdf_metrics['total_volume']:,}", str(pdf_metrics['sentiment_dominant']), f"{pdf_metrics['total_engagement']:,}"]
                    ], colWidths=[5.5*cm]*3, style=TableStyle([
                        ('BACKGROUND',(0,0),(-1,0),colors.HexColor('#1a365d')),('TEXTCOLOR',(0,0),(-1,0),colors.white),
                        ('FONTNAME',(0,0),(-1,0),'Helvetica-Bold'),('ALIGN',(0,0),(-1,-1),'CENTER'),
                        ('GRID',(0,0),(-1,-1),0.3,colors.lightgrey)
                    ]))
                    story_p.append(t_m)
                    story_p.append(PageBreak())

                    story_p.append(Paragraph('BAB I — PENGATURAN TARGET SCRAPING & KEYSEARCH (6.1)', sH1))
                    story_p.append(Paragraph('Ringkasan konfigurasi target scraping dan pilihan riwayat keysearch:', sB))
                    story_p.append(Spacer(1, 0.2*cm))
                    
                    gen_pdf = (cfg_pdf or {}).get('config', {}).get('general', {})
                    t_cfg_p = Table([
                        [Paragraph('<b>Target Keysearch / Riwayat</b>', sB), Paragraph(', '.join(selected_search_terms) if selected_search_terms else ', '.join(gen_pdf.get('keywords', ['-'])), sB)],
                        [Paragraph('<b>Target Profil Akun</b>', sB), Paragraph(', '.join(gen_pdf.get('profiles', ['-'])), sB)],
                        [Paragraph('<b>Target Hashtag</b>', sB), Paragraph(', '.join(gen_pdf.get('hashtags', ['-'])), sB)],
                        [Paragraph('<b>Rentang Waktu Periode</b>', sB), Paragraph(f"{viz_date_range[0]} s/d {viz_date_range[1]}" if isinstance(viz_date_range, tuple) else "-", sB)],
                    ], colWidths=[5*cm, 11*cm], style=TableStyle([('GRID',(0,0),(-1,-1),0.3,colors.lightgrey)]))
                    story_p.append(t_cfg_p)
                    story_p.append(Spacer(1, 0.5*cm))

                    story_p.append(Paragraph('BAB II — RINGKASAN REVIEW DATA (5.2)', sH1))
                    story_p.append(Paragraph(f'Hasil review data live: <b>{len(df_base_viz):,}</b> data diterima, <b>{pdf_metrics["total_sentiment_labelled"]:,}</b> terlabel sentimen.', sB))
                    story_p.append(Spacer(1, 0.2*cm))
                    
                    pie_bytes_p = _chart_pie_sentimen_pdf(pdf_metrics['pos_count'], pdf_metrics['neu_count'], pdf_metrics['neg_count'])
                    if pie_bytes_p:
                        story_p.append(Image(pie_bytes_p, width=12*cm, height=9*cm, hAlign='CENTER'))
                    story_p.append(PageBreak())

                    story_p.append(Paragraph('BAB III — VISUALISASI ANALISIS DASHBOARD', sH1))
                    tr_bytes_p = _chart_tren_harian_pdf(df_viz_cleaned)
                    if tr_bytes_p:
                        story_p.append(Paragraph('3.1 Grafik Tren Sentimen Harian', sH2))
                        story_p.append(Image(tr_bytes_p, width=16*cm, height=7.5*cm, hAlign='CENTER'))
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

                    story_p.append(Paragraph('BAB IV — RINGKASAN EKSEKUTIF NARASI AI', sH1))
                    narasi_pdf_txt = st.session_state.get('ai_narrative_viz_cache', '')
                    if not narasi_pdf_txt:
                        story_p.append(Paragraph('<i>Narasi AI belum di-generate di dashboard. Silakan klik tombol Perbarui Analisis Narasi terlebih dahulu.</i>', sBodyJustified))
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

                    doc_p.build(story_p, onFirstPage=_pn, onLaterPages=_pn)
                    buf_p.seek(0)
                    _pdf_report_buf = buf_p
                except Exception as e_pdf_gen:
                    st.error(f"❌ Gagal menyusun PDF: {e_pdf_gen}")
                    _pdf_report_buf = None

        if _pdf_report_buf is not None:
            st.download_button(
                label="⬇️ Unduh PDF Laporan Resmi",
                data=_pdf_report_buf.getvalue(),
                file_name=f"Laporan_Sentimen_Kebijakan_{datetime.datetime.now().strftime('%Y%m%d_%H%M')}.pdf",
                mime="application/pdf",
                type="primary",
                key="btn_dl_pdf_tab4_final"
            )
