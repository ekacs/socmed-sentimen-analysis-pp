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

def get_supabase_dashboard_url():
    db_url = os.getenv("DATABASE_URL", "")
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

DB_FILE = 'sentimen_kebijakan.db'
CONFIG_FILE = 'target_config.json'
MAX_SUPABASE_ROWS = 666666

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

def extract_top_keywords(df, num_words=5):
    text_list = []
    if df is None or df.empty:
        return "Tidak ada kata kunci dominan"
        
    for _, row in df.iterrows():
        val_cleaned = row.get('cleaned_text')
        val_raw = row.get('raw_text')
        t = ""
        if pd.notna(val_cleaned) and val_cleaned is not None:
            t = str(val_cleaned).strip()
        elif pd.notna(val_raw) and val_raw is not None:
            t = str(val_raw).strip()
            
        if t and t.lower() != 'nan':
            text_list.append(t.lower())
            
    stopwords = {
        'dan', 'di', 'ke', 'dari', 'ini', 'itu', 'yang', 'saya', 'kamu', 'dia', 'kami', 'kita', 'mereka', 
        'adalah', 'ada', 'dengan', 'untuk', 'pada', 'atau', 'juga', 'sudah', 'telah', 'bisa', 'dapat', 'akan', 
        'ingin', 'hari', 'nih', 'dah', 'sangat', 'sekali', 'saja', 'karena', 'tapi', 'namun', 'krl', 'commuter', 
        'line', 'mrt', 'lrt', 'transjakarta', 'bus', 'kereta', 'ikn', 'ibu', 'kota', 'yang', 'untuk', 'pada', 
        'semua', 'ada', 'banyak', 'sudah', 'telah', 'bisa', 'dapat', 'tidak', 'gak', 'enggak', 'pun', 'lah',
        'kok', 'sih', 'ya', 'aja', 'dgn', 'yg', 'utk', 'klo', 'kalo', 'lu', 'gw', 'gua', 'lu', 'buat', 'bgt'
    }
    
    words = []
    for text in text_list:
        for char in ".,!?;:()[]{}'\"-@#/*":
            text = text.replace(char, " ")
        for word in text.split():
            word = word.strip()
            if word and word not in stopwords and len(word) > 2:
                words.append(word)
                
    counter = collections.Counter(words)
    top_common = counter.most_common(num_words)
    return ", ".join([f"{w[0]} ({w[1]})" for w in top_common]) if top_common else "Tidak ada kata kunci dominan"

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
    st.markdown("Tentukan parameter target penarikan data publik dari Twitter (X), Instagram, LinkedIn, dan Portal Berita.")
    
    # 3.1 Cek Kapasitas Database Supabase
    try:
        if hasattr(db_manager, 'hitung_total_baris'):
            total_db_rows = db_manager.hitung_total_baris()
        else:
            total_db_rows = len(df_all) if not df_all.empty else 0
    except Exception:
        total_db_rows = len(df_all) if not df_all.empty else 0

    db_is_full = total_db_rows >= MAX_SUPABASE_ROWS
    
    c_cap1, c_cap2 = st.columns([3, 1])
    with c_cap1:
        st.caption(f"📦 Status Kapasitas Storage Database: **{total_db_rows:,}** / **{MAX_SUPABASE_ROWS:,}** baris tersimpan.")
    with c_cap2:
        st.progress(min(1.0, total_db_rows / MAX_SUPABASE_ROWS))
        
    if db_is_full:
        st.error(
            "🚨 **Mohon maaf untuk sementara waktu mesin tidak dapat digunakan karena penyimpanan database telah penuh "
            "untuk penggunaan lebih lanjut dapat menghubungi Mrs Prof. Tuti Rachmawati, PhD - Universitas Parahyangan**"
        )
    
    # Panduan Twitter Advanced Search
    with st.expander("📖 Panduan Sintaks Pencarian Lanjutan (Twitter Advanced Search Operator)", expanded=False):
        st.markdown(
            "Anda dapat memasukkan kombinasi operator pencarian lanjutan di bidang **Target Kata Kunci** sesuai panduan "
            "[Twitter Advanced Search Guide](https://github.com/igorbrigadir/twitter-advanced-search):\n\n"
            "| Operator | Fungsi / Deskripsi | Contoh Penggunaan |\n"
            "| :--- | :--- | :--- |\n"
            "| `\"frasa persis\"` | Mencari frasa kata kunci yang persis berurutan | `\"Ibu Kota Baru\"` |\n"
            "| `kata1 kata2` | Mencari tweet yang mengandung KEDUA kata tersebut | `IKN Nusantara` |\n"
            "| `from:username` | Menarik tweet yang ditulis oleh akun tertentu | `from:jokowi` |\n"
            "| `to:username` | Menarik tweet balasan (reply) ke akun tertentu | `to:kemenpupr` |\n"
            "| `since:YYYY-MM-DD` | Tweet yang dibuat SEJAK tanggal tertentu | `since:2026-07-01` |\n"
            "| `until:YYYY-MM-DD` | Tweet yang dibuat SAMPAI tanggal tertentu | `until:2026-07-13` |\n"
            "| `min_faves:N` | Minimal jumlah Suka (Likes) | `min_faves:100` |\n"
            "| `min_retweets:N` | Minimal jumlah Retweet/Share | `min_retweets:50` |\n"
            "| `-kata` | Mengecualikan tweet yang mengandung kata tertentu | `IKN -kaltim` |\n"
            "| `lang:id` | Membatasi hasil hanya tweet berbahasa Indonesia | `subsidi lang:id` |\n"
        )

    # Muat Konfigurasi Target dari target_config.json
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                current_config = json.load(f)
        except Exception:
            current_config = {}
    else:
        current_config = {}
        
    general_cfg = current_config.get("config", {}).get("general", {})
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
        "portal_berita": "Portal Berita"
    }
    rev_mapping = {v: k for k, v in mapping_source_types.items()}
    platform_options = ["Twitter (X)", "Instagram", "LinkedIn", "Portal Berita"]
    
    default_selected = [mapping_source_types.get(s) for s in raw_source_list if mapping_source_types.get(s)]
    if not default_selected: default_selected = ["Twitter (X)"]

    selected_platforms = st.multiselect(
        "Pilih Platform Sasaran Scraping (bisa pilih lebih dari satu):",
        options=platform_options,
        default=default_selected
    )

    with st.form("form_target_config"):
        st.write(f"**Konfigurasi Parameter Target Scraping**")
        col_s1, col_s2 = st.columns(2)
        with col_s1:
            default_start = general_cfg.get("start_date", "2026-07-06")
            try:
                start_date_input = st.date_input("Tanggal Mulai Target", value=datetime.datetime.strptime(default_start, "%Y-%m-%d").date())
            except Exception:
                start_date_input = st.date_input("Tanggal Mulai Target", value=datetime.date.today() - datetime.timedelta(days=7))
        with col_s2:
            default_end = general_cfg.get("end_date", "2026-07-13")
            try:
                end_date_input = st.date_input("Tanggal Akhir Target", value=datetime.datetime.strptime(default_end, "%Y-%m-%d").date())
            except Exception:
                end_date_input = st.date_input("Tanggal Akhir Target", value=datetime.date.today())

        default_keywords = ", ".join(general_cfg.get("keywords", ["mbg"]))
        default_profiles = ", ".join(general_cfg.get("profiles", ["jokowi", "kemenpupr"]))
        default_hashtags = ", ".join(general_cfg.get("hashtags", ["#IKNNusantara"]))
        fallback_max = general_cfg.get("max_results", 100)

        keywords_input = st.text_input("Target Kata Kunci / Search Key (pisahkan dengan koma):", value=default_keywords, help="Dapat menggunakan operator pencarian lanjutan Twitter seperti tabel panduan di atas.")
        profiles_input = st.text_input("Target Profil Akun (pisahkan dengan koma):", value=default_profiles)
        hashtags_input = st.text_input("Target Tagar/Hashtag (pisahkan dengan koma):", value=default_hashtags)

        st.markdown("#### 📊 Batas Maksimal Data per Platform")
        def get_platform_default(field_name: str, fallback_val: int) -> int:
            val = general_cfg.get(field_name)
            if val is None: val = fallback_max if fallback_max else fallback_val
            try: return int(val)
            except (TypeError, ValueError): return fallback_val

        max_twitter = st.slider("🐦 Twitter (X) — Batas cuitan:", 10, 5000, get_platform_default("max_results_twitter", 500), 10) if "Twitter (X)" in selected_platforms else None
        max_instagram = st.slider("📸 Instagram — Batas postingan per profil:", 5, 500, get_platform_default("max_results_instagram", 100), 5) if "Instagram" in selected_platforms else None
        max_linkedin = st.slider("💼 LinkedIn — Batas postingan:", 5, 500, get_platform_default("max_results_linkedin", 100), 5) if "LinkedIn" in selected_platforms else None
        
        max_news = None
        news_portals_input = None
        if "Portal Berita" in selected_platforms:
            max_news = st.slider("📰 Portal Berita — Batas artikel per domain:", 5, 200, get_platform_default("max_results_news", 50), 5)
            raw_news_urls = general_cfg.get("news_portal_urls", ["https://www.kompas.com/"])
            default_news_str = ", ".join(raw_news_urls) if isinstance(raw_news_urls, list) else str(raw_news_urls)
            news_portals_input = st.text_input("📰 URL Portal Berita (pisahkan koma):", value=default_news_str)

        btn_save_config = st.form_submit_button("💾 Simpan Konfigurasi Target")
        if btn_save_config:
            if not selected_platforms:
                st.error("❌ Pilih setidaknya satu platform sasaran.")
            else:
                source_types_to_save = [rev_mapping[sp] for sp in selected_platforms if sp in rev_mapping]
                general_obj = {
                    "start_date": start_date_input.strftime("%Y-%m-%d"),
                    "end_date": end_date_input.strftime("%Y-%m-%d"),
                    "keywords": [k.strip() for k in keywords_input.split(",") if k.strip()],
                    "profiles": [p.strip() for p in profiles_input.split(",") if p.strip()],
                    "hashtags": [h.strip() for h in hashtags_input.split(",") if h.strip()],
                    "max_results": fallback_max,
                    "max_results_twitter": max_twitter or get_platform_default("max_results_twitter", 500),
                    "max_results_instagram": max_instagram or get_platform_default("max_results_instagram", 100),
                    "max_results_linkedin": max_linkedin or get_platform_default("max_results_linkedin", 100),
                    "max_results_news": max_news or get_platform_default("max_results_news", 50),
                    "news_portal_urls": [u.strip() for u in (news_portals_input or "https://www.kompas.com/").split(",") if u.strip()]
                }
                new_config = {"source_types": source_types_to_save, "config": {"general": general_obj}}
                with open(CONFIG_FILE, 'w') as f:
                    json.dump(new_config, f, indent=4)
                st.success("✅ Konfigurasi target berhasil disimpan!")

    st.divider()
    st.markdown("### 🚀 Eksekusi Penarikan Data")
    if db_is_full:
        st.button("🚀 Jalankan Penarikan Data Sekarang", type="primary", disabled=True, help="Database penuh (maks 666.666 baris). Penarikan data dinonaktifkan sementara.")
    else:
        if st.button("🚀 Jalankan Penarikan Data Sekarang", type="primary", key="btn_run_scraper_main"):
            with st.status("🚀 Menghubungkan ke Apify Cloud & menarik data mentah...", expanded=True) as status_s:
                try:
                    result = subprocess.run([sys.executable, "01_run_scraper.py"], capture_output=True, text=True, check=True)
                    status_s.update(label="✅ Penarikan data selesai!", state="complete", expanded=False)
                    st.success("✅ Penarikan data mentah selesai. Data siap diproses di Tahapan 2.")
                    with st.expander("📋 Log Scraper"):
                        st.code(result.stdout, language="text")
                except subprocess.CalledProcessError as e:
                    status_s.update(label=f"❌ Gagal (Exit code: {e.returncode})", state="error", expanded=True)
                    st.error("❌ Gagal menjalankan scraper. Cek token APIFY_API_TOKEN di file .env.")
                    with st.expander("📋 Log Kesalahan"):
                        st.code(e.stdout or e.stderr, language="text")

# =====================================================================
# TAB 2: PROSES AI & KLASIFIKASI ML
# =====================================================================
with tab_ml:
    st.subheader("🧠 Tahapan 2: Proses AI (Gemini EYD) & Klasifikasi ML (SVM)")
    st.info(
        "ℹ️ **Ketentuan Prapemrosesan Otomatis:**\n\n"
        "Sebelum proses AI (Gemini EYD) dan klasifikasi sentimen (SVM) dijalankan, sistem secara otomatis melakukan "
        "**pembersihan data duplikat** pada data scraping mentah (data dengan `username` dan `raw_text` yang persis sama, "
        "hanya mempertahankan baris dengan `created_at` / `date` paling awal)."
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

    st.divider()
    btn_run_pipeline = st.button("🧠 Jalankan Proses AI & ML Sekarang", type="primary", use_container_width=True, key="btn_run_pipeline_tab2")
    
    if btn_run_pipeline:
        with st.status("🧠 Melakukan pembersihan duplikat RAW, standardisasi EYD (Gemini), & klasifikasi SVM...", expanded=True) as status_ml:
            try:
                result = subprocess.run([sys.executable, "01_pipeline_data.py"], capture_output=True, text=True, check=True)
                status_ml.update(label="✅ Proses AI & ML Selesai!", state="complete", expanded=False)
                st.success("✅ Proses prapemrosesan AI & klasifikasi ML selesai dengan sukses! Data siap di-review di Tahapan 3.")
                with st.expander("📋 Log Detail Pemrosesan Pipeline"):
                    st.code(result.stdout, language="text")
                    if result.stderr: st.code(result.stderr, language="text")
            except subprocess.CalledProcessError as e:
                status_ml.update(label=f"❌ Gagal (Exit code: {e.returncode})", state="error", expanded=True)
                st.error("❌ Gagal memproses pipeline data. Cek file .env (GEMINI_API_KEY) dan ketersediaan model SVM.")
                with st.expander("📋 Log Kesalahan"):
                    st.code(e.stdout or e.stderr, language="text")

# =====================================================================
# TAB 3: REVIEW DATA
# =====================================================================
with tab_review:
    st.subheader("📋 Tahapan 3: Review Data & Kontrol Kualitas")
    st.markdown("Transparansi data lengkap dari platform sumber beserta filter batas skor keyakinan (*confidence score*) dan fasilitas ekspor/impor Excel terkoreksi.")
    
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
    st.markdown("### ⚙️ 5.1 Pengaturan Koreksi & Ambang Keyakinan Data")
    
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
    st.markdown("### 📊 5.2 Ringkasan Visualisasi Hasil Review Data")
    
    total_raw_live = len(df_live_full)
    total_acc = len(df_reviewed_final)
    total_rej = total_raw_live - total_acc
    
    cr1, cr2, cr3 = st.columns(3)
    with cr1: st.metric("📦 Total Live Data", f"{total_raw_live:,}")
    with cr2: st.metric("✅ Data Diterima (Review)", f"{total_acc:,}")
    with cr3: st.metric("❌ Data Ditolak/Dieliminasi", f"{total_rej:,}", delta=f"-{total_rej}" if total_rej else None, delta_color="inverse")

    if not df_reviewed_final.empty:
        c_rev_chart1, c_rev_chart2 = st.columns([1, 1])
        with c_rev_chart1:
            sent_rev_counts = df_reviewed_final['sentiment_label'].value_counts().reset_index()
            sent_rev_counts.columns = ['Sentimen', 'Jumlah']
            fig_rev_pie = px.pie(
                sent_rev_counts, names='Sentimen', values='Jumlah', hole=0.4,
                color='Sentimen', color_discrete_map={'Positif': '#2D6A4F', 'Netral': '#4682B4', 'Negatif': '#B00020'}
            )
            fig_rev_pie.update_layout(title="Distribusi Sentimen Data Diterima", height=280)
            st.plotly_chart(fig_rev_pie, use_container_width=True)
            
        with c_rev_chart2:
            st.markdown("**Tabel Live Interaktif (13 Kolom Lengkap):**")
            df_disp = df_reviewed_final[[c for c in _all_cols_needed if c in df_reviewed_final.columns]].copy()
            df_disp.rename(columns=col_rename_map, inplace=True)
            st.dataframe(df_disp, use_container_width=True, height=280)

# =====================================================================
# TAB 4: VISUALISASI & ANALISIS DASHBOARD
# =====================================================================
with tab_viz:
    st.subheader("📊 Tahapan 4: Visualisasi & Analisis Dashboard Eksekutif")
    st.markdown("Pengaturan kriteria analisis sentimen, perumusan narasi AI 250+ kata, dan cetak laporan resmi berformat PDF.")
    
    df_base_viz = st.session_state.get('df_reviewed_final', df_all).copy()
    
    # 6.1 Pengaturan Analisis
    st.markdown("### ⚙️ 6.1 Pengaturan Parameter Analisis")
    
    try:
        if hasattr(db_manager, 'ambil_keysearch_history'):
            hist_records = db_manager.ambil_keysearch_history()
        else:
            hist_records = []
    except Exception:
        hist_records = []
    hist_labels = [h["display_label"] for h in hist_records if isinstance(h, dict) and "display_label" in h]
    
    col_an1, col_an2 = st.columns([2, 1])
    with col_an1:
        selected_hist = st.multiselect(
            "Riwayat Keysearch, User Profile, dan Hashtag Target:",
            options=hist_labels,
            default=hist_labels[:1] if hist_labels else None,
            help="Pilih satu atau lebih riwayat kombinasi pencarian untuk memfilter data analisis."
        )
    with col_an2:
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
            
        viz_date_range = st.date_input("Rentang Periode Data Scraping:", value=(min_d, max_d))
        
    btn_exec_analysis = st.button("🔍 Jalankan Analisis Sekarang", type="primary", key="btn_exec_viz")
    
    df_viz_filtered = df_base_viz.copy()

    # Filter berdasarkan rentang tanggal
    if isinstance(viz_date_range, tuple) and len(viz_date_range) == 2:
        df_viz_filtered = df_viz_filtered[
            (df_viz_filtered['date_parsed'] >= viz_date_range[0]) & 
            (df_viz_filtered['date_parsed'] <= viz_date_range[1])
        ]

    # Filter berdasarkan Riwayat Keysearch / Profil / Hashtag yang dipilih
    selected_search_terms = []
    if selected_hist:
        for h in hist_records:
            if h.get("display_label") in selected_hist:
                for field in ["keywords", "profiles", "hashtags"]:
                    val = h.get(field, "")
                    if val:
                        for term in str(val).split(","):
                            clean_term = term.strip().lower().lstrip("#@")
                            if clean_term and clean_term not in selected_search_terms:
                                selected_search_terms.append(clean_term)

    if selected_search_terms and not df_viz_filtered.empty:
        def _matches_keysearch(row):
            txt = (str(row.get('cleaned_text') or '') + ' ' + str(row.get('raw_text') or '')).lower()
            return any(st_term in txt for st_term in selected_search_terms)

        df_filtered_by_key = df_viz_filtered[df_viz_filtered.apply(_matches_keysearch, axis=1)]
        # Jika hasil filter tidak kosong, gunakan data terfilter
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

    mv1, mv2, mv3 = st.columns(3)
    with mv1:
        st.markdown(f'<div class="metric-card"><div class="metric-value">{total_volume_viz:,}</div><div class="metric-label">Total Volume Data (Cleaned: {total_cleaned_viz:,})</div></div>', unsafe_allow_html=True)
    with mv2:
        st.markdown(f'<div class="metric-card"><div class="metric-value">{dominant_viz}</div><div class="metric-label">Sentimen Dominan</div></div>', unsafe_allow_html=True)
    with mv3:
        st.markdown(f'<div class="metric-card"><div class="metric-value">{tot_engagement_v:,}</div><div class="metric-label">Total Engagement (Likes + Shares)</div></div>', unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # 6.2 Visualisasi Grafik & Narasi AI (NLG)
    col_chart_l, col_chart_r = st.columns([7, 3])
    with col_chart_l:
        st.subheader("📈 Tren Sentimen Publik Harian")
        if 'date_parsed' in df_viz_cleaned.columns and not df_viz_cleaned.empty:
            df_tr = df_viz_cleaned.groupby(['date_parsed', 'sentiment_label']).size().reset_index(name='count')
            fig_tr = px.line(df_tr, x='date_parsed', y='count', color='sentiment_label',
                             color_discrete_map={'Positif': '#2D6A4F', 'Netral': '#4682B4', 'Negatif': '#B00020'},
                             line_shape='spline', height=300)
            st.plotly_chart(fig_tr, use_container_width=True)
        else:
            st.info("Belum ada data sentimen terklasifikasi untuk membentuk grafik tren.")
            
    with col_chart_r:
        st.subheader("📊 Distribusi Sentimen")
        if total_labelled_viz > 0:
            df_p = pd.DataFrame({'Sentimen': ['Positif', 'Netral', 'Negatif'], 'Jumlah': [pos_cnt_v, neu_cnt_v, neg_cnt_v]})
            fig_p = px.pie(df_p, names='Sentimen', values='Jumlah', hole=0.4,
                           color='Sentimen', color_discrete_map={'Positif': '#2D6A4F', 'Netral': '#4682B4', 'Negatif': '#B00020'},
                           height=260)
            st.plotly_chart(fig_p, use_container_width=True)
        else:
            st.info("Belum ada data sentimen terklasifikasi.")

    st.divider()

    # 6.2 Narasi AI (NLG)
    st.subheader("📝 6.2 Ringkasan Eksekutif Narasi AI (NLG)")
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
        elif selected_hist:
            fokus_kebijakan_txt = ", ".join(selected_hist)
        else:
            fokus_kebijakan_txt = f"isu publik dengan kata kunci ({top_kw_str})"

        if st.button("🔄 Perbarui Analisis Narasi (Gemini AI)", type="primary", key="btn_gen_nlg_tab4"):
            with st.spinner(f"Menganalisis isu '{fokus_kebijakan_txt}' & menyusun narasi minimal 250 kata..."):
                narrative_res = generate_executive_summary(
                    total_data=total_cleaned_viz,
                    persen_negatif=round(persen_neg_v, 1),
                    persen_positif=round(persen_pos_v, 1),
                    persen_netral=round(persen_neu_v, 1),
                    top_keywords=top_kw_str,
                    contoh_cuitan=contoh_suara,
                    kebijakan_fokus=fokus_kebijakan_txt
                )
                st.session_state['ai_narrative_viz_cache'] = narrative_res
                
        if st.session_state['ai_narrative_viz_cache']:
            st.markdown(st.session_state['ai_narrative_viz_cache'])
        else:
            st.info("Klik tombol **🔄 Perbarui Analisis Narasi** di atas untuk menghasilkan ringkasan eksekutif.")

    # 6.3 Print Hasil Analisis (PDF Export)
    st.divider()
    st.markdown("### 📄 6.3 Print & Export Laporan PDF Resmi")
    st.markdown("Cetak laporan PDF lengkap yang mencakup Informasi Data Scraping (6.1), Visualisasi Review Data (5.2), dan Narasi Eksekutif AI (6.2).")

    if not PDF_LIBS_OK:
        st.warning(f"⚠️ Library PDF belum lengkap. Install via: `pip install reportlab matplotlib`\nDetail: {PDF_IMPORT_ERROR_MSG}")
    else:
        _pdf_report_buf = None
        if st.button("📥 Susun & Download Laporan PDF Resmi", type="primary", key="btn_build_pdf_tab4"):
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
                        [Paragraph('<b>Target Keysearch / Riwayat</b>', sB), Paragraph(', '.join(selected_hist) if selected_hist else ', '.join(gen_pdf.get('keywords', ['-'])), sB)],
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
