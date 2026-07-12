# Arsitektur Modul Scraping Twitter (X)
**Basis:** Apify Python SDK (*Microservice Ingestion*)

---

## 1. Tinjauan Arsitektur (*Architecture Overview*)
Modul ini dirancang khusus sebagai mikroservis asinkron yang bertugas menarik data (*Data Ingestion*) secara andal dari platform media sosial X (dahulu Twitter). Dengan mengadopsi **Apify Python SDK**, arsitektur ini memindahkan seluruh beban komputasi berat, manajemen rotasi alamat IP (Proxy), dan penanganan batasan laju pemanggilan (*Rate Limits / IP Blocks*) ke platform komputasi awan serverless milik Apify. 

Sistem lokal hanya bertindak sebagai pengendali, perangkai kueri, pengambil dataset hasil, serta penyimpan data akhir ke dalam basis data lokal. Hal ini menjamin efisiensi sumber daya lokal dan stabilitas pengambilan data jangka panjang.

---

## 2. Tumpukan Teknologi (*Technology Stack*)
* **Bahasa Pemrograman:** Python 3.10+
* **Pustaka Utama:** `apify-client` (SDK Resmi), `json`, `sqlite3` (atau driver PostgreSQL `psycopg2`), `datetime`
* **Layanan Pihak Ketiga:** Platform Cloud Apify (Direkomendasikan menggunakan Actor: `apidojo/tweet-scraper` atau Actor Twitter Scraper sejenis yang stabil).
* **Format Konfigurasi Input:** Berkas JSON dinamis (`target_config.json`).

---

## 3. Komponen Utama & Alur Sistem
Sistem dibagi menjadi tiga komponen logis utama yang membentuk pipa pemrosesan data linier:

```
┌────────────────────────────────────────┐
│  A. Komponen Konfigurasi Dinamis       │  --> Membaca target_config.json
└──────────────────┬─────────────────────┘  --> Menyusun Advanced Search Query
                   │ (Kueri Twitter Valid)
                   ▼
┌────────────────────────────────────────┐
│  B. Komponen Eksekusi & SDK Apify      │  --> Inisialisasi ApifyClient
└──────────────────┬─────────────────────┘  --> Trigger Actor secara Sinkron (Blocking)
                   │ (Dataset ID dari Apify)
                   ▼
┌────────────────────────────────────────┐
│  C. Komponen Transformasi & Penyimpanan│  --> Ambil Data per baris (Iterate Items)
└────────────────────────────────────────┘  --> Validasi Skema & Upsert (INSERT OR IGNORE)
```

### A. Komponen Konfigurasi Dinamis (*Dynamic Configuration Input*)
Komponen ini membaca berkas `target_config.json` yang memuat parameter pencarian dari pengguna tanpa perlu menyentuh atau memodifikasi kode program utama Python.
* **Fungsi Utama:** Membaca berkas konfigurasi, memproses array parameter, dan merangkai nilai-beda nilai tersebut menjadi satu string pencarian lanjutan (*Advanced Search Query*) Twitter yang valid secara sintaksis.

**Contoh Format `target_config.json`:**
```json
{
  "keywords": ["Ibu Kota Baru", "IKN", "Infrastruktur"],
  "hashtags": ["#IKNNusantara", "#KebijakanPusat"],
  "usernames": ["jokowi", "kemenpupr"],
  "max_tweets": 500,
  "language": "id"
}
```

### B. Komponen Eksekusi & SDK Apify (*The Controller*)
Komponen utama pengontrol alur kerja scraping dengan melakukan pemanggilan API ke platform cloud Apify.
1. **Inisialisasi:** Membuka sesi koneksi terautentikasi menggunakan token API Apify unik.
2. **Transformasi Payload:** Menerjemahkan parameter dari `target_config.json` menjadi payload JSON masukan yang dipahami oleh Actor Twitter Scraper (misal: menggabungkan kata kunci menggunakan operator boolean `OR`).
3. **Eksekusi Sinkron:** Memicu Actor di server cloud Apify dan memblokir eksekusi skrip lokal sementara waktu (`client.actor(...).call()`) hingga proses penarikan data selesai sepenuhnya di cloud.

### C. Komponen Transformasi & Penyimpanan Data (*The Sink*)
Setelah pemanggilan Actor selesai, komponen ini mengambil dataset hasil akhir dari server Apify menggunakan *Dataset ID*.
1. **Dataset Iteration:** Mengambil hasil pencarian secara baris-per-baris melalui memori secara efisien menggunakan fungsi generator bawaan SDK `iterate_items()`.
2. **Validasi Skema:** Memetakan skema JSON bawaan dari Apify ke dalam skema tabel SQL lokal/online yang telah ditentukan.
3. **Strategi Upsert (Pencegahan Duplikasi):** Menggunakan klausa pelindung duplikasi data (`INSERT OR IGNORE` pada SQLite atau `ON CONFLICT DO NOTHING` pada PostgreSQL) berdasarkan keunikan kolom `tweet_id` untuk memastikan tidak ada redundansi data meskipun kueri penarikan dijalankan berulang kali.

---

## 4. Struktur Skema Basis Data (*Data Schema*)
Tabel `raw_tweets` dioptimalkan untuk menyimpan data mentah sebagai landasan jejak audit (*audit trail*) analitik yang tepercaya:

| Nama Kolom | Tipe Data | Keterangan / Aturan Validasi (*Constraint*) |
| :--- | :--- | :--- |
| `tweet_id` | `TEXT` | **PRIMARY KEY**. Menjamin keunikan data cuitan tunggal secara global. |
| `date` | `TEXT` | Tanggal pembuatan cuitan dengan standarisasi format ISO 8601 (`YYYY-MM-DDTHH:MM:SSZ`). |
| `raw_text` | `TEXT` | Teks asli cuitan dari platform Twitter tanpa proses pembersihan apa pun. |
| `username` | `TEXT` | Nama pengguna/akun Twitter yang menerbitkan cuitan tersebut. |
| `likes` | `INTEGER` | Jumlah suka (*likes*) yang diperoleh cuitan (indikasi tingkat keterlibatan audiens). |
| `retweets` | `INTEGER` | Jumlah bagikan (*retweets*) (indikasi vitalitas penyebaran pesan). |
| `status` | `TEXT` | Nilai bawaan adalah `'RAW'`. Akan diubah menjadi `'CLEANED'` oleh modul AI pascapemrosesan. |

---

## 5. Manajemen Kesalahan & Mitigasi Risiko
* **Kegagalan Autentikasi:** Sistem akan membatalkan proses penarikan data dan melemparkan pengecualian kritis (*Exception*) jika token API Apify tidak valid atau kedaluwarsa sebelum kueri terkirim ke server cloud, guna menghindari konsumsi kuota yang sia-sia.
* **Pembatasan Anggaran & Biaya:** Parameter `max_tweets` diterapkan pada level konfigurasi lokal untuk membatasi konsumsi Unit Compute (CU) platform Apify agar biaya operasional tetap terkontrol dan terprediksi.
* **Timeout Actor:** Meskipun pemanggilan secara sinkron (*blocking*) sangat memadai untuk fase MVP, untuk penarikan data skala besar (>10.000 data) disarankan memodifikasi pemanggilan secara asinkron (`start()`) yang memanfaatkan fitur *Webhook* untuk mengirimkan notifikasi saat data selesai diproses.
