import os
import sys
import time
import json
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

def get_gemini_client(api_key=None):
    """
    Menginisialisasi klien Gemini SDK resmi secara aman.
    Jika api_key diberikan secara eksplisit, gunakan api_key tersebut. Jika tidak, gunakan os.getenv("GEMINI_API_KEY").
    """
    if not api_key:
        api_key = os.getenv("GEMINI_API_KEY")
    if not api_key or api_key == "YOUR_GEMINI_API_KEY_HERE":
        print("[WARNING] Kunci API Gemini ('GEMINI_API_KEY') tidak dikonfigurasi.")
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

def clean_unique_texts_batch(client, batch_texts):
    """
    Mengirimkan batch unik (maks 25-30 teks) ke Gemini API dalam 1 JSON prompt.
    batch_texts: list of (idx, raw_text)
    Returns: dict mapping idx -> cleaned_text
    """
    if not client:
        return {idx: raw for idx, raw in batch_texts}

    payload = [{"id": idx, "text": raw} for idx, raw in batch_texts]
    payload_str = json.dumps(payload, ensure_ascii=False)

    system_prompt = (
        "Anda adalah asisten tata bahasa Indonesia baku (EYD).\n"
        "Input berupa array JSON bertipe [{\"id\": int, \"text\": string}].\n"
        "Tugas Anda: perbaiki typo, singkatan, dan slang dari tiap teks menjadi bahasa Indonesia baku (EYD) "
        "tanpa mengubah makna asli.\n"
        "OUTPUT HARUS HANYA berupa array JSON murni bertipe [{\"id\": int, \"cleaned\": string}].\n"
        "Jangan ubah nilai 'id'. DILARANG KERAS menambah teks/komentar di luar JSON."
    )

    for attempt in range(3):
        try:
            response = client.models.generate_content(
                model='gemini-3.1-flash-lite',
                contents=payload_str,
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    temperature=0.1,
                    max_output_tokens=4000
                )
            )
            raw_resp = response.text.strip()
            if raw_resp.startswith("```"):
                raw_resp = raw_resp.strip("`").strip()
                if raw_resp.startswith("json\n"):
                    raw_resp = raw_resp[5:].strip()

            parsed = json.loads(raw_resp)
            id_to_cleaned = {}
            if isinstance(parsed, list):
                for item in parsed:
                    if isinstance(item, dict) and "id" in item and "cleaned" in item:
                        id_to_cleaned[item["id"]] = str(item["cleaned"]).strip('"\'')

            result = {}
            for idx, raw in batch_texts:
                result[idx] = id_to_cleaned.get(idx, raw)
            return result
        except Exception as e:
            err_str = str(e).lower()
            if "429" in err_str or "quota" in err_str or "resourceexhausted" in err_str or "rate limit" in err_str:
                print(f"[ERROR] ❌ Kuota token Gemini AI telah HABIS / Rate Limit tercapai: {e}")
                db_manager.set_gemini_quota_flag(True)
            if attempt == 2:
                print(f"[WARNING] Batch cleaning fallback ke teks asli: {e}")
                return {idx: raw for idx, raw in batch_texts}
            time.sleep(1.5 * (attempt + 1))

    return {idx: raw for idx, raw in batch_texts}

def process_pipeline():
    # 0. Deduplikasi Data RAW sebelum pemrosesan AI & ML
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
        
    print(f"[INFO] Ditemukan {len(rows)} baris data RAW untuk diproses.")
    
    # 2. Caching & Deduplikasi Teks Mentah
    eyd_cache = db_manager.ambil_eyd_cache()
    if eyd_cache:
        print(f"[INFO] Memuat {len(eyd_cache):,} pasangan EYD dari cache lokal.")

    # Ekstrak teks mentah unik yang belum ada di cache
    uncached_unique_texts = list(set([raw for _, raw in rows if raw and raw not in eyd_cache]))
    cache_hits = len(rows) - len(uncached_unique_texts)
    
    if cache_hits > 0:
        print(f"[INFO] ⚡ Caching Hit: {cache_hits} baris data langsung menggunakan hasil EYD dari cache (bebas API token).")
        
    if gemini_client and uncached_unique_texts:
        batch_size = 25
        unique_indexed = list(enumerate(uncached_unique_texts))
        batches = [unique_indexed[i:i + batch_size] for i in range(0, len(unique_indexed), batch_size)]
        
        print(f"[INFO] Memproses {len(uncached_unique_texts)} teks unik belum ter-cache via Gemini AI ({len(batches)} batch @ maks {batch_size} teks/batch)...")
        
        max_workers = min(8, max(1, len(batches)))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [
                executor.submit(clean_unique_texts_batch, gemini_client, batch)
                for batch in batches
            ]
            for future in as_completed(futures):
                try:
                    cleaned_res = future.result()
                    for idx, cleaned_t in cleaned_res.items():
                        raw_orig = uncached_unique_texts[idx]
                        eyd_cache[raw_orig] = cleaned_t
                except Exception as e:
                    print(f"[ERROR] Eksekusi batch AI unik gagal: {e}")

    # Map seluruh data RAW ke cleaned_texts menggunakan eyd_cache
    pids = [pid for pid, _ in rows]
    cleaned_texts = [eyd_cache.get(raw, raw) for _, raw in rows]

    # 3. Vectorized Machine Learning (SVM) Massal
    sentiment_labels = [None] * len(rows)
    confidence_scores = [0.0] * len(rows)
    
    if model and vectorizer:
        print(f"[INFO] Melakukan inferensi ML (SVM) massal secara ter-vektorisasi untuk {len(rows)} data...")
        try:
            vec_texts = vectorizer.transform(cleaned_texts)
            preds = model.predict(vec_texts)
            probs = model.predict_proba(vec_texts)
            for i in range(len(rows)):
                sentiment_labels[i] = preds[i]
                confidence_scores[i] = float(np.max(probs[i]))
        except Exception as e:
            print(f"[ERROR] Inferensi SVM massal gagal: {e}")

    # 4. Single-Transaction Bulk Database Update
    print(f"[INFO] Menyimpan hasil pemrosesan AI & ML ke database dalam 1 transaksi massal...")
    batch_updates = [
        (cleaned_texts[i], sentiment_labels[i], confidence_scores[i], pids[i])
        for i in range(len(rows))
    ]
    
    try:
        db_manager.perbarui_cuitan_batch(batch_updates)
        success_count = len(batch_updates)
    except Exception as e:
        print(f"[ERROR] Bulk update DB gagal: {e}")
        success_count = 0

    failed_count = len(rows) - success_count
    print("")
    print("=" * 60)
    print(f"[SUMMARY][TOTAL]   : Total data RAW tersedia  = {len(rows)}")
    print(f"[SUMMARY][SUCCESS] : Berhasil diproses        = {success_count}")
    print(f"[SUMMARY][FAILED]  : Gagal / dilewati          = {failed_count}")
    if model and vectorizer:
        print(f"[SUMMARY][LABEL]   : Label sentimen (SVM) diberikan = YES")
    else:
        print(f"[SUMMARY][LABEL]   : Label sentimen (SVM) diberikan = NO")
    if gemini_client:
        print(f"[SUMMARY][EYD]     : Standardisasi EYD (Gemini Batch) = YES")
    else:
        print(f"[SUMMARY][EYD]     : Standardisasi EYD (Gemini Batch) = NO")
    print("=" * 60)
    
    if success_count == 0 and len(rows) > 0:
        print("[EXIT_CODE=1] Semua baris GAGAL diproses!")
        sys.exit(1)
    print(f"[SUCCESS] Pipa data selesai! Berhasil memproses {success_count} dari {len(rows)} data.")
    sys.exit(0)

if __name__ == "__main__":
    process_pipeline()
