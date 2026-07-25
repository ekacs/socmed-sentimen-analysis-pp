import os
import re
import sys
import json
import datetime
import subprocess
import collections
import pandas as pd
import streamlit as st
import plotly.express as px
import db_manager

# Impor generator NLG
from nlg_generator import generate_executive_summary

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

# Jalankan buat_tabel() untuk memastikan basis data ter-inisialisasi
try:
    db_manager.buat_tabel()
except Exception as e:
    st.error(f"Gagal menginisialisasi basis data: {e}")

# 2. Injeksi CSS Kustom (Swiss Modern Estetika)
st.markdown("""
    <style>
        /* Sembunyikan footer, tapi biarkan header/menu (untuk pengaturan tema) */
        footer {visibility: hidden;}
        /* Sembunyikan tombol tutup sidebar di desktop agar selalu terbuka */
        @media (min-width: 768px) {
            [data-testid="collapsedControl"] { display: none !important; }
        }

        /* Tipografi & Warna Latar Belakang */
        html, body, [class*="css"] {
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background-color: var(--background-color);
            color: var(--text-color);
        }

        /* Kartu Metrik Kustom */
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

        /* Border Kontainer Grafis */
        div.stBox {
            border: 1px solid rgba(128, 128, 128, 0.2) !important;
            border-radius: 8px !important;
            background-color: var(--secondary-background-color) !important;
            padding: 1.5rem !important;
            box-shadow: 0 1px 3px rgba(0,0,0,0.02) !important;
        }

        /* Desain Tab */
        .stTabs [data-baseweb="tab-list"] {
            gap: 24px;
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
        .stTabs [data-baseweb="tab"]:hover {
            opacity: 1;
        }
        .stTabs [aria-selected="true"] {
            opacity: 1 !important;
            border-bottom-color: var(--primary-color) !important;
        }
        
        /* Tombol */
        .stButton>button {
            border-radius: 6px !important;
            font-weight: 600 !important;
        }
    </style>
""", unsafe_allow_html=True)

# 3. Fungsi Basis Data
def load_data_from_db():
    """
    Mengambil data dari database (SQLite/PostgreSQL).
    """
    return db_manager.baca_data_untuk_streamlit()

# 4. Fungsi Pembantu Analisis Teks (Top Keywords)
def extract_top_keywords(df, num_words=5):
    """
    Ekstraksi frekuensi kata kunci sederhana dari cleaned_text (atau raw_text jika cleaned kosong).
    """
    text_list = []
    for _, row in df.iterrows():
        t = row.get('cleaned_text') or row.get('raw_text') or ''
        if t:
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
        # Bersihkan tanda baca sederhana
        for char in ".,!?;:()[]{}'\"-@#/*":
            text = text.replace(char, " ")
        for word in text.split():
            word = word.strip()
            if word and word not in stopwords and len(word) > 2:
                words.append(word)
                
    counter = collections.Counter(words)
    top_common = counter.most_common(num_words)
    return ", ".join([f"{w[0]} ({w[1]})" for w in top_common]) if top_common else "Tidak ada kata kunci dominan"

# 5. Dashboard Header
st.title("🏛️ Pusat Analisis Sentimen Kebijakan Publik")
st.markdown("Dasbor eksekutif berbasis AI untuk memantau sentimen publik terhadap kebijakan publik.")
st.divider()

# 6. Memuat Data Aktual
df_all = load_data_from_db()

# Cek apakah database kosong
if df_all.empty:
    st.info("ℹ️ Basis data kosong atau belum ada data ditarik. Silakan gunakan menu **⚙️ Pengaturan Target** untuk memicu penarikan data pertama.")
    df_all = pd.DataFrame(columns=['tweet_id', 'date', 'username', 'raw_text', 'cleaned_text', 'sentiment_label', 'confidence_score', 'likes', 'retweets', 'status', 'source_platform'])

# 7. Sidebar Filter
st.sidebar.markdown("### 🎨 Pengaturan Tampilan & Sistem")
st.sidebar.info("💡 **Tips Tema:** Klik ikon **⋮** di sudut kanan atas layar, lalu pilih **Settings > Theme** untuk beralih antara *Light* dan *Dark Mode*.")

# Mode Penarikan Data (Scraping Mode)
mode_sekarang = db_manager.get_scraping_mode()
mode_pilihan = st.sidebar.radio(
    "🔄 Mode Penarikan Data (Scraping):",
    options=["Otomatis (Cronjob Harian)", "Manual (Hanya via Dasbor)"],
    index=0 if mode_sekarang == 'auto' else 1
)

new_mode = 'auto' if mode_pilihan == "Otomatis (Cronjob Harian)" else 'manual'
if new_mode != mode_sekarang:
    db_manager.set_scraping_mode(new_mode)
    st.sidebar.success(f"Mode berhasil diubah ke: {mode_pilihan}")

# Akses Database
st.sidebar.divider()
st.sidebar.markdown("### 🗄️ Akses Database Awan")
st.sidebar.link_button(
    "🌐 Buka Tabel Supabase",
    get_supabase_dashboard_url(),
    use_container_width=True,
    help="Buka editor tabel PostgreSQL Supabase secara instan."
)

st.sidebar.divider()
st.sidebar.header("📁 Filter Analisis Global")

# Filter Platform
platforms_available = df_all['source_platform'].unique().tolist() if not df_all.empty else ["Twitter", "Instagram", "LinkedIn", "News"]
platform_filter = st.sidebar.multiselect(
    "Pilih Platform Sumber:",
    options=platforms_available,
    default=platforms_available
)

# Filter Rentang Tanggal
if not df_all.empty and 'date' in df_all.columns:
    try:
        df_all['date_parsed'] = pd.to_datetime(df_all['date'], errors='coerce').dt.date
        df_all['date_parsed'] = df_all['date_parsed'].fillna(datetime.date.today())
        min_date = df_all['date_parsed'].min()
        max_date = df_all['date_parsed'].max()
        if min_date == max_date:
            min_date = max_date - datetime.timedelta(days=7)
    except Exception:
        df_all['date_parsed'] = datetime.date.today()
        min_date = datetime.date.today() - datetime.timedelta(days=7)
        max_date = datetime.date.today()
else:
    df_all['date_parsed'] = datetime.date.today()
    min_date = datetime.date.today() - datetime.timedelta(days=7)
    max_date = datetime.date.today()

date_range = st.sidebar.date_input(
    "Rentang Waktu:",
    value=(min_date, max_date)
)

# Filter Data Berdasarkan Seleksi Sidebar
if not df_all.empty:
    df_filtered = df_all[df_all['source_platform'].isin(platform_filter)]
    if isinstance(date_range, tuple) and len(date_range) == 2:
        df_filtered = df_filtered[
            (df_filtered['date_parsed'] >= date_range[0]) & 
            (df_filtered['date_parsed'] <= date_range[1])
        ]
else:
    df_filtered = df_all.copy()

# 8. Struktur Layout Tab Utama
tab3, tab1, tab2 = st.tabs(["⚙️ Pengaturan Target", "📊 Analitik Sentimen", "📑 Jejak Audit Data"])

# =====================================================================
# TAB 1: ANALITIK SENTIMEN
# =====================================================================
with tab1:
    if df_filtered.empty:
        st.warning("⚠️ Tidak ada data yang cocok dengan kriteria filter saat ini.")
    else:
        # Perhitungan Metrik Dinamis
        total_volume = len(df_filtered)
        
        # Sentimen
        sentiment_counts = df_filtered['sentiment_label'].value_counts()
        total_sentiment_labelled = df_filtered['sentiment_label'].notna().sum()
        
        # Hitung Persentase Sentimen
        if total_sentiment_labelled > 0:
            persen_neg = (df_filtered['sentiment_label'] == 'Negatif').sum() / total_sentiment_labelled * 100
            persen_pos = (df_filtered['sentiment_label'] == 'Positif').sum() / total_sentiment_labelled * 100
            persen_neu = (df_filtered['sentiment_label'] == 'Netral').sum() / total_sentiment_labelled * 100
            
            neg_count = (df_filtered['sentiment_label'] == 'Negatif').sum()
            pos_count = (df_filtered['sentiment_label'] == 'Positif').sum()
            neu_count = (df_filtered['sentiment_label'] == 'Netral').sum()
            
            # Tentukan Dominasi
            max_idx = sentiment_counts.idxmax() if not sentiment_counts.empty else "N/A"
            max_val = sentiment_counts.max() / total_sentiment_labelled * 100 if not sentiment_counts.empty else 0.0
            sentiment_dominant = f"{max_idx} ({max_val:.1f}%)"
        else:
            persen_neg = persen_pos = persen_neu = 0.0
            neg_count = pos_count = neu_count = 0
            sentiment_dominant = "Belum Terlabel"
            
        # Total Likes & Retweets
        total_likes = int(df_filtered['likes'].sum() if 'likes' in df_filtered.columns else 0)
        total_retweets = int(df_filtered['retweets'].sum() if 'retweets' in df_filtered.columns else 0)
        total_engagement = total_likes + total_retweets

        # Render Metrik Grid (Bento Grid)
        m_col1, m_col2, m_col3 = st.columns(3)
        with m_col1:
            st.markdown(f"""
                <div class="metric-card">
                    <div class="metric-value">{total_volume:,}</div>
                    <div class="metric-label">Total Volume Data</div>
                </div>
            """, unsafe_allow_html=True)
        with m_col2:
            st.markdown(f"""
                <div class="metric-card">
                    <div class="metric-value">{sentiment_dominant}</div>
                    <div class="metric-label">Sentimen Dominan</div>
                </div>
            """, unsafe_allow_html=True)
        with m_col3:
            st.markdown(f"""
                <div class="metric-card">
                    <div class="metric-value">{total_engagement:,}</div>
                    <div class="metric-label">Total Keterlibatan Publik (Likes + Shares)</div>
                </div>
            """, unsafe_allow_html=True)
            
        st.markdown("<br>", unsafe_allow_html=True)
        
        # Grid Utama (70% Kiri, 30% Kanan)
        col_left, col_right = st.columns([7, 3])
        
        with col_left:
            st.subheader("📈 Tren Sentimen Harian")
            # Persiapan grafik garis tren harian
            if 'date_parsed' in df_filtered.columns:
                df_trend = df_filtered.groupby(['date_parsed', 'sentiment_label']).size().reset_index(name='count')
                
                # Plotly line chart
                fig_trend = px.line(
                    df_trend, 
                    x='date_parsed', 
                    y='count', 
                    color='sentiment_label',
                    color_discrete_map={
                        'Positif': '#2D6A4F',
                        'Netral': '#4682B4',
                        'Negatif': '#B00020'
                    },
                    line_shape='spline',
                    labels={'date_parsed': 'Tanggal', 'count': 'Jumlah Konten', 'sentiment_label': 'Sentimen'}
                )
                fig_trend.update_layout(
                    paper_bgcolor='rgba(0,0,0,0)',
                    plot_bgcolor='rgba(0,0,0,0)',
                    font_family='Inter, sans-serif',
                    height=300,
                    margin=dict(l=10, r=10, t=10, b=10)
                )
                st.plotly_chart(fig_trend, use_container_width=True)
            else:
                st.info("Data waktu tidak tersedia untuk grafik tren.")
                
            st.divider()
            
            # AI Narrative Laporan (NLG)
            st.subheader("📝 Ringkasan Eksekutif")
            st.markdown("Ringkasan narasi kebijakan publik disusun otomatis berdasarkan data yang tersedia di basis data.")
            
            # Dapatkan keyword populer dan contoh suara negatif
            top_words = extract_top_keywords(df_filtered, 5)
            
            negative_tweets = df_filtered[df_filtered['sentiment_label'] == 'Negatif']
            suara_publik = f"'{negative_tweets['raw_text'].iloc[0]}'" if not negative_tweets.empty else "Tidak ada cuitan negatif yang terekam."
            
            # Gunakan session_state untuk menyimpan laporan AI agar tidak me-refresh di setiap render
            if 'ai_report_cache' not in st.session_state:
                st.session_state['ai_report_cache'] = ""
                
            if total_volume < 500:
                st.warning(f"⚠️ **Volume Data Tidak Mencukupi (Minimal 500 Data)**\n\n"
                           f"Saat ini hanya terdapat **{total_volume}** data yang terpilih. "
                           f"Batas minimum untuk menyusun Ringkasan Eksekutif berbasis AI adalah **500 data** "
                           f"agar hasil analisis sentimen publik bersifat representatif dan valid.\n\n"
                           f"**Rekomendasi:** Silakan lakukan penarikan data baru di tab **⚙️ Pengaturan Target** atau sesuaikan filter rentang waktu Anda.")
                st.session_state['ai_report_cache'] = ""
            else:
                if st.button("🔄 Perbarui Analisis Narasi", type="primary"):
                    with st.spinner("Menganalisis statistik dan merancang laporan..."):
                        laporan = generate_executive_summary(
                            total_data=total_volume,
                            persen_negatif=round(persen_neg, 1),
                            persen_positif=round(persen_pos, 1),
                            persen_netral=round(persen_neu, 1),
                            top_keywords=top_words,
                            contoh_cuitan=suara_publik
                        )
                        st.session_state['ai_report_cache'] = laporan
                        
                if st.session_state['ai_report_cache']:
                    st.markdown(st.session_state['ai_report_cache'])
                else:
                    st.info("Klik tombol **🔄 Perbarui Analisis Narasi** di atas untuk menyusun ringkasan laporan eksekutif secara otomatis.")
                
        with col_right:
            st.subheader("📊 Distribusi Sentimen")
            # Donut chart persentase sentimen
            if total_sentiment_labelled > 0:
                df_pie = pd.DataFrame({
                    'Sentimen': ['Positif', 'Netral', 'Negatif'],
                    'Jumlah': [pos_count, neu_count, neg_count]
                })
                fig_pie = px.pie(
                    df_pie, 
                    names='Sentimen', 
                    values='Jumlah',
                    hole=0.4,
                    color='Sentimen',
                    color_discrete_map={
                        'Positif': '#2D6A4F',
                        'Netral': '#4682B4',
                        'Negatif': '#B00020'
                    }
                )
                fig_pie.update_layout(
                    paper_bgcolor='rgba(0,0,0,0)',
                    plot_bgcolor='rgba(0,0,0,0)',
                    font_family='Inter, sans-serif',
                    height=260,
                    margin=dict(l=10, r=10, t=10, b=10),
                    showlegend=True
                )
                st.plotly_chart(fig_pie, use_container_width=True)
            else:
                st.info("Belum ada data sentimen terklasifikasi.")
                
            st.divider()
            
            st.subheader("🔑 Kata Kunci Populer")
            st.markdown("Kata-kata paling sering dibahas (diluar kata sambung umum):")
            
            # Tampilkan kata kunci populer
            words_list = extract_top_keywords(df_filtered, 8).split(", ")
            if words_list and words_list[0] != "Tidak ada kata kunci dominan":
                for w in words_list:
                    st.markdown(f"- **{w}**")
            else:
                st.caption("Tidak cukup data teks baku untuk menganalisis kata kunci.")

# =====================================================================
# TAB 2: JEJAK AUDIT DATA
# =====================================================================
with tab2:
    col_audit1, col_audit2 = st.columns([3, 1])
    with col_audit1:
        st.subheader("📑 Jejak Audit Data Mentah & Baku")
        st.markdown("Transparansi analisis: bandingkan teks asli dari masyarakat dengan hasil standardisasi bahasa oleh AI.")
    with col_audit2:
        st.markdown("<div style='height: 25px;'></div>", unsafe_allow_html=True)
        st.link_button(
            "🌐 Editor Supabase",
            get_supabase_dashboard_url(),
            use_container_width=True,
            help="Buka dan sunting database langsung di Supabase Cloud."
        )
    
    if df_filtered.empty:
        st.info("Belum ada data untuk diaudit.")
    else:
        # Persiapkan data audit
        audit_cols = [
            'tweet_id', 'date', 'username', 'raw_text', 'cleaned_text', 
            'sentiment_label', 'confidence_score', 'source_platform'
        ]
        
        df_audit = df_filtered[audit_cols].copy()
        df_audit.columns = [
            'ID Konten', 'Tanggal Pembuatan', 'Username', 'Teks Mentah (X/X-like)', 
            'Teks Baku (EYD AI)', 'Label Sentimen', 'Skor Keyakinan', 'Platform'
        ]
        
        # Tampilkan tabel interaktif
        st.dataframe(
            df_audit,
            use_container_width=True,
            column_config={
                "Skor Keyakinan": st.column_config.NumberColumn(format="%.2f"),
                "Tanggal Pembuatan": st.column_config.DatetimeColumn(format="YYYY-MM-DD HH:mm:ss")
            }
        )

# =====================================================================
# TAB 3: PUSAT KENDALI SCRAPER (PENGATURAN TARGET)
# =====================================================================
with tab3:
    st.subheader("⚙️ Pusat Kendali Penarikan Data (Scraper)")
    st.markdown("Atur target pemantauan isu publik dari berbagai platform digital tanpa menyentuh baris kode.")
    
    # Muat konfigurasi default dari file JSON
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                current_config = json.load(f)
        except Exception:
            current_config = {}
    else:
        current_config = {}
        
    general_cfg = current_config.get("config", {}).get("general", {})
    
    # Cari nilai default untuk form (dukung source_types array baru & source_type string lama)
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
    default_selected = []
    for s in raw_source_list:
        label = mapping_source_types.get(s)
        if label and label not in default_selected:
            default_selected.append(label)
    if not default_selected:
        default_selected = ["Twitter (X)"]
    
    selected_platforms = st.multiselect(
        "Pilih Platform Sasaran (bisa pilih lebih dari satu):",
        options=platform_options,
        default=default_selected
    )
    if not selected_platforms:
        st.warning("⚠️ Silakan pilih setidaknya satu platform sasaran.")
    
    # Form dinamis
    with st.form("form_target_config"):
        label_platforms = ", ".join(selected_platforms) if selected_platforms else "Belum dipilih"
        st.write(f"**Konfigurasi Parameter: {label_platforms}**")
        
        # 1. Rentang Tanggal Target
        col_start, col_end = st.columns(2)
        with col_start:
            default_start = general_cfg.get("start_date", "2026-07-06")
            try:
                start_date_input = st.date_input("Tanggal Mulai Pencarian", value=datetime.datetime.strptime(default_start, "%Y-%m-%d").date())
            except Exception:
                start_date_input = st.date_input("Tanggal Mulai Pencarian", value=datetime.date.today() - datetime.timedelta(days=7))
        with col_end:
            default_end = general_cfg.get("end_date", "2026-07-13")
            try:
                end_date_input = st.date_input("Tanggal Akhir Pencarian", value=datetime.datetime.strptime(default_end, "%Y-%m-%d").date())
            except Exception:
                end_date_input = st.date_input("Tanggal Akhir Pencarian", value=datetime.date.today())
                
        # 2. Target Kata Kunci, Profil, Hashtag
        default_keywords = ", ".join(general_cfg.get("keywords", ["Ibu Kota Baru", "IKN"]))
        default_profiles = ", ".join(general_cfg.get("profiles", ["jokowi", "kemenpupr"]))
        default_hashtags = ", ".join(general_cfg.get("hashtags", ["#IKNNusantara"]))
        fallback_max = general_cfg.get("max_results", 100)
        
        keywords_input = st.text_input("Target Kata Kunci (pisahkan dengan koma):", value=default_keywords)
        profiles_input = st.text_input("Target Profil Akun (pisahkan dengan koma):", value=default_profiles)
        hashtags_input = st.text_input("Target Tagar/Hashtag (pisahkan dengan koma):", value=default_hashtags)
        
        # 3. Batas Maksimal Data PER PLATFORM (hanya tampil jika platform dipilih)
        st.markdown("#### 📊 Batas Maksimal Data per Platform")
        st.caption("Setiap platform memiliki batas independen. Nilai default disarankan berdasarkan karakteristik dan biaya Apify tiap platform.")
        
        # Helper: dapatkan default per platform (backward compat)
        def get_platform_default(field_name: str, fallback_val: int) -> int:
            val = general_cfg.get(field_name)
            if val is None:
                val = fallback_max if fallback_max else fallback_val
            try:
                return int(val)
            except (TypeError, ValueError):
                return fallback_val
        
        # Variabel penampung nilai per platform
        max_twitter = None
        max_instagram = None
        max_linkedin = None
        max_news = None
        
        # Tampilkan slider hanya untuk platform yang DIPILIH
        if "Twitter (X)" in selected_platforms:
            max_twitter = st.slider(
                "🐦 Twitter (X) — Batas maksimal cuitan:",
                min_value=10, max_value=5000,
                value=get_platform_default("max_results_twitter", 500),
                step=10,
                help="Total cuitan yang akan ditarik dari search query Twitter."
            )
        
        if "Instagram" in selected_platforms:
            max_instagram = st.slider(
                "📸 Instagram — Batas postingan per profil:",
                min_value=5, max_value=500,
                value=get_platform_default("max_results_instagram", 100),
                step=5,
                help="Jumlah postingan TERBARU yang ditarik per profil target (dikali jumlah profil)."
            )
        
        if "LinkedIn" in selected_platforms:
            max_linkedin = st.slider(
                "💼 LinkedIn — Batas postingan per perusahaan:",
                min_value=5, max_value=500,
                value=get_platform_default("max_results_linkedin", 100),
                step=5,
                help="Jumlah postingan TERBARU yang ditarik per profil perusahaan."
            )
        
        if "Portal Berita" in selected_platforms:
            max_news = st.slider(
                "📰 Portal Berita — Batas halaman per domain:",
                min_value=5, max_value=200,
                value=get_platform_default("max_results_news", 50),
                step=5,
                help="Maksimal halaman artikel yang di-crawl per domain portal berita (dikali jumlah keyword × jumlah domain)."
            )
            # Default URL portal berita: baca dari config, fallback ke kompas.com
            raw_news_urls = general_cfg.get("news_portal_urls")
            if not raw_news_urls:
                default_news_portals_str = "https://www.kompas.com/"
            elif isinstance(raw_news_urls, list):
                default_news_portals_str = ", ".join(u.strip() for u in raw_news_urls if u.strip())
            elif isinstance(raw_news_urls, str):
                default_news_portals_str = raw_news_urls
            else:
                default_news_portals_str = "https://www.kompas.com/"
            if not default_news_portals_str.strip():
                default_news_portals_str = "https://www.kompas.com/"
            
            news_portals_input = st.text_input(
                "📰 Portal Berita — Daftar URL Portal (pisahkan dengan koma):",
                value=default_news_portals_str,
                placeholder="https://www.kompas.com/, https://www.cnnindonesia.com/",
                help="Masukkan URL homepage portal berita. Sistem akan otomatis menggunakan URL pencarian internal masing-masing portal. Default: https://www.kompas.com/"
            )
        
        # Simpan
        save_btn = st.form_submit_button("💾 Simpan Konfigurasi Target")
        
        if save_btn:
            if not selected_platforms:
                st.error("❌ Gagal menyimpan: Pilih setidaknya SATU platform sasaran terlebih dahulu.")
            else:
                # Rangkai array source_types untuk disimpan
                source_types_to_save = []
                for sp in selected_platforms:
                    code = rev_mapping.get(sp)
                    if code and code not in source_types_to_save:
                        source_types_to_save.append(code)
                if not source_types_to_save:
                    source_types_to_save = ["twitter_"]
                
                # Susun general config (selalu simpan SEMUA field per-platform agar konsisten)
                general_obj = {
                    "start_date": start_date_input.strftime("%Y-%m-%d"),
                    "end_date": end_date_input.strftime("%Y-%m-%d"),
                    "keywords": [k.strip() for k in keywords_input.split(",") if k.strip()],
                    "profiles": [p.strip() for p in profiles_input.split(",") if p.strip()],
                    "hashtags": [h.strip() for h in hashtags_input.split(",") if h.strip()],
                    # max_results tetap disimpan sebagai legacy / aggregate fallback
                    "max_results": fallback_max if isinstance(fallback_max, int) else 100
                }
                
                # Simpan batas per platform (gunakan nilai UI jika platform dipilih,
                # jika tidak dipilih: pertahankan nilai lama jika ada, atau isi default)
                if max_twitter is not None:
                    general_obj["max_results_twitter"] = int(max_twitter)
                else:
                    general_obj["max_results_twitter"] = get_platform_default("max_results_twitter", 500)
                
                if max_instagram is not None:
                    general_obj["max_results_instagram"] = int(max_instagram)
                else:
                    general_obj["max_results_instagram"] = get_platform_default("max_results_instagram", 100)
                
                if max_linkedin is not None:
                    general_obj["max_results_linkedin"] = int(max_linkedin)
                else:
                    general_obj["max_results_linkedin"] = get_platform_default("max_results_linkedin", 100)
                
                if max_news is not None:
                    general_obj["max_results_news"] = int(max_news)
                else:
                    general_obj["max_results_news"] = get_platform_default("max_results_news", 50)
                
                # Simpan news_portal_urls (baik Portal Berita dipilih atau tidak, agar konsisten)
                if "news_portals_input" in locals() and news_portals_input is not None:
                    parsed_urls = []
                    for u in [x.strip() for x in news_portals_input.split(",") if x.strip()]:
                        # Pastikan minimal punya format domain, tambah https jika tidak ada skema
                        if u and not u.startswith("http"):
                            u = "https://" + u.lstrip("/")
                        if u:
                            parsed_urls.append(u.rstrip("/"))
                    # Jika hasilnya kosong, pakai default kompas.com agar tidak error
                    if not parsed_urls:
                        parsed_urls = ["https://www.kompas.com"]
                    general_obj["news_portal_urls"] = parsed_urls
                else:
                    # Portal Berita tidak dipilih, pertahankan nilai lama atau default
                    old_news_urls = general_cfg.get("news_portal_urls")
                    if isinstance(old_news_urls, list) and old_news_urls:
                        general_obj["news_portal_urls"] = old_news_urls
                    else:
                        general_obj["news_portal_urls"] = ["https://www.kompas.com"]
                
                new_config = {
                    "source_types": source_types_to_save,
                    "config": {
                        "general": general_obj
                    }
                }
                
                try:
                    with open(CONFIG_FILE, 'w') as f:
                        json.dump(new_config, f, indent=4)
                    label_simpan = ", ".join(selected_platforms)
                    st.success(f"✅ Konfigurasi target berhasil disimpan! Platform aktif: {label_simpan}")
                except Exception as e:
                    st.error(f"[ERROR] Gagal menyimpan konfigurasi: {e}")
                
    st.divider()
    
    # Bagian Eksekusi Pemicu Scraping & Pipeline AI
    st.subheader("🚀 Pemicu Aliran Pemrosesan (Pipeline Run)")
    st.markdown("Gunakan panel kontrol di bawah untuk memicu penarikan data baru dari Apify dan memproses prapemrosesan LLM + Klasifikasi ML secara instan.")
    
    col_run1, col_run2 = st.columns(2)
    
    # Pemicu Scraper
    with col_run1:
        st.markdown("**Langkah 1: Penarikan Data (Scraper)**")
        st.caption("Menghubungkan ke platform Apify Cloud untuk menarik data mentah terbaru sesuai konfigurasi.")
        if st.button("🚀 Jalankan Penarikan Data Sekarang", type="primary", use_container_width=True):
            with st.spinner("Menghubungkan ke Apify Cloud & menarik data mentah..."):
                try:
                    # Jalankan subprocess run scraper
                    result = subprocess.run(
                        [sys.executable, "01_run_scraper.py"],
                        capture_output=True, text=True, check=True
                    )
                    st.success("✅ Proses penarikan data mentah selesai!")
                    with st.expander("Tampilkan Log Scraper"):
                        st.code(result.stdout)
                except subprocess.CalledProcessError as e:
                    st.error(f"❌ Gagal menjalankan modul scraper (Exit code: {e.returncode}).")
                    with st.expander("Tampilkan Log Kesalahan", expanded=True):
                        st.markdown("**Output (stdout):**")
                        st.code(e.stdout if e.stdout else "Tidak ada output.")
                        st.markdown("**Error (stderr):**")
                        st.code(e.stderr if e.stderr else "Tidak ada error.")
                        
    # Pemicu Pipeline AI/ML
    with col_run2:
        st.markdown("**Langkah 2: Proses AI & Klasifikasi ML**")
        st.caption("Prapemrosesan bahasa baku EYD oleh model Gemini AI dan pelabelan sentimen oleh SVM lokal.")
        if st.button("🧠 Jalankan Proses AI & ML Sekarang", use_container_width=True):
            with st.spinner("Menstandardisasi teks dan melabeli sentimen..."):
                try:
                    # Jalankan subprocess run pipeline data
                    result = subprocess.run(
                        [sys.executable, "01_pipeline_data.py"],
                        capture_output=True, text=True, check=True
                    )
                    st.success("✅ Prapemrosesan AI & Klasifikasi SVM selesai!")
                    with st.expander("Tampilkan Log Pemrosesan"):
                        st.code(result.stdout)
                    # Force refresh page
                    st.rerun()
                except subprocess.CalledProcessError as e:
                    st.error(f"❌ Gagal menjalankan modul prapemrosesan AI/ML (Exit code: {e.returncode}).")
                    with st.expander("Tampilkan Log Kesalahan", expanded=True):
                        st.markdown("**Output (stdout):**")
                        st.code(e.stdout if e.stdout else "Tidak ada output.")
                        st.markdown("**Error (stderr):**")
                        st.code(e.stderr if e.stderr else "Tidak ada error.")
