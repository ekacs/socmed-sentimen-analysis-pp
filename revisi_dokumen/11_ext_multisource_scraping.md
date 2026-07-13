# Ekstensi Multi-Sumber Ingestion (Instagram, LinkedIn, & Portal Berita)
**Proyek:** Analisis Sentimen Kebijakan Publik Berbasis Kecerdasan Buatan (AI)

---

## 1. Tinjauan Arsitektur Multi-Sumber
Untuk memperluas cakupan analisis dari yang awalnya hanya berfokus pada Twitter (X) menjadi ekosistem multi-platform, kita perlu melakukan adaptasi pada **sisi Ingestion**. Beruntung, dengan menggunakan **Apify**, kita tidak perlu membangun scraper manual untuk masing-masing situs dari nol. Kita cukup memetakan kueri ke **Actor Apify** yang berspesialisasi pada masing-masing platform tersebut.

Berikut adalah pemetaan Actor Apify yang direkomendasikan untuk stabilitas jangka panjang:

| Sumber Data | Rekomendasi Actor Apify | Jenis Data Luaran |
| :--- | :--- | :--- |
| **Instagram** | `apify/instagram-scraper` atau `apidojo/instagram-scraper` | Profil, Caption Post, Komentar Postingan |
| **LinkedIn** | `curious_coder/linkedin-profile-scraper` atau `bebity/linkedin-post-comments-scraper` | Profil, Konten Post, Komentar Profesional |
| **Portal Berita** | `apify/website-content-crawler` atau `apify/cheerio-scraper` | Judul Artikel, Isi Berita, Tanggal Publikasi, Penulis |

---

## 2. Pembaruan Struktur Konfigurasi (`target_config.json`)
Agar sistem dapat mengenali target platform mana yang ingin ditarik secara dinamis tanpa mengubah kode inti, kita perlu mendesain ulang skema berkas konfigurasi dengan parameter `source_type`:

```json
{
  "source_type": "instagram_posts", 
  "config": {
    "instagram": {
      "usernames": ["kemenpupr", "kemendagri"],
      "max_posts_per_profile": 10,
      "scrape_comments": true,
      "max_comments_per_post": 25
    },
    "linkedin": {
      "urls": ["https://www.linkedin.com/company/kementerian-perhubungan-ri"],
      "max_posts": 15,
      "scrape_comments": true
    },
    "news_portal": {
      "domains": [
        "kompas.com",
        "kompasiana.com",
        "cnnindonesia.com",
        "katadata.co.id",
        "databoks.katadata.co.id"
      ],
      "search_keywords": ["krl commuter line", "transjakarta", "ikn nusantara"],
      "max_articles_per_domain": 20
    }
  }
}
```

---

## 3. Implementasi Kode Modular Scraper (`01_run_scraper.py`)
Berikut adalah implementasi kode Python modular yang mampu mendeteksi `source_type` dari berkas konfigurasi dan secara dinamis memicu Actor Apify yang sesuai, serta menstandardisasi hasilnya untuk disimpan ke dalam database.

```python
import os
import json
import sqlite3
from google import genai
from apify_client import ApifyClient
from dotenv import load_dotenv

# Memuat berkas .env
load_dotenv()

# Inisialisasi Klien
apify_client = ApifyClient(os.getenv("APIFY_API_TOKEN"))
DB_FILE = 'sentimen_kebijakan.db'

def load_config(config_path='target_config.json'):
    with open(config_path, 'r') as file:
        return json.load(file)

def save_to_db(data_standardized):
    """
    Menyimpan hasil ekstraksi dari platform mana pun ke skema tabel tunggal
    dengan pendekatan UPSERT (INSERT OR IGNORE) untuk menjaga integritas data.
    """
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Memastikan tabel siap menerima data dengan kolom 'source_platform'
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS log_cuitan (
            tweet_id TEXT PRIMARY KEY,          -- Bertindak sebagai ID Unik Konten secara global
            date TEXT NOT NULL,
            username TEXT NOT NULL,
            raw_text TEXT NOT NULL,
            cleaned_text TEXT,
            sentiment_label TEXT,
            confidence_score REAL DEFAULT 0.0,
            likes INTEGER DEFAULT 0,
            retweets INTEGER DEFAULT 0,         -- Diisi 0 jika platform tidak memilikinya
            status TEXT DEFAULT 'RAW',
            source_platform TEXT NOT NULL       -- Keterangan sumber: 'Twitter', 'Instagram', 'LinkedIn', 'News'
        )
    ''')
    
    query = '''
        INSERT OR IGNORE INTO log_cuitan (
            tweet_id, date, username, raw_text, likes, retweets, status, source_platform
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    '''
    
    data_tuple = [
        (
            d['id'], 
            d['date'], 
            d['username'], 
            d['raw_text'], 
            d.get('likes', 0), 
            d.get('retweets', 0), 
            'RAW', 
            d['source_platform']
        )
        for d in data_standardized
    ]
    
    cursor.executemany(query, data_tuple)
    conn.commit()
    conn.close()
    print(f"✅ Berhasil menyelaraskan {len(data_standardized)} baris data baru ke database!")

# ==========================================
# SUB-MODUL SCRAPER BERDASARKAN PLATFORM
# ==========================================

def scrape_instagram(config):
    """Menggunakan apify/instagram-scraper untuk mengambil postingan/komentar"""
    print("🚀 Memulai penarikan data dari Instagram...")
    insta_cfg = config['config']['instagram']
    
    run_input = {
        "directUrls": [f"https://www.instagram.com/{user}/" for user in insta_cfg['usernames']],
        "resultsType": "posts",
        "resultsLimit": insta_cfg['max_posts_per_profile'],
        "addParentData": True
    }
    
    run = apify_client.actor("apify/instagram-scraper").call(run_input=run_input)
    results = []
    
    for item in apify_client.dataset(run["defaultDatasetId"]).iterate_items():
        # Menstandardisasi format Instagram agar cocok dengan skema tabel database
        results.append({
            "id": f"IG_POST_{item.get('id')}",
            "date": item.get("timestamp", ""),
            "username": f"@{item.get('ownerUsername', 'unknown')}",
            "raw_text": item.get("caption", "No Caption"),
            "likes": item.get("likesCount", 0),
            "retweets": 0, # Instagram tidak memiliki fitur retweet asli
            "source_platform": "Instagram"
        })
        
        # Jika dikonfigurasi untuk menarik komentar
        if insta_cfg['scrape_comments'] and item.get('latestComments'):
            for comment in item['latestComments'][:insta_cfg['max_comments_per_post']]:
                results.append({
                    "id": f"IG_COMM_{comment.get('id')}",
                    "date": comment.get("createdAt", item.get("timestamp")),
                    "username": f"@{comment.get('owner', {}).get('username', 'unknown')}",
                    "raw_text": comment.get("text", ""),
                    "likes": 0,
                    "retweets": 0,
                    "source_platform": "Instagram_Comment"
                })
                
    return results

def scrape_linkedin(config):
    """Menggunakan LinkedIn Post Scraper untuk menarik data feed korporasi"""
    print("🚀 Memulai penarikan data dari LinkedIn...")
    li_cfg = config['config']['linkedin']
    
    run_input = {
        "urls": li_cfg['urls'],
        "limit": li_cfg['max_posts']
    }
    
    run = apify_client.actor("bebity/linkedin-post-comments-scraper").call(run_input=run_input)
    results = []
    
    for item in apify_client.dataset(run["defaultDatasetId"]).iterate_items():
        results.append({
            "id": f"LI_POST_{item.get('urn')}",
            "date": item.get("postedAt", ""),
            "username": item.get("authorName", "LinkedIn User"),
            "raw_text": item.get("text", "No Content"),
            "likes": item.get("numLikes", 0),
            "retweets": item.get("numShares", 0),
            "source_platform": "LinkedIn"
        })
    return results

def scrape_news_portal(config):
    """
    Menggunakan Cheerio Scraper atau Website Content Crawler untuk merayapi 
    situs berita Indonesia (Kompas, CNN, Katadata, dsb) secara selektif.
    """
    print("🚀 Memulai penarikan data dari Portal Berita...")
    news_cfg = config['config']['news_portal']
    
    # Contoh penyusunan target URL pencarian pada masing-masing portal berita
    start_urls = []
    for keyword in news_cfg['search_keywords']:
        k_encoded = keyword.replace(" ", "%20")
        for domain in news_cfg['domains']:
            if "kompas.com" in domain:
                start_urls.append({"url": f"https://search.kompas.com/search/?q={k_encoded}"})
            elif "cnnindonesia.com" in domain:
                start_urls.append({"url": f"https://www.cnnindonesia.com/search/?query={k_encoded}"})
            elif "katadata.co.id" in domain:
                start_urls.append({"url": f"https://katadata.co.id/search?q={k_encoded}"})
                
    # Menjalankan Cheerio Scraper untuk mengekstrak struktur tag artikel berita
    run_input = {
        "startUrls": start_urls,
        "maxPagesPerCrawl": news_cfg['max_articles_per_domain'],
        # JQuery selector kustom untuk mengekstrak judul dan paragraf berita utama
        "pageFunction": """
        async function pageFunction(context) {
            const { $, request } = context;
            const title = $('h1').text().trim();
            const body = $('article p, .post__content p, .detail-text p').text().trim();
            const date = $('.read__time, .date, .detail__date').text().trim();
            
            return {
                url: request.url,
                title: title,
                content: body.slice(0, 1000), // Batasi panjang teks berita
                date: date || new Date().toISOString()
            };
        }
        """
    }
    
    run = apify_client.actor("apify/cheerio-scraper").call(run_input=run_input)
    results = []
    
    for item in apify_client.dataset(run["defaultDatasetId"]).iterate_items():
        if item.get("title") and item.get("content"):
            results.append({
                "id": f"NEWS_{hash(item['url'])}",
                "date": item.get("date"),
                "username": item["url"].split("/")[2], # Mendapatkan nama domain sebagai username
                "raw_text": f"JUDUL: {item['title']} | ISI: {item['content']}",
                "likes": 0,
                "retweets": 0,
                "source_platform": "News_Portal"
            })
    return results

# ==========================================
# ORKESTRATOR UTAMA
# ==========================================

def main():
    config = load_config()
    source_type = config.get("source_type")
    
    data_extracted = []
    
    if source_type == "instagram_posts":
        data_extracted = scrape_instagram(config)
    elif source_type == "linkedin_posts":
        data_extracted = scrape_linkedin(config)
    elif source_type == "news_portal":
        data_extracted = scrape_news_portal(config)
    else:
        print(f"⚠️ Tipe sumber '{source_type}' tidak dikenal atau tidak didukung.")
        return
        
    if data_extracted:
        save_to_db(data_extracted)
    else:
        print("📭 Tidak ada data baru yang berhasil ditarik.")

if __name__ == "__main__":
    main()
```

---

## 4. Keuntungan Arsitektur Multi-Sumber Ini
1. **Satu Skema Tabel untuk Semua Platform (`One Schema to Rule Them All`):** Teks postingan LinkedIn, caption Instagram, isi berita Kompas/CNN, serta komentar pengguna diseragamkan ke dalam kolom `raw_text` dengan pemetaan pelabelan asal kolom `source_platform`. Ini mempermudah visualisasi analitik komparatif di Streamlit.
2. **Fleksibel & Dinamis:** Pengguna dapat mengganti fokus scraping (misalnya dari Instagram ke portal berita) hanya dengan mengubah berkas JSON konfigurasi tanpa menyentuh kode program.
3. **Pemberdayaan Penuh Kemampuan Prapemrosesan AI (Gemini):** Karena semua sumber data telah disatukan di database dengan status `'RAW'`, pipeline pembersihan teks berbasis model Gemini (`01_pipeline_data.py`) dapat menyaring dan menstandardisasi seluruh teks tersebut secara bersamaan tanpa membeda-bedakan platform asalnya.
