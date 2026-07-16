import os
from google import genai
from google.genai import types
from dotenv import load_dotenv

# Memuat berkas .env
load_dotenv()

def generate_executive_summary(
    total_data: int,
    persen_negatif: float,
    persen_positif: float,
    persen_netral: float,
    top_keywords: str,
    contoh_cuitan: str,
    kebijakan_fokus: str = "Layanan Transportasi Publik"
) -> str:
    """
    Menghasilkan laporan ringkasan eksekutif analitis berbasis AI (NLG) 
    berdasarkan metrik agregat yang dihitung secara dinamis dari database.
    """
    # 1. Validasi Kunci API Gemini secara aman
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key or api_key == "YOUR_GEMINI_API_KEY_HERE":
        return (
            "### ⚠️ Kunci API Gemini Belum Dikonfigurasi\n\n"
            "Fitur **Penyusunan Ringkasan Eksekutif berbasis AI (NLG)** saat ini dinonaktifkan "
            "karena kunci API `GEMINI_API_KEY` tidak ditemukan atau masih bernilai standar di file `.env`.\n\n"
            "**Langkah Pengaktifan:**\n"
            "1. Buka file `.env` di direktori proyek Anda.\n"
            "2. Masukkan kunci API Gemini Anda yang valid pada variabel `GEMINI_API_KEY`.\n"
            "3. Klik tombol **🔄 Perbarui Analisis Narasi** kembali."
        )

    try:
        # Inisialisasi klien SDK google-genai terbaru
        client = genai.Client(api_key=api_key)
        
        # 2. Perancangan Prompt Berbasis Data Aktual (Bebas Halusinasi)
        prompt_narasi = f"""
        Bertindaklah sebagai Analis Kebijakan Publik Senior di Kementerian Perhubungan.
        Tugas Anda adalah menulis Laporan Ringkasan Eksekutif mengenai sentimen publik terhadap {kebijakan_fokus} selama satu minggu terakhir.

        Anda WAJIB mendasarkan analisis Anda HANYA pada data statistik aktual berikut:
        - Total volume percakapan: {total_data} interaksi/cuitan.
        - Distribusi Sentimen: {persen_negatif}% Negatif, {persen_positif}% Positif, dan {persen_netral}% Netral.
        - Isu utama yang dikeluhkan (Top Keywords): {top_keywords}.
        - Contoh suara langsung masyarakat: {contoh_cuitan}.

        ATURAN PENULISAN MUTLAK:
        1. Panjang teks MINIMAL 200 kata.
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
        
        # 3. Eksekusi menggunakan model generasi terbaru
        response = client.models.generate_content(
            model='gemini-3.1-flash-lite',  # gemini-3.1-flash-lite: kompatibel dengan API key baru
            contents=prompt_narasi,
            config=types.GenerateContentConfig(
                temperature=0.15,
                max_output_tokens=1000
            )
        )
        return response.text
        
    except Exception as e:
        return f"### ❌ Kesalahan API Gemini\n\nGagal menghubungi server AI Gemini. Detail kesalahan: {e}"

if __name__ == "__main__":
    print("--- Memulai Simulasi Pengujian NLG Generator ---")
    # Simulasi running
    hasil_simulasi = generate_executive_summary(
        total_data=1250,
        persen_negatif=60.0,
        persen_positif=10.0,
        persen_netral=30.0,
        top_keywords="terlambat, AC panas, gerbong berdesakan",
        contoh_cuitan="'Setiap pagi KRL arah Sudirman selalu telat dan AC-nya sering mati, sangat menyiksa.'"
    )
    print(hasil_simulasi)
