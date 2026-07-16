import os
import numpy as np
import joblib
from dotenv import load_dotenv
from google import genai
from google.genai import types
import db_manager

# Memuat file .env
load_dotenv()

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
        print(f"[ERROR] Galat saat menghubungi Gemini API untuk teks '{raw_text[:30]}...': {e}")
        return raw_text

def process_pipeline():
    # 1. Inisialisasi Klien Gemini & Muat Model SVM
    gemini_client = get_gemini_client()
    svm_model, vectorizer = load_svm_model()
    
    # 2. Ambil data dengan status 'RAW'
    rows = db_manager.ambil_cuitan_mentah()
    
    if not rows:
        print("[INFO] Tidak ada data cuitan mentah baru (status 'RAW') untuk diproses.")
        return
        
    print(f"[INFO] Memulai pemrosesan untuk {len(rows)} data cuitan mentah baru...")
    
    success_count = 0
    
    # 4. Iterasi dan proses setiap baris
    for tweet_id, raw_text in rows:
        print(f"[INFO] Memproses Tweet ID: {tweet_id}")
        
        # Langkah A: Pembersihan Bahasa via AI
        cleaned_text = clean_text_with_gemini(gemini_client, raw_text)
        print(f"  [RAW] : {raw_text}")
        print(f"  [BAKU]: {cleaned_text}")
        
        # Langkah B: Prediksi Sentimen via SVM
        sentiment_label = None
        confidence_score = 0.0
        
        if svm_model and vectorizer:
            try:
                # Transformasi teks
                vec_text = vectorizer.transform([cleaned_text])
                # Prediksi label
                sentiment_label = svm_model.predict(vec_text)[0]
                # Hitung skor keyakinan (probabilitas maksimum)
                probs = svm_model.predict_proba(vec_text)[0]
                confidence_score = float(np.max(probs))
                print(f"  [SVM] : Sentimen -> {sentiment_label} (Keyakinan: {confidence_score:.2%})")
            except Exception as e:
                print(f"  [ERROR]: Gagal melakukan inferensi SVM: {e}")
                
        # Langkah C: Perbarui baris di Database
        try:
            db_manager.perbarui_cuitan_setelah_proses(tweet_id, cleaned_text, sentiment_label, confidence_score)
            success_count += 1
        except Exception as e:
            print(f"  [ERROR]: Gagal memperbarui database: {e}")
    print(f"[SUCCESS] Pipa data selesai! Berhasil memproses {success_count} dari {len(rows)} data.")

if __name__ == "__main__":
    process_pipeline()
