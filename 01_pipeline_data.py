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

def clean_batch_with_gemini(client, batch_items):
    """
    Mengirimkan batch 25 teks sekaligus ke Gemini API dalam 1 panggil JSON prompt.
    batch_items: list of (platform_id, raw_text)
    Returns: dict mapping platform_id -> cleaned_text
    """
    if not client:
        return {pid: raw for pid, raw in batch_items}

    payload = [{"id": idx, "text": raw} for idx, (pid, raw) in enumerate(batch_items)]
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
            for item in parsed:
                if isinstance(item, dict) and "id" in item and "cleaned" in item:
                    id_to_cleaned[item["id"]] = str(item["cleaned"]).strip('"\'')

            result = {}
            for idx, (pid, raw) in enumerate(batch_items):
                result[pid] = id_to_cleaned.get(idx, raw)
            return result
        except Exception as e:
            if attempt == 2:
                print(f"[WARNING] Batch cleaning fallback ke teks asli: {e}")
                return {pid: raw for pid, raw in batch_items}
            time.sleep(1.5 * (attempt + 1))

    return {pid: raw for pid, raw in batch_items}

def process_batch(batch_items, gemini_client, model, vectorizer):
    """
    Memproses 1 batch data (50 baris) secara ultra-cepat dengan Gemini AI & SVM.
    """
    cleaned_dict = clean_batch_with_gemini(gemini_client, batch_items)
    
    pids = [pid for pid, _ in batch_items]
    cleaned_texts = [cleaned_dict.get(pid, raw) for pid, raw in batch_items]
    
    sentiment_labels = [None] * len(batch_items)
    confidence_scores = [0.0] * len(batch_items)
    
    if model and vectorizer:
        try:
            vec_texts = vectorizer.transform(cleaned_texts)
            preds = model.predict(vec_texts)
            probs = model.predict_proba(vec_texts)
            for i in range(len(batch_items)):
                sentiment_labels[i] = preds[i]
                confidence_scores[i] = float(np.max(probs[i]))
        except Exception as e:
            print(f"[ERROR] Inferensi SVM batch gagal: {e}")
            
    batch_updates = [
        (cleaned_texts[i], sentiment_labels[i], confidence_scores[i], pids[i])
        for i in range(len(pids))
    ]
    try:
        db_manager.perbarui_cuitan_batch(batch_updates)
        return len(batch_updates)
    except Exception as e:
        print(f"[ERROR] Bulk update DB batch gagal: {e}")
        return 0

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
        
    batch_size = 50
    batches = [rows[i:i + batch_size] for i in range(0, len(rows), batch_size)]
    
    print(f"[INFO] Memulai pemrosesan High-Speed Parallel Batching ({len(batches)} batch @ {batch_size} data/batch) untuk {len(rows)} data RAW...")
    print(f"[INFO] Model SVM: {'TERSEDIA' if (model and vectorizer) else 'TIDAK DITEMUKAN'}")
    print(f"[INFO] Gemini Client: {'TERSEDIA' if gemini_client else 'TIDAK ADA API KEY (copy teks asli)'}")
    
    success_count = 0
    max_workers = 10
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [
            executor.submit(process_batch, batch, gemini_client, model, vectorizer)
            for batch in batches
        ]
        for future in as_completed(futures):
            try:
                success_count += future.result()
            except Exception as e:
                print(f"[ERROR] Batch execution failed: {e}")
                
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
    print(f"[SUCCESS] Pipa data selesai! Berhasil memproses {success_count} dari {len(rows)} data dalam {len(batches)} batch.")
    sys.exit(0)

if __name__ == "__main__":
    process_pipeline()
