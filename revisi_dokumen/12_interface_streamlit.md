# Integrasi Konfigurasi Target Dinamis Melalui Antarmuka Streamlit

**Proyek:** Analisis Sentimen Kebijakan Publik Berbasis Kecerdasan Buatan (AI)

---

## 1. Tinjauan Pendekatan (UI/UX)

Memindahkan konfigurasi dari pengeditan berkas manual (`target_config.json`) ke antarmuka pengguna (UI) di Streamlit adalah langkah yang sangat tepat untuk meningkatkan *User Experience* (UX).

Dengan pendekatan ini, dasbor Streamlit tidak hanya berfungsi sebagai alat **Visualisasi (Read-only)**, tetapi juga sebagai **Pusat Kendali (Control Center)**. Pengguna (seperti analis atau pembuat kebijakan) dapat mengubah target analisis, mengatur kata kunci, dan memicu penarikan data langsung dari peramban web tanpa perlu memahami kode pemrograman.

---

## 2. Alur Kerja Arsitektur Baru

1. **Frontend (Streamlit):** Menyediakan formulir interaktif di panel samping (*sidebar*) atau tab khusus "Pengaturan".
2. **State Management:** Input dari pengguna dibaca oleh Streamlit dan diubah menjadi format *dictionary* Python.
3. **Penyimpanan Konfigurasi:** Saat pengguna menekan tombol "Simpan Target", Streamlit akan menimpa (*overwrite*) berkas `target_config.json` lokal dengan konfigurasi terbaru.
4. **Eksekusi (Opsional):** Streamlit dapat menyediakan tombol "Jalankan Penarikan Data Sekarang" yang memicu skrip `01_run_scraper.py` berjalan di latar belakang menggunakan modul `subprocess`.

---

## 3. Konsep Tata Letak (Layout) Antarmuka untuk Pemula

Bagi pemula, membuat tampilan yang rapi di Streamlit bisa dilakukan dengan memanfaatkan fitur pembagian kolom (`st.columns`) dan formulir (`st.form`). Berikut adalah gambaran visual sketsa tata letaknya:

```Shell
[ HEADER ] ⚙️ Pusat Kendali Penarikan Data
[ SELECTBOX ] Pilih Platform Target: (Misal: Twitter, Instagram)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[ BINGKAI FORMULIR KONFIGURASI ]
  📅 Periode Waktu Penarikan:
  [ Kotak Tanggal Mulai ]      [ Kotak Tanggal Akhir ]
  
  🎯 Target Sasaran Analisis:
  [ Input Teks: Kata Kunci (Keywords)                ]
  [ Input Teks: Nama Profil Akun (Usernames)         ]
  [ Input Teks: Tagar (Hashtags)                     ]
  
  ⚙️ Pengaturan Tambahan:
  [ Slider: Batas Maksimal Data yang Ditarik         ]
  
  [ Tombol: 💾 Simpan Konfigurasi Target ]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[ Tombol Utama: 🚀 Jalankan Penarikan Data Sekarang ]
```

---

## 4. Implementasi Kode Streamlit (`app_config_ui.py`)

Berikut adalah rancangan kodenya. Kami telah menambahkan fitur pemilihan **Periode Waktu**, **Kata Kunci**, **Nama Profil**, dan **Hashtag** ke dalam formulir sesuai konsep tata letak di atas.

```python
import streamlit as st
import json
import subprocess
import os
import datetime

CONFIG_FILE = 'target_config.json'

def simpan_konfigurasi(config_dict):
    """Menyimpan dictionary Python ke dalam berkas JSON."""
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config_dict, f, indent=4)
    st.success("✅ Konfigurasi berhasil disimpan!")

def menu_konfigurasi_scraper():
    """Fungsi komponen UI untuk menu pengaturan target scraping."""
    st.header("⚙️ Pusat Kendali Penarikan Data")
    st.markdown("Atur target pemantauan isu publik dari berbagai platform digital.")
  
    # Memilih platform utama
    platform_pilihan = st.selectbox(
        "Pilih Platform Target:",
        ("Twitter (X)", "Instagram", "LinkedIn", "Portal Berita")
    )
  
    # Form dinamis berdasarkan platform
    with st.form("form_konfigurasi"):
        st.subheader(f"Konfigurasi Parameter: {platform_pilihan}")
    
        # 1. Periode Waktu Penarikan
        st.markdown("**📅 Periode Waktu Penarikan**")
        col1, col2 = st.columns(2)
        with col1:
            start_date = st.date_input("Tanggal Mulai", datetime.date.today() - datetime.timedelta(days=7))
        with col2:
            end_date = st.date_input("Tanggal Akhir", datetime.date.today())
        
        # 2. Target Sasaran (Kata Kunci, Profil, Hashtag)
        st.markdown("**🎯 Target Sasaran Analisis**")
        kata_kunci = st.text_input("Kata Kunci (pisahkan dengan koma):", "Ibu Kota Baru, IKN")
        nama_profil = st.text_input("Nama Profil Target (pisahkan dengan koma):", "kemenpupr, kemendagri")
        hashtag = st.text_input("Hashtag / Tagar (pisahkan dengan koma):", "#IKNNusantara")
    
        # 3. Pengaturan Tambahan
        st.markdown("**⚙️ Pengaturan Tambahan**")
        max_data = st.slider("Batas Maksimal Data (Post/Artikel/Cuitan):", 10, 1000, 100)
    
        # Tombol Submit di dalam Form
        if st.form_submit_button("💾 Simpan Konfigurasi Target"):
            # Format data untuk disimpan
            config_data = {
                "source_type": platform_pilihan.lower().replace(" ", "_").replace("(x)", "").strip(),
                "config": {
                    "general": {
                        "start_date": start_date.strftime("%Y-%m-%d"),
                        "end_date": end_date.strftime("%Y-%m-%d"),
                        "keywords": [k.strip() for k in kata_kunci.split(",") if k.strip()],
                        "profiles": [p.strip() for p in nama_profil.split(",") if p.strip()],
                        "hashtags": [h.strip() for h in hashtag.split(",") if h.strip()],
                        "max_results": max_data
                    }
                }
            }
            simpan_konfigurasi(config_data)

    # Tombol Eksekusi Manual di Streamlit (Di luar form)
    st.divider()
    st.markdown("### 🚀 Eksekusi Penarikan Data")
    st.warning("Perhatian: Penarikan data membutuhkan waktu beberapa saat. Jangan tutup halaman ini saat proses berjalan.")
  
    if st.button("Jalankan Penarikan Data Sekarang", type="primary"):
        with st.spinner("Mengontak server cloud Apify dan memproses data..."):
            try:
                # Memanggil skrip python secara terpisah (Subprocess)
                result = subprocess.run(
                    ["python", "01_run_scraper.py"],
                    capture_output=True, text=True, check=True
                )
                st.success("Proses penarikan data selesai!")
                st.info("Log Sistem:\n" + result.stdout)
            
                # Memaksa muat ulang halaman agar grafik ter-update dengan data baru
                st.rerun() 
            except subprocess.CalledProcessError as e:
                st.error("Gagal menjalankan scraper.")
                st.code(e.stderr)

# ===============================================
# CARA INTEGRASI KE DALAM app.py UTAMA
# ===============================================
# Di dalam app.py, Anda dapat membuat Tab khusus untuk kendali ini:
# 
# tab1, tab2, tab3 = st.tabs(["📊 Analitik Sentimen", "📑 Jejak Audit Data", "⚙️ Pengaturan Target"])
# 
# with tab1:
#     render_dashboard_charts()
#
# with tab2:
#     render_audit_table()
#
# with tab3:
#     menu_konfigurasi_scraper()
```

---

## 5. Keuntungan Konsep Ini bagi Pengguna Akhir

1. **Bebas Kode (*No-Code Experience*):** Pengguna akhir atau pengambil kebijakan sama sekali tidak perlu melihat apalagi menyunting berkas `target_config.json`. Mereka dapat mengatur parameter secara langsung melalui antarmuka grafis.
2. **Validasi Input Terjaga:** Dengan menggunakan *slider* angka, *checkbox*, dan *dropdown (multiselect)*, kita mencegah pengguna memasukkan format data yang salah (misalnya, memasukkan teks pada parameter angka `max_tweets`), yang bisa membuat program *crash*.
3. **Kendali Penuh (On-Demand Trigger):** Meskipun GitHub Actions sudah diatur untuk berjalan setiap tengah malam, tombol "Jalankan Penarikan Data Sekarang" memberikan fleksibilitas bagi analis jika ada isu mendadak (misalnya: *viral/trending topic* yang butuh pemantauan menit itu juga). Pendekatan hibrida (otomatis + manual) ini sangat dihargai dalam aplikasi skala *enterprise*.
