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

# Impor generator NLG
from nlg_generator import generate_executive_summary

# --- Opsional: Library Export PDF (reportlab + matplotlib) ---
# User HARUS install manual sekali via:  pip install reportlab matplotlib
PDF_LIBS_OK = False
PDF_IMPORT_ERROR_MSG = ""
try:
    import matplotlib
    matplotlib.use('Agg')  # Non-interactive backend (PENTING di server Streamlit!)
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
if not PDF_LIBS_OK:
    PDF_INSTALL_CMD = (
        "⚠️ Library export PDF belum lengkap! Jalankan di terminal:\n\n"
        "    pip install reportlab matplotlib\n\n"
        f"Detail error: {PDF_IMPORT_ERROR_MSG}"
    )
else:
    PDF_INSTALL_CMD = ""

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

# ====================================================================
# [EXPORT PDF] Helper functions
# ====================================================================
def _fig_to_png_bytes(fig, dpi: int = 150) -> BytesIO:
    """Convert matplotlib figure -> PNG BytesIO (untuk dimasukkan ke PDF reportlab)."""
    buf = BytesIO()
    fig.savefig(buf, format='png', dpi=dpi, bbox_inches='tight',
                facecolor='white', edgecolor='none')
    plt.close(fig)
    buf.seek(0)
    return buf


def _chart_pie_sentimen_pdf(pos: int, neu: int, neg: int) -> Optional[BytesIO]:
    """Donut chart distribusi sentimen untuk PDF."""
    if not PDF_LIBS_OK or (pos + neu + neg) <= 0:
        return None
    fig, ax = plt.subplots(figsize=(5, 4))
    labels = ['Positif', 'Netral', 'Negatif']
    sizes = [pos, neu, neg]
    warna = ['#2D6A4F', '#4682B4', '#B00020']
    # Hilangkan label bernilai 0
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
    ax.set_title('Distribusi Sentimen Publik', fontsize=13, fontweight='bold', pad=15)
    return _fig_to_png_bytes(fig)


def _chart_tren_harian_pdf(df_filtered: pd.DataFrame) -> Optional[BytesIO]:
    """Line chart tren sentimen harian untuk PDF."""
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
    """Horizontal bar jumlah data per platform sumber."""
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


def _chart_keywords_pdf(keywords_list: List[str]) -> Optional[BytesIO]:
    """Bar chart top keyword teratas."""
    if not PDF_LIBS_OK or not keywords_list or not any(k for k in keywords_list if k and k != 'Tidak ada kata kunci dominan'):
        return None
    kl = [k for k in keywords_list if k and k != 'Tidak ada kata kunci dominan'][:10]
    if not kl:
        return None
    fig, ax = plt.subplots(figsize=(7.5, 3.5))
    import numpy as np
    y_pos = np.arange(len(kl))
    freqs = list(range(len(kl), 0, -1))  # Urut: pertama paling besar (proxy frequency)
    bars = ax.barh(y_pos, freqs, color='#6c757d')
    ax.set_yticks(y_pos); ax.set_yticklabels(kl, fontsize=10)
    ax.set_title(f'Top {len(kl)} Kata Kunci Populer', fontsize=13, fontweight='bold', pad=10)
    ax.set_xlabel('Frekuensi Relatif')
    ax.grid(alpha=0.3, axis='x', linestyle='--')
    ax.invert_yaxis()
    return _fig_to_png_bytes(fig)


def generate_full_pdf_report(
    config_loaded: dict,
    df_filt: pd.DataFrame,
    filter_platforms: List[str],
    filter_date_range: tuple,
    metrics: Dict,
    ai_narasi_txt: str = "",
) -> BytesIO:
    """
    Membangkitkan PDF Laporan Lengkap. Return BytesIO buffer.
    
    Struktur PDF:
    1. Cover/Halaman Judul + Informasi Target Scraper (config)
    2. BAB I  : Pengaturan Target Scraper (source_types, keywords, profiles, hashtags,
                 dates, per-platform max limits, news portal URLs)
    3. BAB II : Filter Analisis (platform terfilter saat ini + date range sidebar)
    4. BAB III: Visual Analitik Sentimen (Pie, Tren, Platform, Keywords)
    5. BAB IV : Ringkasan Eksekutif Narasi (AI generated jika >= 500 data)
    6. BAB V  : Lampiran Tabel Sampel 10 Data Terbaru
    """
    # ---- STYLES ReportLab ----
    styles = getSampleStyleSheet()
    sTitle = ParagraphStyle('TitleBigTitle', parent=styles['Title'], fontSize=20, alignment=TA_CENTER,
                            spaceAfter=14, textColor=colors.HexColor('#1a365d'))
    sSub = ParagraphStyle('SubtitleC', parent=styles['Normal'], fontSize=11, alignment=TA_CENTER,
                           textColor=colors.grey)
    sH1 = ParagraphStyle('BabH1', parent=styles['Heading1'], fontSize=15, textColor=colors.HexColor('#1a365d'),
                          spaceBefore=10, spaceAfter=6, borderPadding=(0,0,2,0))
    sH2 = ParagraphStyle('BabH2', parent=styles['Heading2'], fontSize=12,
                          textColor=colors.HexColor('#2c5282'), spaceBefore=6, spaceAfter=4)
    sBody = ParagraphStyle('BodyTextJ', parent=styles['BodyText'], fontSize=10, leading=14,
                            alignment=TA_JUSTIFY, spaceAfter=4)
    sBullet = ParagraphStyle('BulletBody', parent=sBody, leftIndent=18, bulletIndent=6, spaceAfter=2)
    sSmall = ParagraphStyle('Small', parent=styles['Normal'], fontSize=8, textColor=colors.grey, alignment=TA_CENTER)
    # ---- Story container elemen PDF ----
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        leftMargin=2*cm, rightMargin=2*cm, topMargin=2*cm, bottomMargin=2.5*cm,
        title='Laporan Analisis Sentimen Kebijakan Publik',
        author='AI Sentimen App'
    )
    story = []
    
    # Helper tambahkan nomor halaman (via canvasmaker)
    def _hal_nomor(canvas, ddoc):
        canvas.saveState()
        canvas.setFont('Helvetica', 8); canvas.setFillColor(colors.grey)
        canvas.drawCentredString(A4[0]/2.0, 1.2*cm, f'Halaman {ddoc.page}')
        canvas.drawString(2*cm, 1.2*cm, 'Analisis Sentimen Kebijakan Publik — AI Powered')
        canvas.restoreState()
    
    # ============ HALAMAN 1: COVER + BAB I & II ============
    story.append(Spacer(1, 1.5*cm))
    story.append(Paragraph('LAPORAN ANALISIS SENTIMEN', sTitle))
    story.append(Paragraph('Kebijakan Publik Berbasis AI', ParagraphStyle('tmp', parent=sTitle, fontSize=14)))
    story.append(Spacer(1, 0.3*cm))
    tgl_sekarang = datetime.datetime.now().strftime('%d %B %Y — %H:%M WIB')
    story.append(Paragraph(f'Tanggal Laporan Dibuat : <b>{tgl_sekarang}</b>', sSub))
    story.append(Spacer(1, 0.8*cm))
    
    # 3 Metrik Utama
    metrik_data = [
        ['Total Volume Data', 'Sentimen Dominan', 'Total Engagement'],
        [f"{metrics.get('total_volume', 0):,}",
         str(metrics.get('sentiment_dominant', 'N/A')),
         f"{metrics.get('total_engagement', 0):,}"],
    ]
    t_metrik = Table(metrik_data, colWidths=[5.5*cm]*3)
    t_metrik.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#1a365d')),
        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,-1), 10),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 10),
        ('TOPPADDING', (0,0), (-1,-1), 10),
        ('GRID', (0,0), (-1,-1), 0.3, colors.lightgrey),
        ('BACKGROUND', (0,1), (-1,1), colors.HexColor('#f7fafc')),
    ]))
    story.append(t_metrik)
    story.append(PageBreak())
    
    # ============================
    # BAB I: PENGATURAN TARGET SCRAPER
    # ============================
    story.append(Paragraph('BAB I — PENGATURAN TARGET SCRAPER', sH1))
    story.append(Paragraph(
        'Berikut adalah konfigurasi target scraper yang tersimpan pada file target_config.json yang digunakan pada saat penarikan data dari Apify Cloud:', sBody))
    story.append(Spacer(1, 0.2*cm))
    
    general = (config_loaded or {}).get('config', {}).get('general', {})
    
    # Helper label-value Table BAB 1
    def _row(label: str, val: str):
        val_clean = str(val).replace('<', '&lt;').replace('>', '&gt;')
        return [Paragraph(f'<b>{label}</b>', sBody), Paragraph(val_clean, sBody)]
    
    s_types_raw = (config_loaded or {}).get('source_types')
    if isinstance(s_types_raw, str):            s_types_raw = [s_types_raw]
    if not s_types_raw:
        s_types_raw = [(config_loaded or {}).get('source_type')] or ['-']
    
    rows_cfg = [
        _row('Platform Sasaran Aktif', ', '.join(str(x) for x in s_types_raw if x)),
        _row('Tanggal Mulai Target', general.get('start_date', '-')),
        _row('Tanggal Akhir Target', general.get('end_date', '-')),
        _row('Kata Kunci Target', ', '.join(general.get('keywords', []) or ['-'])),
        _row('Profil/Akun Target', ', '.join(general.get('profiles', []) or ['-'])),
        _row('Hashtag Target', ', '.join(general.get('hashtags', []) or ['-'])),
        _row('Batas (Umum - Legacy)', general.get('max_results', '-')),
        _row('Batas Twitter (X)', general.get('max_results_twitter', '-')),
        _row('Batas Instagram (per profil)', general.get('max_results_instagram', '-')),
        _row('Batas LinkedIn (per target)', general.get('max_results_linkedin', '-')),
        _row('Batas Portal Berita (per domain)', general.get('max_results_news', '-')),
        _row('URL Portal Berita',
             ', '.join(general.get('news_portal_urls', []) or ['https://www.kompas.com'])),
    ]
    t_cfg = Table(rows_cfg, colWidths=[4.5*cm, 11.5*cm], hAlign='LEFT')
    t_cfg.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('LEFTPADDING', (0,0), (-1,-1), 6),
        ('RIGHTPADDING', (0,0), (-1,-1), 6),
        ('TOPPADDING', (0,0), (-1,-1), 5),
        ('BOTTOMPADDING', (0,0), (-1,-1), 5),
        ('GRID', (0,0), (-1,-1), 0.3, colors.lightgrey),
        ('BACKGROUND', (0,0), (0,-1), colors.HexColor('#edf2f7')),
    ]))
    story.append(t_cfg)
    story.append(PageBreak())
    
    # ============================
    # BAB II: FILTER ANALISIS SAAT INI
    # ============================
    story.append(Paragraph('BAB II — FILTER ANALISIS SAAT INI', sH1))
    story.append(Paragraph(
        'Ringkasan filter yang diterapkan pada sidebar dashboard saat laporan diekspor:', sBody))
    story.append(Spacer(1, 0.2*cm))
    
    # Normalisasi date range
    if isinstance(filter_date_range, tuple) and len(filter_date_range) == 2:
        t_awal, t_akhir = [str(d) for d in filter_date_range]
        rentang_waktu = f'{t_awal} &nbsp; s/d &nbsp; {t_akhir}'
    else:
        rentang_waktu = '-'
    
    filt_rows = [
        _row('Platform Terfilter', ', '.join(filter_platforms) if filter_platforms else '(Semua)'),
        _row('Rentang Waktu Analisis', rentang_waktu),
        _row('Jumlah Baris Sesuai Filter', f"{metrics.get('total_volume', 0):,} baris data"),
        _row('Jumlah Terlabel Sentimen', f"{metrics.get('total_sentiment_labelled', 0):,} baris"),
        _row('Persentase Positif', f"{metrics.get('persen_pos', 0.0):.2f}%"),
        _row('Persentase Netral', f"{metrics.get('persen_neu', 0.0):.2f}%"),
        _row('Persentase Negatif', f"{metrics.get('persen_neg', 0.0):.2f}%"),
    ]
    t_fil = Table(filt_rows, colWidths=[4.5*cm, 11.5*cm])
    t_fil.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('LEFTPADDING', (0,0), (-1,-1), 6),
        ('RIGHTPADDING', (0,0), (-1,-1), 6),
        ('TOPPADDING', (0,0), (-1,-1), 5),
        ('BOTTOMPADDING', (0,0), (-1,-1), 5),
        ('GRID', (0,0), (-1,-1), 0.3, colors.lightgrey),
        ('BACKGROUND', (0,0), (0,-1), colors.HexColor('#fff7ed')),
    ]))
    story.append(t_fil)
    story.append(Spacer(1, 0.5*cm))
    
    # ============================
    # BAB III: VISUAL ANALITIK SENTIMEN
    # ============================
    story.append(Paragraph('BAB III — VISUALISASI ANALITIK SENTIMEN', sH1))
    story.append(Paragraph(
        'Visualisasi data di bawah ini merepresentasikan hasil analisis sentimen publik berdasarkan data yang tersedia beserta distribusi, tren waktu, platform sumber, dan kata kunci populer:', sBody))
    story.append(Spacer(1, 0.3*cm))
    
    # --- 3.1 Pie Sentimen
    pos = int(metrics.get('pos_count', 0)); neu = int(metrics.get('neu_count', 0)); neg = int(metrics.get('neg_count', 0))
    pie_pie_bytes = _chart_pie_sentimen_pdf(pos, neu, neg)
    story.append(Paragraph('3.1 Distribusi Sentimen Publik', sH2))
    if pie_pie_bytes:
        story.append(Image(pie_pie_bytes, width=13*cm, height=10*cm, hAlign='CENTER'))
        story.append(Spacer(1, 0.3*cm))
        # Tabel persentase pendukung
        distrib_rows = [
            ['Kategori', 'Jumlah', 'Persentase'],
            ['Positif', f'{pos:,}', f"{metrics.get('persen_pos', 0):.2f}%"],
            ['Netral',  f'{neu:,}', f"{metrics.get('persen_neu', 0):.2f}%"],
            ['Negatif', f'{neg:,}', f"{metrics.get('persen_neg', 0):.2f}%"],
            ['Total (Terlabel)', f"{pos+neu+neg:,}", '100.00%'],
        ]
        t_dis = Table(distrib_rows, colWidths=[5*cm, 4*cm, 4*cm], hAlign='CENTER')
        t_dis.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#2c5282')),
            ('TEXTCOLOR', (0,0), (-1,0), colors.white),
            ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
            ('ALIGN', (0,0), (-1,-1), 'CENTER'),
            ('FONTNAME', (0,-1), (-1,-1), 'Helvetica-Bold'),
            ('GRID', (0,0), (-1,-1), 0.3, colors.lightgrey),
            ('FONTSIZE', (0,0), (-1,-1), 10),
            ('TOPPADDING', (0,0), (-1,-1), 6),
            ('BOTTOMPADDING', (0,0), (-1,-1), 6),
        ]))
        story.append(t_dis)
    else:
        story.append(Paragraph('_Belum ada data sentimen terlabel untuk divisualisasikan._', sBody))
    story.append(PageBreak())
    
    # --- 3.2 Tren Harian
    story.append(Paragraph('3.2 Tren Sentimen Harian', sH2))
    tren_bytes = _chart_tren_harian_pdf(df_filt)
    if tren_bytes:
        story.append(Image(tren_bytes, width=17*cm, height=8*cm, hAlign='CENTER'))
    else:
        story.append(Paragraph('_Data tanggal tidak cukup data untuk membentuk grafik tren._', sBody))
    story.append(Spacer(1, 0.5*cm))
    
    # --- 3.3 Platform Sumber
    story.append(Paragraph('3.3 Volume Data per Platform Sumber', sH2))
    plat_bytes = _chart_platform_pdf(df_filt)
    if plat_bytes:
        story.append(Image(plat_bytes, width=17*cm, height=7*cm, hAlign='CENTER'))
    else:
        story.append(Paragraph('_Data platform sumber tidak tersedia._', sBody))
    story.append(Spacer(1, 0.5*cm))
    
    # --- 3.4 Top Keywords
    story.append(Paragraph('3.4 Kata Kunci Populer', sH2))
    # Dapatkan keywords dari fungsi helper extract_top_keywords
    try:
        kw_text = extract_top_keywords(df_filt, 10)
        kw_list = [w.strip() for w in kw_text.split(',') if w.strip()]
    except Exception:
        kw_list = []
    kw_bytes = _chart_keywords_pdf(kw_list)
    if kw_bytes:
        story.append(Image(kw_bytes, width=17*cm, height=8*cm, hAlign='CENTER'))
    elif kw_list:
        # Fallback: tulisan list saja
        for w in kw_list[:10]:
            story.append(Paragraph(f'- <b>{w}</b>', sBullet))
    else:
        story.append(Paragraph('_Belum cukup data teks baku untuk ekstraksi kata kunci._', sBody))
    
    story.append(PageBreak())
    
    # ============================
    # BAB IV: RINGKASAN EKSEKUTIF (AI Narrative)
    # ============================
    story.append(Paragraph('BAB IV — RINGKASAN EKSEKUTIF NARASI', sH1))
    tv = int(metrics.get('total_volume', 0))
    if tv < 500 and not ai_narasi_txt.strip():
        _warn = (f'<b>⚠️ Catatan:</b> Volume data saat ini baru <b>{tv:,}</b> data. '
                 'Batas minimum untuk Ringkasan Eksekutif berbasis AI adalah <b>500 data</b> '
                 'agar hasil analisis sentimen publik bersifat representatif dan valid. '
                 'Disarankan untuk menambah data scraper terlebih dahulu sebelum membuat laporan resmi.')
        story.append(Paragraph(_warn,
            ParagraphStyle('warning', parent=sBody, textColor=colors.HexColor('#8a6d3b'),
                           backColor=colors.HexColor('#fcf8e3'), borderPadding=8)))
    elif ai_narasi_txt.strip():
        # Pisahkan per paragraf (enter ganda = paragraf baru)
        for pg in re.split(r"\n{2,}|", ai_narasi_txt.replace('\r\n', '\n')):
            pg_clean = pg.strip()
            if not pg_clean: continue
            # Bold heading seperti "1. Situasi Saat Ini" → Style Heading 2
            if re.match(r'^\d+\.\s+[A-Z].+', pg_clean.split('\n')[0]) or '###' in pg_clean[:10]:
                lines = pg_clean.split('\n', 1)
                story.append(Paragraph(lines[0].replace('###', '').strip(), sH2))
                if len(lines) > 1 and lines[1].strip():
                    story.append(Paragraph(lines[1].strip().replace('\n', '<br/>'), sBody))
            else:
                story.append(Paragraph(pg_clean.replace('\n', '<br/>'), sBody))
            story.append(Spacer(1, 0.15*cm))
    else:
        story.append(Paragraph(
            'Narasi AI belum di-generate. Silakan kembali ke dashboard Tab Analitik Sentimen, klik tombol Perbarui Analisis Narasi, lalu export ulang laporan PDF.', sBody))
    story.append(PageBreak())
    
    # ============================
    # BAB V: LAMPIRAN SAMPEL DATA
    # ============================
    story.append(Paragraph('BAB V — LAMPIRAN: SAMPEL DATA TERBARU', sH1))
    story.append(Paragraph(
        'Berikut adalah 10 sampel data terbaru yang lolos filter (username, platform, sentimen, skor keyakinan, dan cuplikan teks baku). Untuk data lengkap dapat dilihat pada Tabel Supabase Cloud.', sBody))
    story.append(Spacer(1, 0.3*cm))
    
    # Susun data sampel (maks 10)
    if not df_filt.empty:
        df_sample = df_filt.head(10).copy()
        cols_needed = ['date', 'username', 'source_platform', 'sentiment_label',
                       'confidence_score', 'cleaned_text', 'raw_text']
        avail_cols = [c for c in cols_needed if c in df_sample.columns]
        df_sample = df_sample[avail_cols].fillna('-')
        
        # Header Tabel
        header_map = {
            'date': 'Tgl', 'username': 'Username', 'source_platform': 'Platform',
            'sentiment_label': 'Sentimen', 'confidence_score': 'Conf.',
            'cleaned_text': 'Teks Baku (EYD)', 'raw_text': 'Teks Mentah'
        }
        header_row = [header_map.get(c, c) for c in avail_cols]
        data_rows = [header_row]
        for _, row in df_sample.iterrows():
            r_list = []
            for c in avail_cols:
                v = row[c]
                if c in ('cleaned_text', 'raw_text'):
                    v_str = str(v)[:90].replace('\n', ' ')
                    if len(str(row[c])) > 90: v_str += '...'
                elif c == 'confidence_score':
                    try: v_str = f"{float(v):.0%}"
                    except: v_str = str(v)
                else:
                    v_str = str(v)[:40]
                r_list.append(v_str)
            data_rows.append(r_list)
        # Lebar kolom adaptif
        ncol = len(avail_cols)
        tot_width = 17*cm
        widths = [tot_width / ncol] * ncol
        # Sesuaikan untuk kolom teks (paling lebar)
        for idx, c in enumerate(avail_cols):
            if c in ('cleaned_text', 'raw_text'):
                widths[idx] = 5.5*cm
        t_samp = Table(data_rows, colWidths=widths, repeatRows=1)
        style_cmds = [
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#2d3748')),
            ('TEXTCOLOR', (0,0), (-1,0), colors.white),
            ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
            ('FONTSIZE', (0,0), (-1,-1), 7.5),
            ('VALIGN', (0,0), (-1,-1), 'TOP'),
            ('LEFTPADDING', (0,0), (-1,-1), 4),
            ('RIGHTPADDING', (0,0), (-1,-1), 4),
            ('TOPPADDING', (0,0), (-1,-1), 4),
            ('BOTTOMPADDING', (0,0), (-1,-1), 4),
            ('GRID', (0,0), (-1,-1), 0.2, colors.lightgrey),
            ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor('#f7fafc')]),
        ]
        # Warnai baris berdasarkan sentimen
        sent_col_idx = avail_cols.index('sentiment_label') if 'sentiment_label' in avail_cols else -1
        if sent_col_idx >= 0:
            for i in range(1, len(data_rows)):
                val_s = str(data_rows[i][sent_col_idx]).lower()
                if 'positif' in val_s:
                    style_cmds.append(('TEXTCOLOR', (sent_col_idx, i), (sent_col_idx, i),
                                       colors.HexColor('#2D6A4F')))
                elif 'negatif' in val_s:
                    style_cmds.append(('TEXTCOLOR', (sent_col_idx, i), (sent_col_idx, i),
                                       colors.HexColor('#B00020')))
        t_samp.setStyle(TableStyle(style_cmds))
        story.append(t_samp)
    else:
        story.append(Paragraph('_Tidak ada data untuk ditampilkan._', sBody))
    
    story.append(Spacer(1, 1*cm))
    story.append(Paragraph('— Akhir Laporan —', sSub))
    
    # BUILD PDF
    doc.build(story, onFirstPage=_hal_nomor, onLaterPages=_hal_nomor)
    buffer.seek(0)
    return buffer
# =====================================================================
# [END] Export PDF Helper
# ====================================================================

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

# Filter Platform (selalu tampilkan SEMUA 4 platform known, meskipun DB baru punya 1 platform)
KNOWN_PLATFORMS = ["Twitter", "Instagram", "LinkedIn", "News"]
if not df_all.empty:
    platforms_in_db = [p for p in df_all['source_platform'].unique().tolist() if p]
    # Urutkan sesuai urutan KNOWN_PLATFORMS lalu sisanya di belakang
    platforms_available = []
    for p in KNOWN_PLATFORMS:
        if p not in platforms_available:
            platforms_available.append(p)
    for p in platforms_in_db:
        if p not in platforms_available:
            platforms_available.append(p)
    # Default pilih hanya yang ada di DB saja (agar tidak milih platform tanpa data)
    platforms_default = [p for p in platforms_in_db if p in KNOWN_PLATFORMS or True]
else:
    platforms_available = KNOWN_PLATFORMS.copy()
    platforms_default = KNOWN_PLATFORMS.copy()

platform_filter = st.sidebar.multiselect(
    "Pilih Platform Sumber:",
    options=platforms_available,
    default=platforms_default if platforms_default else None
)
if not df_all.empty:
    missing_in_db = [p for p in KNOWN_PLATFORMS if p not in platforms_in_db]
    if missing_in_db:
        st.sidebar.caption(f"ℹ️ Belum ada data: {', '.join(missing_in_db)} (pilih untuk lihat perbandingan kosong / trigger scraper)")

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
            
            # AI Narrative Laporan (NLG) + Export PDF
            col_head1, col_head2 = st.columns([5,1])
            with col_head1:
                st.subheader("📝 Ringkasan Eksekutif")
                st.markdown("Ringkasan narasi kebijakan publik disusun otomatis berdasarkan data yang tersedia di basis data.")
            with col_head2:
                st.markdown("<div style='height: 0.2cm;'></div>", unsafe_allow_html=True)
                if not PDF_LIBS_OK:
                    with st.popover("📥 Download PDF"):
                        st.warning("⚠️ Library export PDF belum terpasang!\n\nJalankan perintah di terminal:\n\n```cmd\npip install reportlab matplotlib\n```\n\nLalu refresh halaman ini.")
                        st.caption(f"Detail error: {PDF_ERR_MSG[:220]}..." if len(PDF_ERR_MSG)>220 else f"Detail: {PDF_ERR_MSG}")
                else:
                    # =================================================================
                    # [SCOPE FIX AMAN] Capture semua variabel ke LOKAL VAR DULU sebelum define nested function.
                    # Ini menghindari Streamlit re-run closure capture ambiguity & NameError.
                    # =================================================================
                    try:
                        df_report_data = df_filtered.copy()  # BAB III & BAB V butuh ini
                    except Exception:
                        df_report_data = pd.DataFrame()
                    report_platforms = list(platform_filter) if isinstance(platform_filter, (list, tuple, set)) else []
                    report_daterange = date_range if isinstance(date_range, tuple) else ('-', '-')
                    report_metrics_payload = {
                        "total_volume": int(total_volume or 0),
                        "sentiment_dominant": str(sentiment_dominant),
                        "total_engagement": int(total_engagement or 0),
                        "total_sentiment_labelled": int(total_sentiment_labelled or 0),
                        "persen_pos": float(persen_pos or 0),
                        "persen_neu": float(persen_neu or 0),
                        "persen_neg": float(persen_neg or 0),
                        "pos_count": int(pos_count or 0),
                        "neu_count": int(neu_count or 0),
                        "neg_count": int(neg_count or 0),
                    }
                    report_narasi_txt = (st.session_state.get('ai_report_cache') or '').strip()
                    
                    # Build metrics dict untuk dikirim ke PDF builder
                    _met = report_metrics_payload
                    
                    # --- Default arg (agar closure capture aman di Streamlit re-run) ---
                    def _build_charts_and_pdf(
                        _df_report: pd.DataFrame = df_report_data,
                        _plats: List[str] = report_platforms,
                        _drng: tuple = report_daterange,
                        _metrics: Dict = report_metrics_payload,
                        _narasi: str = report_narasi_txt,
                    ) -> Optional[BytesIO]:
                        """Helper in-Scope: build 4 matplotlib charts + PDF full report -> BytesIO."""
                        try:
                            # ===== Helper 1: matplotlib fig -> PNG bytes =====
                            def _fig2png(fig, dpi=150):
                                _b = BytesIO()
                                fig.savefig(_b, format='png', dpi=dpi, bbox_inches='tight',
                                            facecolor='white', edgecolor='none')
                                plt.close(fig); _b.seek(0); return _b
                            
                            # ===== Helper 2: Pie Sentimen =====
                            def _c_pie(p, n, ne):
                                if p+n+ne <= 0: return None
                                fig, ax = plt.subplots(figsize=(5,4))
                                _L, _S, _W = [], [], []
                                for _nm, _va, _co in [('Positif', p, '#2D6A4F'), ('Netral', ne, '#4682B4'), ('Negatif', n, '#B00020')]:
                                    if _va>0: _L.append(_nm); _S.append(_va); _W.append(_co)
                                if not _S: return None
                                wedges, _tx, autotx = ax.pie(_S, labels=_L, colors=_W, autopct='%1.1f%%',
                                    startangle=90, pctdistance=0.78, wedgeprops=dict(width=0.5, edgecolor='white', lw=2))
                                for _t in _tx: _t.set_fontsize(10)
                                for _t in autotx: _t.set_fontsize(9); _t.set_fontweight('bold'); _t.set_color('white')
                                ax.text(0,0, f'Total: {sum(_S):,}\n(Terlabel)', ha='center', va='center', fontsize=11, fontweight='bold')
                                ax.set_title('Distribusi Sentimen Publik', fontsize=13, fontweight='bold', pad=15)
                                return _fig2png(fig)
                            
                            # ===== Helper 3: Tren Harian =====
                            def _c_tren(dff):
                                if dff.empty or 'date_parsed' not in dff.columns: return None
                                _dg = dff.groupby(['date_parsed','sentiment_label']).size().reset_index(name='count')
                                if _dg.empty: return None
                                fig, ax = plt.subplots(figsize=(7.5,3.5))
                                _cmap = {'Positif':'#2D6A4F','Netral':'#4682B4','Negatif':'#B00020'}
                                for _lb, _co in _cmap.items():
                                    _sub = _dg[_dg['sentiment_label']==_lb]
                                    if not _sub.empty:
                                        ax.plot(pd.to_datetime(_sub['date_parsed']), _sub['count'], marker='o', ms=4, lw=2, label=_lb, color=_co)
                                ax.set_title('Tren Sentimen Publik Harian', fontsize=13, fontweight='bold', pad=10)
                                ax.set_xlabel('Tanggal'); ax.set_ylabel('Jumlah Konten'); ax.legend(); ax.grid(alpha=0.3, ls='--')
                                ax.xaxis.set_major_formatter(mdates.DateFormatter('%d-%b'))
                                fig.autofmt_xdate(); ax.yaxis.set_major_locator(MaxNLocator(integer=True))
                                return _fig2png(fig)
                            
                            # ===== Helper 4: Bar Platform =====
                            def _c_plat(dff):
                                if dff.empty or 'source_platform' not in dff.columns: return None
                                _dp = dff['source_platform'].value_counts().reset_index()
                                _dp.columns=['platform','count']
                                if _dp.empty: return None
                                fig, ax = plt.subplots(figsize=(7.5,3))
                                _cols = ['#1f77b4','#2ca02c','#ff7f0e','#d62728','#9467bd'][:len(_dp)]
                                bars = ax.barh(_dp['platform'], _dp['count'], color=_cols)
                                ax.set_title('Volume Data per Platform Sumber', fontsize=13, fontweight='bold', pad=10)
                                ax.set_xlabel('Jumlah Konten')
                                for _b in bars:
                                    _w = _b.get_width()
                                    ax.text(_w + max(1,_w*0.01), _b.get_y()+_b.get_height()/2, f'{int(_w):,}', va='center', fontsize=10, fontweight='bold')
                                ax.grid(alpha=0.3, axis='x', ls='--'); ax.invert_yaxis()
                                return _fig2png(fig)
                            
                            # ===== Helper 5: Bar Keywords =====
                            def _c_kw(kw_list):
                                _k = [x for x in kw_list if x and x!='Tidak ada kata kunci dominan'][:10]
                                if not _k: return None
                                fig, ax = plt.subplots(figsize=(7.5,3.5))
                                _fr = list(range(len(_k),0,-1))
                                bars = ax.barh(_k, _fr, color='#6c757d')
                                ax.set_title(f'Top {len(_k)} Kata Kunci Populer', fontsize=13, fontweight='bold', pad=10)
                                ax.set_xlabel('Frekuensi Relatif'); ax.grid(alpha=0.3, axis='x', ls='--'); ax.invert_yaxis()
                                return _fig2png(fig)
                            
                            # ===== Helper 6: Load config =====
                            try:
                                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                                    _cfg = json.load(f)
                            except Exception:
                                _cfg = {}
                            _gen = (_cfg or {}).get('config', {}).get('general', {})
                            
                            # ===== Helper 7: Build PDF via reportlab =====
                            sty = getSampleStyleSheet()
                            sH1 = ParagraphStyle('H1P', parent=sty['Heading1'], fontSize=15,
                                textColor=colors.HexColor('#1a365d'), spaceBefore=10, spaceAfter=6)
                            sH2 = ParagraphStyle('H2P', parent=sty['Heading2'], fontSize=12,
                                textColor=colors.HexColor('#2c5282'), spaceBefore=6, spaceAfter=4)
                            sBody = ParagraphStyle('BodJ', parent=sty['BodyText'], fontSize=10, leading=14, alignment=TA_JUSTIFY, spaceAfter=4)
                            sBul = ParagraphStyle('BulP', parent=sBody, leftIndent=18, bulletIndent=6, spaceAfter=2)
                            sSub = ParagraphStyle('SubPc', parent=sty['Normal'], fontSize=11, alignment=TA_CENTER, textColor=colors.grey)
                            sTitle = ParagraphStyle('Judul', parent=sty['Title'], fontSize=20, alignment=TA_CENTER,
                                spaceAfter=14, textColor=colors.HexColor('#1a365d'))
                            
                            def _rv(L, V): return [Paragraph(f'<b>{L}</b>', sBody), Paragraph(str(V), sBody)]
                            
                            _buf = BytesIO()
                            doc = SimpleDocTemplate(_buf, pagesize=A4, leftMargin=2*cm, rightMargin=2*cm,
                                topMargin=2*cm, bottomMargin=2.5*cm,
                                title='Laporan Analisis Sentimen Kebijakan Publik', author='AI Sentimen App')
                            story = []
                            
                            def _page_no(canvas, ddoc):
                                canvas.saveState()
                                canvas.setFont('Helvetica', 8); canvas.setFillColor(colors.grey)
                                canvas.drawCentredString(A4[0]/2.0, 1.2*cm, f'Halaman {ddoc.page}')
                                canvas.drawString(2*cm, 1.2*cm, 'Analisis Sentimen Kebijakan Publik — AI Powered')
                                canvas.restoreState()
                            
                            # ========== COVER ==========
                            story.append(Spacer(1, 1.5*cm))
                            story.append(Paragraph('LAPORAN ANALISIS SENTIMEN', sTitle))
                            story.append(Paragraph('Kebijakan Publik Berbasis AI', ParagraphStyle('tm', parent=sTitle, fontSize=14)))
                            story.append(Spacer(1, 0.3*cm))
                            story.append(Paragraph(f'Tanggal Laporan: <b>{datetime.datetime.now().strftime("%d %B %Y — %H:%M WIB")}</b>', sSub))
                            story.append(Spacer(1, 0.8*cm))
                            story.append(Table([
                                ['Total Volume Data', 'Sentimen Dominan', 'Total Engagement'],
                                [f"{_met['total_volume']:,}", str(_met['sentiment_dominant']), f"{_met['total_engagement']:,}"]
                            ], colWidths=[5.5*cm]*3, style=TableStyle([
                                ('BACKGROUND',(0,0),(-1,0),colors.HexColor('#1a365d')),('TEXTCOLOR',(0,0),(-1,0),colors.white),
                                ('FONTNAME',(0,0),(-1,0),'Helvetica-Bold'),('FONTSIZE',(0,0),(-1,-1),10),
                                ('ALIGN',(0,0),(-1,-1),'CENTER'),('VALIGN',(0,0),(-1,-1),'MIDDLE'),
                                ('BOTTOMPADDING',(0,0),(-1,-1),10),('TOPPADDING',(0,0),(-1,-1),10),
                                ('GRID',(0,0),(-1,-1),0.3,colors.lightgrey),
                                ('BACKGROUND',(0,1),(-1,1),colors.HexColor('#f7fafc'))
                            ])))
                            story.append(PageBreak())
                            
                            # ========== BAB I ==========
                            story.append(Paragraph('BAB I — PENGATURAN TARGET SCRAPER', sH1))
                            story.append(Paragraph('Konfigurasi target scraper yang tersimpan (target_config.json) pada saat penarikan data:', sBody))
                            story.append(Spacer(1, 0.2*cm))
                            _st_raw = (_cfg or {}).get('source_types')
                            if isinstance(_st_raw, str): _st_raw = [_st_raw]
                            if not _st_raw: _st_raw = [(_cfg or {}).get('source_type') or '-']
                            
                            _url_portals = _gen.get('news_portal_urls') or ['https://www.kompas.com/']
                            if isinstance(_url_portals, list):
                                _url_s = ', '.join(str(u) for u in _url_portals if u)
                            else: _url_s = str(_url_portals)
                            
                            _rows_c = [
                                _rv('Platform Sasaran Aktif', ', '.join(str(x) for x in _st_raw if x)),
                                _rv('Tanggal Mulai', _gen.get('start_date','-')),
                                _rv('Tanggal Akhir', _gen.get('end_date','-')),
                                _rv('Kata Kunci Target', ', '.join(_gen.get('keywords',[]) or ['-'])),
                                _rv('Profil/Akun Target', ', '.join(_gen.get('profiles',[]) or ['-'])),
                                _rv('Hashtag Target', ', '.join(_gen.get('hashtags',[]) or ['-'])),
                                _rv('Batas Twitter (X)', _gen.get('max_results_twitter', _gen.get('max_results','-'))),
                                _rv('Batas Instagram (per profil)', _gen.get('max_results_instagram', _gen.get('max_results','-'))),
                                _rv('Batas LinkedIn (per target)', _gen.get('max_results_linkedin', _gen.get('max_results','-'))),
                                _rv('Batas Portal Berita', _gen.get('max_results_news', _gen.get('max_results','-'))),
                                _rv('URL Portal Berita', _url_s),
                            ]
                            _t_cfg = Table(_rows_c, colWidths=[4.5*cm, 11.5*cm], style=TableStyle([
                                ('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),6),
                                ('RIGHTPADDING',(0,0),(-1,-1),6),('TOPPADDING',(0,0),(-1,-1),5),
                                ('BOTTOMPADDING',(0,0),(-1,-1),5),('GRID',(0,0),(-1,-1),0.3,colors.lightgrey),
                                ('BACKGROUND',(0,0),(0,-1),colors.HexColor('#edf2f7')),
                            ]))
                            story.append(_t_cfg); story.append(PageBreak())
                            
                            # ========== BAB II ==========
                            story.append(Paragraph('BAB II — FILTER ANALISIS SAAT INI', sH1))
                            story.append(Paragraph('Filter sidebar yang diterapkan saat laporan diekspor:', sBody))
                            story.append(Spacer(1, 0.2*cm))
                            _plat = ', '.join(_plats) if _plats else '(Semua)'
                            if isinstance(_drng, tuple) and len(_drng)==2:
                                _rw = f'{_drng[0]} s/d {_drng[1]}'
                            else: _rw = '-'
                            # (gunakan _metrics untuk metrik, ganti semua reference _met → _metrics dibawah)
                            _m = _metrics
                            _rows_f = [
                                _rv('Platform Terfilter', _plat),
                                _rv('Rentang Waktu Analisis', _rw),
                                _rv('Jumlah Baris Sesuai Filter', f"{_m['total_volume']:,} baris"),
                                _rv('Jumlah Terlabel Sentimen', f"{_m['total_sentiment_labelled']:,}"),
                                _rv('Persentase Positif', f"{_m['persen_pos']:.2f}%"),
                                _rv('Persentase Netral', f"{_m['persen_neu']:.2f}%"),
                                _rv('Persentase Negatif', f"{_m['persen_neg']:.2f}%"),
                            ]
                            _t_fi = Table(_rows_f, colWidths=[4.5*cm, 11.5*cm], style=TableStyle([
                                ('VALIGN',(0,0),(-1,-1),'TOP'),('GRID',(0,0),(-1,-1),0.3,colors.lightgrey),
                                ('LEFTPADDING',(0,0),(-1,-1),6),('RIGHTPADDING',(0,0),(-1,-1),6),
                                ('TOPPADDING',(0,0),(-1,-1),5),('BOTTOMPADDING',(0,0),(-1,-1),5),
                                ('BACKGROUND',(0,0),(0,-1),colors.HexColor('#fff7ed')),
                            ]))
                            story.append(_t_fi); story.append(Spacer(1, 0.3*cm))
                            
                            # ========== BAB III ==========
                            story.append(Paragraph('BAB III — VISUALISASI ANALITIK SENTIMEN', sH1))
                            story.append(Paragraph('Visualisasi hasil analisis sentimen publik berdasarkan data yang tersedia:', sBody))
                            story.append(Spacer(1, 0.2*cm))
                            
                            # 3.1 Pie
                            story.append(Paragraph('3.1 Distribusi Sentimen Publik', sH2))
                            pie_b = _c_pie(int(_m['pos_count']), int(_m['neg_count']), int(_m['neu_count']))
                            if pie_b:
                                story.append(Image(pie_b, width=12*cm, height=9.5*cm, hAlign='CENTER'))
                                story.append(Spacer(1, 0.3*cm))
                                _rows_d = [
                                    ['Kategori','Jumlah','Persentase'],
                                    ['Positif', f"{_m['pos_count']:,}", f"{_m['persen_pos']:.2f}%"],
                                    ['Netral',  f"{_m['neu_count']:,}", f"{_m['persen_neu']:.2f}%"],
                                    ['Negatif', f"{_m['neg_count']:,}", f"{_m['persen_neg']:.2f}%"],
                                    ['Total (Terlabel)', f"{_m['pos_count']+_m['neu_count']+_m['neg_count']:,}", '100.00%'],
                                ]
                                _td = Table(_rows_d, colWidths=[5*cm,4*cm,4*cm], hAlign='CENTER', style=TableStyle([
                                    ('BACKGROUND',(0,0),(-1,0),colors.HexColor('#2c5282')),('TEXTCOLOR',(0,0),(-1,0),colors.white),
                                    ('FONTNAME',(0,0),(-1,0),'Helvetica-Bold'),('ALIGN',(0,0),(-1,-1),'CENTER'),
                                    ('FONTNAME',(0,-1),(-1,-1),'Helvetica-Bold'),('GRID',(0,0),(-1,-1),0.3,colors.lightgrey),
                                    ('FONTSIZE',(0,0),(-1,-1),10),('TOPPADDING',(0,0),(-1,-1),6),
                                    ('BOTTOMPADDING',(0,0),(-1,-1),6),
                                ]))
                                story.append(_td)
                            else:
                                story.append(Paragraph('_Belum ada data sentimen terlabel._', sBody))
                            story.append(PageBreak())
                            
                            # 3.2 Tren
                            story.append(Paragraph('3.2 Tren Sentimen Harian', sH2))
                            _tr_b = _c_tren(_df_report)
                            if _tr_b: story.append(Image(_tr_b, width=17*cm, height=8*cm, hAlign='CENTER'))
                            else: story.append(Paragraph('_Data tanggal tidak mencukupi untuk grafik tren._', sBody))
                            story.append(Spacer(1, 0.4*cm))
                            # 3.3 Platform
                            story.append(Paragraph('3.3 Volume Data per Platform Sumber', sH2))
                            _pl_b = _c_plat(_df_report)
                            if _pl_b: story.append(Image(_pl_b, width=17*cm, height=7*cm, hAlign='CENTER'))
                            else: story.append(Paragraph('_Data platform sumber tidak tersedia._', sBody))
                            story.append(Spacer(1, 0.4*cm))
                            # 3.4 Keywords
                            story.append(Paragraph('3.4 Top Kata Kunci Populer', sH2))
                            try:
                                _kw_t = extract_top_keywords(_df_report, 10)
                                _kw_l = [w.strip() for w in _kw_t.split(',') if w.strip()]
                            except Exception: _kw_l = []
                            _kw_b = _c_kw(_kw_l)
                            if _kw_b: story.append(Image(_kw_b, width=17*cm, height=8*cm, hAlign='CENTER'))
                            elif _kw_l:
                                for w in _kw_l[:10]: story.append(Paragraph(f'- <b>{w}</b>', sBul))
                            else: story.append(Paragraph('_Belum cukup data teks baku._', sBody))
                            story.append(PageBreak())
                            
                            # ========== BAB IV ==========
                            story.append(Paragraph('BAB IV — RINGKASAN EKSEKUTIF NARASI', sH1))
                            _tv = int(_m['total_volume'])
                            _ai_txt = _narasi
                            if _tv < 500 and not _ai_txt:
                                story.append(Paragraph(
                                    f'<b>⚠️ Catatan:</b> Volume data baru <b>{_tv:,}</b> data. '
                                    'Batas minimum Ringkasan Eksekutif AI adalah <b>500 data</b>. '
                                    'Disarankan menambah data scraper terlebih dahulu.',
                                    ParagraphStyle('warnP', parent=sBody, textColor=colors.HexColor('#8a6d3b'),
                                        backColor=colors.HexColor('#fcf8e3'), borderPadding=8)))
                            elif _ai_txt:
                                # Pisahkan per paragraf (enter dobel)
                                _paras = re.split(r"\n{2,}|", _ai_txt.replace('\r\n','\n'))
                                for _pg in _paras:
                                    _pg = _pg.strip()
                                    if not _pg: continue
                                    if re.match(r'^(\d+\.\s+[A-Z]|###\s)', _pg):
                                        _lines = _pg.split('\n', 1)
                                        story.append(Paragraph(_lines[0].replace('###','').strip(), sH2))
                                        if len(_lines)>1 and _lines[1].strip():
                                            story.append(Paragraph(_lines[1].strip().replace('\n','<br/>'), sBody))
                                    else:
                                        story.append(Paragraph(_pg.replace('\n','<br/>'), sBody))
                                    story.append(Spacer(1, 0.15*cm))
                            else:
                                story.append(Paragraph(
                                    'Narasi AI belum di-generate. Kembali ke Tab Analitik Sentimen → klik '
                                    'tombol <b>Perbarui Analisis Narasi</b> → export ulang PDF.', sBody))
                            story.append(PageBreak())
                            
                            # ========== BAB V ==========
                            story.append(Paragraph('BAB V — LAMPIRAN: 10 SAMPEL DATA TERBARU', sH1))
                            story.append(Paragraph('Sampel 10 data terbaru yang lolos filter. Data lengkap lihat Supabase Cloud:', sBody))
                            story.append(Spacer(1, 0.3*cm))
                            if not _df_report.empty:
                                _ds = _df_report.head(10).copy()
                                _nc = ['date','username','source_platform','sentiment_label','confidence_score','cleaned_text','raw_text']
                                _av = [c for c in _nc if c in _ds.columns]; _ds = _ds[_av].fillna('-')
                                _hm = {'date':'Tgl','username':'Username','source_platform':'Platform','sentiment_label':'Sent.',
                                       'confidence_score':'Conf.','cleaned_text':'Teks Baku (EYD)','raw_text':'Teks Mentah'}
                                _dr = [[_hm.get(c,c) for c in _av]]
                                for _, _r in _ds.iterrows():
                                    _rl = []
                                    for c in _av:
                                        v = _r[c]
                                        if c in ('cleaned_text','raw_text'):
                                            v_s = str(v)[:85].replace('\n',' ')
                                            if len(str(v))>85: v_s += '...'
                                        elif c == 'confidence_score':
                                            try: v_s = f"{float(v):.0%}"
                                            except: v_s = str(v)
                                        else: v_s = str(v)[:35]
                                        _rl.append(v_s)
                                    _dr.append(_rl)
                                _nc2 = len(_av); _tw = 17*cm
                                _ws = [_tw/_nc2]*_nc2
                                for _i,_c in enumerate(_av):
                                    if _c in ('cleaned_text','raw_text'): _ws[_i] = 5.5*cm
                                _ts = Table(_dr, colWidths=_ws, repeatRows=1)
                                _sc = [
                                    ('BACKGROUND',(0,0),(-1,0),colors.HexColor('#2d3748')),
                                    ('TEXTCOLOR',(0,0),(-1,0),colors.white),('FONTNAME',(0,0),(-1,0),'Helvetica-Bold'),
                                    ('FONTSIZE',(0,0),(-1,-1),7.5),('VALIGN',(0,0),(-1,-1),'TOP'),
                                    ('LEFTPADDING',(0,0),(-1,-1),4),('RIGHTPADDING',(0,0),(-1,-1),4),
                                    ('TOPPADDING',(0,0),(-1,-1),4),('BOTTOMPADDING',(0,0),(-1,-1),4),
                                    ('GRID',(0,0),(-1,-1),0.2,colors.lightgrey),
                                    ('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white, colors.HexColor('#f7fafc')]),
                                ]
                                _si = _av.index('sentiment_label') if 'sentiment_label' in _av else -1
                                if _si >= 0:
                                    for _i in range(1, len(_dr)):
                                        _val = str(_dr[_i][_si]).lower()
                                        _co = '#2D6A4F' if 'positif' in _val else ('#B00020' if 'negatif' in _val else None)
                                        if _co: _sc.append(('TEXTCOLOR', (_si,_i),(_si,_i), colors.HexColor(_co)))
                                _ts.setStyle(TableStyle(_sc)); story.append(_ts)
                            else:
                                story.append(Paragraph('_Tidak ada data untuk ditampilkan._', sBody))
                            story.append(Spacer(1, 1*cm))
                            story.append(Paragraph('— Akhir Laporan —', ParagraphStyle('akhir',
                                parent=sty['Normal'], fontSize=10, alignment=TA_CENTER, textColor=colors.grey)))
                            doc.build(story, onFirstPage=_page_no, onLaterPages=_page_no)
                            _buf.seek(0); return _buf
                        except Exception as _errPDF:
                            st.exception(_errPDF)
                            return None
                    
                    # Generate filename
                    _tfn = datetime.datetime.now().strftime('%Y%m%d_%H%M')
                    _fname = f"Laporan_Sentimen_Kebijakan_{_tfn}.pdf"
                    _placeholder = st.empty()
                    if _placeholder.button("📥 Susun PDF", use_container_width=True, type="secondary", key="btn_prep_pdf"):
                        with st.spinner("Menyusun laporan PDF + grafik visual... (±5-15 detik)"):
                            _pdf_buf = _build_charts_and_pdf()
                        if _pdf_buf:
                            _placeholder.empty()
                            st.toast("✅ Laporan PDF siap diunduh", icon="📥")
                            st.download_button(
                                label="⬇️ Download Laporan PDF",
                                data=_pdf_buf,
                                file_name=_fname,
                                mime="application/pdf",
                                use_container_width=True,
                                type="primary",
                                key="btn_dl_pdf_done"
                            )
            
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
    
    # ============================================================
    # [UX FIX] Inisialisasi session_state untuk RINGKASAN PERSISTEN
    # (Tetap tampil walau tombol sebelah diklik — hilang hanya jika F5 atau tombol bersihkan)
    # ============================================================
    import datetime as _dt_nowmod
    if "last_scraper_result" not in st.session_state:
        st.session_state.last_scraper_result = None
    if "last_ml_result" not in st.session_state:
        st.session_state.last_ml_result = None
    
    # --- Helper simpan ke session_state (supaya tidak duplikat code)
    def _save_result(key: str, status: str, title: str, message: str = "",
                      stdout: str = "", stderr: str = "", exit_code=None,
                      extra=None):
        payload = {
            "time": _dt_nowmod.datetime.now().strftime("%d-%b %H:%M:%S"),
            "status": status,        # "success" | "error" | "info"
            "title": title,
            "message": message,
            "stdout": stdout or "",
            "stderr": stderr or "",
            "exit_code": exit_code,
            "extra": extra or {}       # misal metrics ML: total/sukses/gagal
        }
        st.session_state[key] = payload
    
    # --- Helper render satu card ringkasan dari session_state ---
    def _render_card(key: str, label_default: str):
        data = st.session_state.get(key)
        if not data:
            st.caption(f"_Belum ada riwayat {label_default}._")
            return
        t = data.get("time") or "-"
        title = data.get("title") or label_default
        msg = data.get("message") or ""
        status = data.get("status") or "info"
        
        if status == "success":
            st.success(f"⏰ {t}\n\n🟢 {title}")
        elif status == "error":
            st.error(f"⏰ {t}\n\n🔴 {title}")
        else:
            st.info(f"⏰ {t}\n\nℹ️ {title}")
        
        if msg:
            st.markdown(msg)
        
        extra = data.get("extra") or {}
        if extra and extra.get("is_ml_summary"):
            st_total   = extra.get("sum_total")
            st_sukses = extra.get("sum_success")
            st_gagal  = extra.get("sum_failed")
            if st_total is not None:
                cA, cB, cC = st.columns(3)
                cA.metric("📦 Total", st_total)
                cB.metric("✅ Sukses", st_sukses or 0,
                         delta=f"-{st_gagal or 0} gagal" if st_gagal else None,
                         delta_color="inverse" if st_gagal else "normal")
                tag_list = []
                if extra.get("has_eyd"): tag_list.append("EYD AI")
                if extra.get("has_svm"): tag_list.append("SVM")
                cC.metric("⚙️ Aktif", " + ".join(tag_list) or "Minimal")
        
        with st.expander(f"📋 Log ({label_default} — {t})"):
            if data.get("stdout"):
                st.code(data["stdout"], language="text")
            if data.get("stderr") and data["stderr"].strip():
                    st.markdown("_Catatan (stderr):_")
                    st.code(data["stderr"], language="text")
            if data.get("exit_code") is not None:
                        st.caption(f"Exit code: {data['exit_code']}")
    
    col_run1, col_run2 = st.columns(2)
    
    # Pemicu Scraper
    with col_run1:
        st.markdown("**Langkah 1: Penarikan Data (Scraper)**")
        st.caption("Menghubungkan ke platform Apify Cloud untuk menarik data mentah terbaru sesuai konfigurasi.")
        
        scraper_run_btn = st.button("🚀 Jalankan Penarikan Data Sekarang", type="primary", use_container_width=True, key="btn_run_scraper")
        
        if scraper_run_btn:
            import re as _re
            with st.status("🚀 Menghubungkan ke Apify Cloud & menarik data mentah...", expanded=True) as status_scrape:
                try:
                    result = subprocess.run(
                        [sys.executable, "01_run_scraper.py"],
                        capture_output=True, text=True, check=True
                    )
                    # Parsing jumlah baris yang disimpan (cari log terakhir total baris)
                    total_match = _re.search(r"Total\s*(?:baris|rows)\s*(?:telah)?\s*(?:disimpan|saved|inserted):?\s*(\d+)" , result.stdout, flags=_re.IGNORECASE)
                    sum_text = f"{total_match.group(1)} baris baru disimpan" if total_match else "Selesai (cek log)"
                    title = f"Penarikan data selesai — {sum_text}"
                    status_scrape.update(label=f"✅ {title}!", state="complete", expanded=False)
                    st.toast(f"✅ Scraper selesai — {sum_text}", icon="🚀")
                    st.success(f"✅ Proses penarikan data mentah selesai — {sum_text}.")
                    with st.expander("📋 Tampilkan Log Scraper (sementara, lihat panel RIWAYAT dibawah untuk persistent)"):
                        st.code(result.stdout, language="text")
                        if result.stderr and result.stderr.strip():
                            st.markdown("*Catatan stderr (non-blocking):* ")
                            st.code(result.stderr, language="text")
                    # [PERSISTEN SAVE] — Langkah 1 Scraper
                    _save_result(
                        key="last_scraper_result",
                        status="success",
                        title=title,
                        message="Data mentah (RAW) siap diproses oleh Langkah 2 AI/ML",
                        stdout=result.stdout,
                        stderr=result.stderr,
                        exit_code=0,
                        extra={"total_baris": int(total_match.group(1)) if total_match else None}
                    )
                    if st.button("🔄 Refresh Dashboard (Lihat Data Baru)", use_container_width=True, key="btn_refresh_scrape"):
                        st.rerun()
                except subprocess.CalledProcessError as e:
                    title = f"GAGAL (Exit code: {e.returncode})"
                    status_scrape.update(label=f"❌ {title}", state="error", expanded=True)
                    st.toast(f"❌ Scraper {title}", icon="🚨")
                    st.error(f"❌ Gagal menjalankan modul scraper — {title}.")
                    with st.expander("📋 Tampilkan Log Kesalahan (sementara)", expanded=True):
                        st.code(e.stdout if e.stdout else "Tidak ada output.", language="text")
                        if e.stderr:
                            st.markdown("_Stderr:_")
                            st.code(e.stderr, language="text")
                    _save_result(
                        key="last_scraper_result",
                        status="error",
                        title=title,
                        message="Periksa token APIFY_API_TOKEN di Secrets atau lihat log dibawah",
                        stdout=e.stdout,
                        stderr=e.stderr,
                        exit_code=e.returncode
                    )
                        
    # Pemicu Pipeline AI/ML
    with col_run2:
        st.markdown("**Langkah 2: Proses AI & Klasifikasi ML**")
        st.caption("Prapemrosesan bahasa baku EYD oleh model Gemini AI dan pelabelan sentimen oleh SVM lokal.")
        
        ml_run_btn = st.button("🧠 Jalankan Proses AI & ML Sekarang", use_container_width=True, key="btn_run_pipeline_ml")
        
        if ml_run_btn:
            import re as _re2
            # Regex extract helper
            def _extract_sum(pattern: str, text: str):
                m = _re2.search(pattern, text)
                return int(m.group(1)) if m else None
            
            with st.status("🧠 Menstandardisasi teks EYD & melabeli sentimen via SVM...", expanded=True) as status_ml:
                combined_out = ""
                combined_err = ""
                exit_code = None
                try:
                    result = subprocess.run(
                        [sys.executable, "01_pipeline_data.py"],
                        capture_output=True, text=True, check=True
                    )
                    combined_out = result.stdout or ""
                    combined_err = result.stderr or ""
                    exit_code = 0
                except subprocess.CalledProcessError as e:
                    combined_out = e.stdout or ""
                    combined_err = e.stderr or ""
                    exit_code = e.returncode
                
                # ---- Parse [SUMMARY] blocks dari output ----
                sum_total   = _extract_sum(r"\[SUMMARY\]\[TOTAL\][^=]*=\s*(\d+)", combined_out)
                sum_success = _extract_sum(r"\[SUMMARY\]\[SUCCESS\][^=]*=\s*(\d+)", combined_out)
                sum_failed  = _extract_sum(r"\[SUMMARY\]\[FAILED\][^=]*=\s*(\d+)", combined_out)
                has_eyd     = bool(_re2.search(r"\[SUMMARY\]\[EYD\].*=\s*YES", combined_out))
                has_svm     = bool(_re2.search(r"\[SUMMARY\]\[LABEL\].*=\s*YES", combined_out))
                no_data_flag = "[INFO][NO_DATA]" in combined_out or exit_code == 2
                extra_summary = {
                    "is_ml_summary": True,
                    "sum_total": sum_total,
                    "sum_success": sum_success,
                    "sum_failed": sum_failed,
                    "has_eyd": has_eyd,
                    "has_svm": has_svm
                }
                
                # --- Tampilkan status berdasarkan exit_code ---
                if exit_code == 2 or no_data_flag:
                    # ---- Tidak ada data RAW untuk diproses ----
                    title = "ℹ️ Tidak ada data mentah (RAW) yang perlu diproses"
                    status_ml.update(label=title, state="complete", expanded=True)
                    st.toast("ℹ️ Tidak ada data RAW baru — jalankan Langkah 1 Scraper dulu", icon="💡")
                    pesan_info = (
                        "💡 **Tidak ada data baru untuk diproses.**\n\n"
                        "Pemrosesan AI/ML hanya mengolah data dengan status `RAW` (belum diproses).\n\n"
                        "**Langkah yang disarankan:** Jalankan **🚀 Langkah 1: Penarikan Data (Scraper)** terlebih dahulu."
                    )
                    st.info(pesan_info)
                    with st.expander("📋 Log Pemrosesan (sementara — lihat RIWAYAT dibawah)"):
                        if combined_out: st.code(combined_out, language="text")
                        if combined_err: st.code(combined_err, language="text")
                    _save_result("last_ml_result", "info", title,
                                 message="Jalankan Langkah 1 Scraper dahulu untuk mendapatkan data RAW baru.",
                                 stdout=combined_out, stderr=combined_err, exit_code=exit_code,
                                 extra=extra_summary)
                elif exit_code == 0:
                    # ---- BERHASIL memproses data ----
                    title = "✅ AI & Klasifikasi SVM Selesai"
                    if sum_success is not None:
                        title += f" — {sum_success} data diproses"
                    status_ml.update(label=title, state="complete", expanded=False)
                    st.toast(title, icon="🧠")
                    st.success(title)
                    if sum_total is not None:
                        c1, c2, c3 = st.columns(3)
                        c1.metric("📦 Total Data RAW", sum_total)
                        c2.metric("✅ Berhasil Diproses", sum_success or 0,
                                  delta=f"-{sum_failed or 0} gagal" if sum_failed else None,
                                  delta_color="inverse" if sum_failed else "normal")
                        tags = []
                        if has_eyd: tags.append("EYD AI")
                        if has_svm: tags.append("SVM Sentimen")
                        c3.metric("⚙️ Aktifkan", " + ".join(tags) or "Minimal")
                    with st.expander("📋 Log (sementara — lihat RIWAYAT dibawah)"):
                        st.code(combined_out, language="text")
                        if combined_err and combined_err.strip():
                            st.code(combined_err, language="text")
                    _save_result("last_ml_result", "success", title,
                                 message="Data sentimen siap ditampilkan di Tab Analitik.",
                                 stdout=combined_out, stderr=combined_err, exit_code=0,
                                 extra=extra_summary)
                    if st.button(
                            "🔄 Refresh Dashboard (Tampilkan Hasil Sentimen)",
                            use_container_width=True, type="primary", key="btn_refresh_ml"
                        ):
                            st.rerun()
                else:
                    # ---- ERROR (exit code 1 atau lain) ----
                    title = f"❌ Gagal AI/ML (Exit {exit_code})"
                    status_ml.update(label=title, state="error", expanded=True)
                    st.toast(title, icon="🚨")
                    st.error(title + ". Periksa stderr dibawah: Cek Syntax / File Config GEMINI_API_KEY & model SVM.")
                    with st.expander("📋 Log Kesalahan (sementara)", expanded=True):
                        if combined_out: st.code(combined_out, language="text")
                        if combined_err: st.code(combined_err, language="text")
                    _save_result("last_ml_result", "error", title,
                                 message="Cek syntax 01_pipeline_data.py atau environment.",
                                 stdout=combined_out, stderr=combined_err, exit_code=exit_code,
                                 extra=extra_summary)
    
    # ============================================================================
    # [UX FIX — BARU] Panel RINGKASAN PERSISTEN EKSEKUSI TERAKHIR
    # Tetap TAMPIL walaupun tombol sebelah diklik (berbeda scope handler — tersimpan di session_state)
    # Hilang JIKA DAN HANYA JIKA user tekan tombol Bersihkan / browser di-refresh (F5).
    # ============================================================================
    st.divider()
    col_hist_title, col_hist_clear = st.columns([6,1])
    with col_hist_title:
        st.subheader("📜 Ringkasan Eksekusi Terakhir (Persistent)")
        st.caption("Notifikasi di panel ini **tetap tampil** walaupun Anda klik tombol lain. Hanya hilang jika F5 atau tombol bersihkan.")
    with col_hist_clear:
        st.write(" ")
        if st.button("🗑️ Bersihkan", use_container_width=True, key="btn_clear_history"):
            st.session_state.last_scraper_result = None
            st.session_state.last_ml_result = None
            st.rerun()
    
    col_hist1, col_hist2 = st.columns(2)
    with col_hist1:
        st.markdown("**🚀 Langkah 1 — Penarikan Data (Scraper)**")
        _render_card("last_scraper_result", "Langkah 1 Scraper")
    with col_hist2:
        st.markdown("**🧠 Langkah 2 — Proses AI/ML**")
        _render_card("last_ml_result", "Langkah 2 AI & SVM")
