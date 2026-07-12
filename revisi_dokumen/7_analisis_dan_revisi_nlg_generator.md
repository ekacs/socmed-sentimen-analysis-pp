# Analisis & Penyesuaian Kode `nlg_generator.py`
**Proyek:** Analisis Sentimen Kebijakan Publik Berbasis Kecerdasan Buatan (AI)

---

## 1. Analisis Relevansi Kode Saat Ini
Secara umum, logika dasar pemrosesan petunjuk (*prompt engineering*) di dalam file `nlg_generator.py` Anda **sangat baik, relevan, dan kokoh**. Instruksi peran (sebagai Analis Kebijakan Publik Senior), batasan anti-halusinasi yang ketat, serta penentuan format luaran yang terstruktur merupakan praktik terbaik dalam rekayasa prompt.

Namun, dari sisi **arsitektur perangkat lunak** dan **integrasi SDK**, kode tersebut memerlukan beberapa penyesuaian penting agar dapat digunakan dalam sistem tingkat produksi (*production-ready*) dan dapat diintegrasikan secara mulus dengan dasbor Streamlit Anda.

Berikut adalah poin-poin analisis dan peluang perbaikan:

| Aspek | Kondisi Kode Saat Ini | Rekomendasi Penyesuaian | Alasan |
| :--- | :--- | :--- | :--- |
| **SDK (Library) API** | Menggunakan `google-generativeai` | Migrasi ke SDK resmi terbaru: `google-genai` | Google telah merilis SDK terpadu baru (`google-genai`) yang lebih cepat, efisien, dan menjadi standar pengembangan masa depan. |
| **Pemilihan Model** | Menggunakan `gemini-1.5-pro` | Tingkatkan ke seri terbaru `gemini-2.5-pro` atau `gemini-2.5-flash` | Seri Gemini 2.5 menawarkan kemampuan penalaran analitis, kepatuhan instruksi (*instruction following*), dan kecepatan respon yang jauh lebih superior. |
| **Struktur Kode** | Script bersifat linier statis (nilai metrik di-*hardcode*) | Ubah menjadi fungsi modular yang menerima parameter dinamis | Agar file `app.py` di Streamlit dapat mengimpor fungsi ini secara langsung dan mengalirkan hasil perhitungan Pandas secara *real-time*. |
| **Keamanan Kredensial** | Kunci API diinisialisasi secara implisit | Muat secara eksplisit via `os.getenv` melalui pustaka `python-dotenv` | Menjamin keandalan deteksi kunci API baik di lingkungan lokal (`.env`) maupun server cloud (Streamlit Secrets). |

---

## 2. Struktur Perbandingan Kode

### Kode Sebelum Penyesuaian (Membatasi Relevansi):
```python
import google.generativeai as genai

# Nilai statis (tidak dinamis untuk Streamlit)
total_data = 1250
...
# Memanggil SDK lama (legacy)
model = genai.GenerativeModel('gemini-1.5-pro')
response = model.generate_content(prompt_narasi)
```

### Kode Setelah Penyesuaian (Modular, Menggunakan SDK Baru, dan Dinamis):
Berikut adalah pembaharuan kode `nlg_generator.py` yang telah dioptimalkan untuk integrasi Streamlit dan menggunakan standar teknologi terbaru Google AI:

```python
import os
from google import genai
from google.genai import types
from dotenv import load_dotenv

# Memuat variabel lingkungan dari file .env (untuk pengujian lokal)
load_dotenv()

def generate_executive_summary(
    total_data: int,
    persen_negatif: float,
    persen_positif: float,
    persen_netral: float,
    top_keywords: str,
    contoh_cuitan: str,
    kebijakan_fokus: str = "Layanan KRL Commuter Line Jabodetabek"
) -> str:
    """
    Menghasilkan laporan ringkasan eksekutif analitis berbasis AI (NLG) 
    berdasarkan metrik agregat yang dihitung secara dinamis dari database.
    """
    # 1. Inisialisasi Klien SDK google-genai terbaru secara aman
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("Kesalahan: Variabel lingkungan 'GEMINI_API_KEY' tidak ditemukan.")
    
    client = genai.Client(api_key=api_key)

    # 2. Perancangan Prompt Berbasis Data Aktual (Bebas Halusinasi)
    prompt_narasi = f"""
    Bertindaklah sebagai Analis Kebijakan Publik Senior di Kementerian Perhubungan.
    Tugas Anda adalah menulis Laporan Ringkasan Eksekutif mengenai sentimen publik terhadap {kebijakan_fokus} selama satu minggu terakhir.

    Anda WAJIB mendasarkan analisis Anda HANYA pada data statistik aktual berikut:
    - Total volume percakapan: {total_data} interaksi.
    - Distribusi Sentimen: {persen_negatif}% Negatif, {persen_positif}% Positif, dan {persen_netral}% Netral.
    - Isu utama yang dikeluhkan (Top Keywords): {top_keywords}.
    - Contoh suara langsung masyarakat: {contoh_cuitan}.

    ATURAN PENULISAN MUTLAK:
    1. Panjang teks MINIMAL 250 kata.
    2. Gunakan gaya bahasa birokrasi pemerintahan (formal, objektif, taktis, dan bebas dari emosi subjektif).
    3. DILARANG KERAS berasumsi atau berhalusinasi di luar data statistik di atas. Jika data terbatas, deskripsikan keterbatasan tersebut secara profesional apa adanya.
    4. Struktur Laporan harus terdiri dari 3 bagian dengan sub-heading bertanda markdown:
       ### [Situasi Saat Ini]
       (Uraikan volume percakapan dan dominasi sentimen publik secara komparatif)
       
       ### [Analisis Permasalahan]
       (Uraikan akar masalah utama berdasarkan Top Keywords dan kutipan suara masyarakat)
       
       ### [Rekomendasi Kebijakan]
       (Sajikan 2-3 butir rekomendasi taktis-realistis yang ditujukan bagi pimpinan/manajemen)

    Tuliskan laporan analisis Anda sekarang:
    """

    try:
        # 3. Eksekusi menggunakan model generasi terbaru (Gemini 2.5 Pro untuk analisis mendalam)
        response = client.models.generate_content(
            model='gemini-2.5-pro',
            contents=prompt_narasi,
            # Mengatur suhu rendah (low temperature) untuk meminimalkan kreativitas bebas / halusinasi
            config=types.GenerateContentConfig(
                temperature=0.15,
                max_output_tokens=1000
            )
        )
        return response.text
    except Exception as e:
        return f"Terjadi kesalahan saat menghubungi API Gemini: {str(e)}"

# Blok eksekusi mandiri untuk pengujian internal (Unit Testing)
if __name__ == "__main__":
    print("--- Memulai Simulasi Pengujian NLG Generator ---")
    hasil_simulasi = generate_executive_summary(
        total_data=1250,
        persen_negatif=60.0,
        persen_positif=10.0,
        persen_netral=30.0,
        top_keywords="terlambat, AC panas, gerbong berdesakan",
        contoh_cuitan="'Setiap pagi KRL arah Sudirman selalu telat dan AC-nya sering mati, sangat menyiksa.'"
    )
    print(hasil_simulasi)
```

---

## 3. Contoh Cara Mengintegrasikan ke Streamlit (`app.py`)
Dengan menggunakan struktur baru yang telah disesuaikan di atas, Anda dapat dengan mudah mengimpor generator ini ke dalam file dasbor Streamlit Anda secara bersih:

```python
# Di dalam file app.py Anda
import streamlit as str
import pandas as pd
from nlg_generator import generate_executive_summary

# ... Kode penarikan data dari database ke Pandas DataFrame (df) ...

# 1. Menghitung metrik secara dinamis dari Pandas
total_cuitan = len(df)
persen_neg = (len(df[df['sentiment'] == 'Negatif']) / total_cuitan) * 100
persen_pos = (len(df[df['sentiment'] == 'Positif']) / total_cuitan) * 100
persen_neu = (len(df[df['sentiment'] == 'Netral']) / total_cuitan) * 100

# 2. Mendapatkan keyword populer & contoh cuitan dari data aktual
top_words = "AC mati, antrean panjang, transit manggarai"  # Contoh kalkulasi TF-IDF
suara_rakyat = df[df['sentiment'] == 'Negatif']['raw_text'].iloc[0] if total_cuitan > 0 else ""

# 3. Menampilkan Ringkasan NLG ke Dasbor Streamlit dengan tombol interaktif
st.subheader("Ringkasan Eksekutif Publik Berbasis AI")

if st.button("🔄 Perbarui Analisis Narasi"):
    with st.spinner("Menganalisis data dan menyusun laporan..."):
        laporan_nlg = generate_executive_summary(
            total_data=total_cuitan,
            persen_negatif=round(persen_neg, 1),
            persen_positif=round(persen_pos, 1),
            persen_netral=round(persen_neu, 1),
            top_keywords=top_words,
            contoh_cuitan=suara_rakyat
        )
        st.markdown(laporan_nlg)
```
