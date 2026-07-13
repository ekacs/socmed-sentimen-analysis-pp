import os
import pandas as pd
import joblib
from sklearn.model_selection import train_test_split
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.svm import SVC
from sklearn.metrics import classification_report, accuracy_score

def train_and_save_model(dataset_path='dataset_pelatihan.csv', model_dir='models'):
    # 1. Pastikan direktori model ada
    if not os.path.exists(model_dir):
        os.makedirs(model_dir)
        print(f"[INFO] Membuat direktori '{model_dir}' untuk penyimpanan model.")
        
    # 2. Muat data latih
    try:
        df = pd.read_csv(dataset_path, encoding='utf-8')
    except FileNotFoundError:
        print(f"[ERROR] Berkas data latih '{dataset_path}' tidak ditemukan.")
        print("[ERROR] Jalankan terlebih dahulu 'python generate_mock_training_data.py'")
        return
        
    print(f"[INFO] Memuat {len(df)} baris data latih dari '{dataset_path}'.")
    
    # Bersihkan baris kosong
    df = df.dropna(subset=['text_baku', 'label_sentimen'])
    
    X = df['text_baku']
    y = df['label_sentimen']
    
    # 3. Bagi data menjadi data latih dan data uji (80% latih, 20% uji)
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )
    
    print(f"[INFO] Jumlah data latih: {len(X_train)}")
    print(f"[INFO] Jumlah data uji: {len(X_test)}")
    
    # 4. Ekstraksi Fitur Teks menggunakan TF-IDF
    print("[INFO] Melakukan ekstraksi fitur teks TF-IDF...")
    vectorizer = TfidfVectorizer(max_features=5000, ngram_range=(1, 2))
    X_train_vectorized = vectorizer.fit_transform(X_train)
    X_test_vectorized = vectorizer.transform(X_test)
    
    # 5. Pelatihan Model SVM (Support Vector Classifier)
    # probability=True agar model bisa mengembalikan skor probabilitas (confidence score)
    print("[INFO] Melatih model Support Vector Machine (SVM)...")
    svm_model = SVC(kernel='linear', probability=True, class_weight='balanced', random_state=42)
    svm_model.fit(X_train_vectorized, y_train)
    
    # 6. Evaluasi Model
    y_pred = svm_model.predict(X_test_vectorized)
    acc = accuracy_score(y_test, y_pred)
    print(f"[SUCCESS] Pelatihan selesai. Akurasi Model Uji: {acc:.2%}")
    print("\n--- Laporan Klasifikasi Uji ---")
    print(classification_report(y_test, y_pred))
    
    # 7. Ekspor Model dan Vectorizer ke format file .pkl menggunakan joblib
    model_path = os.path.join(model_dir, 'svm_model.pkl')
    vec_path = os.path.join(model_dir, 'tfidf_vectorizer.pkl')
    
    joblib.dump(svm_model, model_path)
    joblib.dump(vectorizer, vec_path)
    
    print(f"[SUCCESS] Model disimpan di: '{model_path}'")
    print(f"[SUCCESS] Vectorizer disimpan di: '{vec_path}'")

if __name__ == "__main__":
    train_and_save_model()
