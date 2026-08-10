import os
import time
from google import genai
from google.genai import types
from dotenv import load_dotenv
import session_credentials

# Memuat berkas .env
load_dotenv()

def generate_executive_summary(
    total_data: int,
    persen_negatif: float,
    persen_positif: float,
    persen_netral: float,
    top_keywords: str,
    contoh_cuitan: str,
    kebijakan_fokus: str = "Kebijakan dan Isu Publik",
    api_key: str = None
) -> str:
    """
    Menghasilkan laporan ringkasan eksekutif analitis berbasis AI (NLG) 
    berdasarkan metrik agregat yang dihitung secara dinamis dari database.
    """
    # 1. Validasi Jumlah Data Minimum
    if total_data < 100:
        return (
            f"### ⚠️ Volume Data Tidak Mencukupi (Minimal 100 Data)\n\n"
            f"Data tidak cukup untuk menghasilkan narasi analisis. Minimal dibutuhkan 100 baris data yang relevan. "
            f"(Saat ini hanya tersedia **{total_data}** data CLEANED yang lolos filter).\n\n"
            f"**Rekomendasi:** Silakan lakukan penarikan data baru atau sesuaikan filter kriteria analisis Anda."
        )

    # 2. Validasi Kunci API LLM secara aman
    if not api_key:
        api_key = session_credentials.get_active_gemini_key()
    if not api_key or api_key == "YOUR_GEMINI_API_KEY_HERE":
        return (
            "### ⚠️ Kunci API LLM Belum Dikonfigurasi\n\n"
            "Fitur **Penyusunan Ringkasan Eksekutif berbasis AI (NLG)** saat ini dinonaktifkan "
            "karena kunci API `GEMINI_API_KEY` tidak ditemukan di sesi atau di file `.env`.\n\n"
            "**Langkah Pengaktifan:**\n"
            "1. Masukkan kunci API LLM Anda pada sidebar **🔐 Pengaturan API Key Sesi** atau file `.env`.\n"
            "2. Klik tombol **🔄 Perbarui Analisis Narasi** kembali."
        )

    try:
        # Inisialisasi klien SDK google-genai terbaru
        client = genai.Client(api_key=api_key)
        
        # 2. Perancangan Prompt Berbasis Data Aktual (Bebas Halusinasi)
        prompt_narasi = f"""
        Bertindaklah sebagai Analis Kebijakan Publik Senior.
        Tugas Anda adalah menulis Laporan Ringkasan Eksekutif mengenai sentimen publik terhadap fokus topik/kebijakan berikut: "{kebijakan_fokus}".

        Anda WAJIB mendasarkan analisis Anda HANYA pada data statistik aktual berikut:
        - Fokus Topik / Kebijakan: {kebijakan_fokus}.
        - Total volume percakapan: {total_data} interaksi/cuitan.
        - Distribusi Sentimen: {persen_negatif}% Negatif, {persen_positif}% Positif, dan {persen_netral}% Netral.
        - Isu utama yang dikeluhkan (Top Keywords): {top_keywords}.
        - Contoh suara langsung masyarakat: {contoh_cuitan}.

        ATURAN PENULISAN MUTLAK:
        1. Panjang teks ideal 250 - 450 kata.
        2. GAYA BAHASA FORMAL: Gunakan gaya bahasa birokrasi pemerintahan yang formal, baku, profesional, lugas, dan taktis.
        3. ANALISIS KRITIS & TRANSPARAN (TETAP MENGANDUNG KRITIK): Laporan WAJIB secara jujur, lugas, dan transparan memaparkan kritik masyarakat, poin keberatan publik, serta potensi risiko/kelemahan kebijakan berdasarkan data tanpa memperhalus (*sugarcoating*) atau menyembunyikan isu negatif.
        4. Catatan Penting Konteks Sentimen: Sentimen positif bukan berarti menandakan emosi yang positif namun bisa juga diartikan pembenaran atas suatu peristiwa dan sebaliknya.
        5. DILARANG KERAS berasumsi atau berhalusinasi di luar data statistik di atas. Jika data terbatas untuk ditarik kesimpulan yang memadai, berikan informasi secara profesional bahwa data yang diterima masih belum cukup untuk ditarik kesimpulan yang memadai.
        6. Struktur Laporan harus LENGKAP dan terdiri dari 3 bagian dengan sub-heading bertanda markdown (TIDAK BOLEH TERPOTONG):
           ### [Situasi Saat Ini]
           (Uraikan volume percakapan dan dominasi sentimen publik secara komparatif untuk fokus topik {kebijakan_fokus})
           
           ### [Analisis Permasalahan]
           (Uraikan akar masalah utama dan paparkan KRITIK tajam publik secara objektif berdasarkan Top Keywords dan kutipan suara masyarakat yang relevan dengan {kebijakan_fokus})
           
           ### [Rekomendasi Kebijakan]
           (Sajikan 2-3 butir rekomendasi taktis-realistis yang merespons kritik publik tersebut bagi pimpinan/manajemen terkait {kebijakan_fokus})
           
        7. DILARANG KERAS menuliskan judul laporan formal (seperti "LAPORAN RINGKASAN EKSEKUTIF: ..."), salam pembuka, perihal, rincian penerima (seperti "Kepada: Yth..."), atau penutup surat formal di awal maupun di akhir output. Hasil generasi harus langsung diawali dengan sub-heading pertama: "### [Situasi Saat Ini]".

        Tuliskan laporan analisis Anda secara tuntas sampai selesai tanpa terputus:
        """
        
        # 3. Eksekusi menggunakan model generasi terbaru dengan retry loop
        for attempt in range(3):
            try:
                response = client.models.generate_content(
                    model=session_credentials.get_active_gemini_model(),
                    contents=prompt_narasi,
                    config=types.GenerateContentConfig(
                        temperature=0.2,
                        max_output_tokens=3000
                    )
                )
                return response.text
            except Exception as e:
                # Jika sudah mencapai batas percobaan, lempar error agar ditangkap blok except terluar
                if attempt == 2:
                    raise e
                # Tunggu sebentar sebelum mencoba lagi (exponential backoff)
                time.sleep(2 * (attempt + 1))
        
    except Exception as e:
        err_str = str(e).lower()
        if "429" in err_str or "quota" in err_str or "resourceexhausted" in err_str or "rate limit" in err_str:
            import db_manager
            db_manager.set_gemini_quota_flag(True)
        return f"### ❌ Kesalahan API LLM\n\nGagal menghubungi server AI LLM. Detail kesalahan: {e}"

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
