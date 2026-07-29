
import os
import sys
import time
import numpy as np
import joblib
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor, as_completed
from google import genai
from google.genai import types
import db_manager

# Memuat file .env — override=False agar env var sistem (GitHub Actions) tidak tertimpa
load_dotenv(override=False)

DB_FILE = 'sentimen_kebijakan.db'
MODEL_PATH = 'models/svm_model.pkl'
VEC_PATH = 'models/tfidf_vectorizer.pkl'

def get_gemini_client():
    """
    Menginisialisasi klien Gemini SDK resmi secara aman.
    """
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key or api_key == "YOUR_GEMINI_API_KEY_HERE":
        print("[WARNING] Kunci API Gemini ('GEMINI_API_KEY') tidak dikonfigurasi di file .env.")
        print("[WARNING] Prapemrosesan AI (Gemini) akan dinonaktifkan (teks asli akan disalin ke cleaned_text).")
        return None
    try:
        return genai.Client(api_key=api_key)
    except Exception as e:
        print(f"[ERROR] Gagal menginisialisasi Gemini Client: {e}")
        return None

def load_svm_model():
    """
    Memuat model SVM dan TF-IDF Vectorizer jika tersedia.
    """
    if os.path.exists(MODEL_PATH) and os.path.exists(VEC_PATH):
        try:
            model = joblib.load(MODEL_PATH)
            vectorizer = joblib.load(VEC_PATH)
            return model, vectorizer
        except Exception as e:
            print(f"[ERROR] Gagal memuat model SVM: {e}")
            return None, None
    else:
        print("[WARNING] Berkas model SVM ('models/svm_model.pkl') tidak ditemukan.")
        print("[WARNING] Prediksi sentimen otomatis dilewati. Silakan jalankan '02_train_model.py' terlebih dahulu.")
        return None, None

def clean_text_with_gemini(client, raw_text):
    """
    Menggunakan Gemini 2.5 Flash untuk membersihkan bahasa tidak baku/gaul menjadi bahasa baku EYD.
    """
    if not client:
        # Fallback jika API key tidak tersedia
        return raw_text
        
    system_prompt = (
        "Tugas Anda adalah menstandardisasi teks media sosial berbahasa Indonesia berikut menjadi "
        "bahasa Indonesia baku yang sesuai dengan Ejaan yang Disempurnakan (EYD).\n"
        "Aturan:\n"
        "1. Perbaiki salah ketik (typo), singkatan, dan bahasa gaul (slang).\n"
        "2. Pertahankan makna asli, emosi, dan sentimen dari teks tersebut.\n"
        "3. DILARANG KERAS memberikan komentar, analisis, atau kalimat tambahan apa pun.\n"
        "4. Cukup kembalikan teks hasil standardisasi murni secara langsung."
    )
    
    # Coba memanggil API Gemini dengan mekanisme retry (3x percobaan)
    for attempt in range(3):
        try:
            response = client.models.generate_content(
                model='gemini-3.1-flash-lite',
                contents=raw_text,
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    temperature=0.1,
                    max_output_tokens=300
                )
            )
            cleaned = response.text.strip()
            
            # Bersihkan pembungkus blok markdown jika ada
            if cleaned.startswith("```") and cleaned.endswith("```"):
                cleaned = cleaned.strip("`").strip()
                if cleaned.startswith("text\n"):
                    cleaned = cleaned[5:].strip()
                    
            # Hapus tanda kutip luar pembungkus teks jika ada
            cleaned = cleaned.strip('"\'')
            return cleaned
            
        except Exception as e:
            if attempt == 2:
                print(f"[ERROR] Gagal permanen setelah 3x percobaan menghubungi Gemini API untuk teks '{raw_text[:30]}...': {e}")
                return raw_text
            # Exponential backoff: tunggu sebentar sebelum mencoba lagi
            time.sleep(2 * (attempt + 1))
            
    return raw_text

def process_single_row(item, gemini_client, model, vectorizer):
    platform_id, raw_text = item
    try:
        # Langkah A: Pembersihan Bahasa via AI
        cleaned_text = clean_text_with_gemini(gemini_client, raw_text)
        
        # Langkah B: Prediksi Sentimen via SVM
        sentiment_label = None
        confidence_score = 0.0
        
        if model and vectorizer:
            try:
                vec_text = vectorizer.transform([cleaned_text])
                sentiment_label = model.predict(vec_text)[0]
                probs = model.predict_proba(vec_text)[0]
                confidence_score = float(np.max(probs))
            except Exception as e:
                print(f"  [ERROR][{platform_id}]: Gagal inferensi SVM: {e}")
                
        # Langkah C: Perbarui baris di Database
        db_manager.perbarui_cuitan_setelah_proses(platform_id, cleaned_text, sentiment_label, confidence_score)
        print(f"[OK][{platform_id}] Sentimen: {sentiment_label} ({confidence_score:.0%}) | Baku: {cleaned_text[:40]}...")
        return True
    except Exception as e:
        print(f"[ERROR][{platform_id}]: Gagal memproses baris: {e}")
        return False

def process_pipeline():
    # 0. Deduplikasi Data RAW sebelum pemrosesan AI & ML
    # Menghapus duplikat (username + raw_text sama), mempertahankan date (created_at) paling awal
    deleted_dups = db_manager.hapus_duplikasi_data_raw()
    if deleted_dups > 0:
        print(f"[INFO] Prapemrosesan: {deleted_dups} data duplikat RAW berhasil dibersihkan.")

    # 1. Inisialisasi Klien Gemini & Muat Model SVM
    gemini_client = get_gemini_client()
    model, vectorizer = load_svm_model()
    rows = db_manager.ambil_cuitan_mentah()
    
    if not rows:
        print("[INFO][NO_DATA] Tidak ada data cuitan mentah baru (status 'RAW') untuk diproses.")
        print("[HINT] Jalankan dulu Langkah 1: Penarikan Data (Scraper) untuk mendapatkan data RAW baru.")
        sys.exit(2)
        
    print(f"[INFO] Memulai pemrosesan paralel (Multithreading 10 worker) untuk {len(rows)} data cuitan mentah baru...")
    print(f"[INFO] Model SVM: {'TERSEDIA' if (model and vectorizer) else 'TIDAK DITEMUKAN (prediksi sentimen dilewati)'}")
    print(f"[INFO] Gemini Client: {'TERSEDIA' if gemini_client else 'TIDAK ADA API KEY (EYD cleanup otomatis = copy teks asli)'}")
    
    success_count = 0
    max_workers = 10 if gemini_client else 20
    
    # 4. Paralelisasi eksekusi per baris menggunakan ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [
            executor.submit(process_single_row, item, gemini_client, model, vectorizer)
            for item in rows
        ]
        for future in as_completed(futures):
            if future.result():
                success_count += 1
                
    # --- Ringkasan akhir dengan tag untuk parsing di UI ---
    failed_count = len(rows) - success_count
    print("")
    print("=" * 60)
    print(f"[SUMMARY][TOTAL]   : Total data RAW tersedia  = {len(rows)}")
    print(f"[SUMMARY][SUCCESS] : Berhasil diproses        = {success_count}")
    print(f"[SUMMARY][FAILED]  : Gagal / dilewati          = {failed_count}")
    if model and vectorizer:
        print(f"[SUMMARY][LABEL]   : Label sentimen (SVM) diberikan = YES")
    else:
        print(f"[SUMMARY][LABEL]   : Label sentimen (SVM) diberikan = NO (model tidak ada)")
    if gemini_client:
        print(f"[SUMMARY][EYD]     : Standardisasi EYD (Gemini)  = YES")
    else:
        print(f"[SUMMARY][EYD]     : Standardisasi EYD (Gemini)  = NO (teks asli disalin langsung)")
    print("=" * 60)
    
    if success_count == 0 and len(rows) > 0:
        print("[EXIT_CODE=1] Semua baris GAGAL diproses!")
        sys.exit(1)
    print(f"[SUCCESS] Pipa data selesai! Berhasil memproses {success_count} dari {len(rows)} data (Multithreading).")
    sys.exit(0)

if __name__ == "__main__":
    process_pipeline()
