import os
import sys
import json
import hashlib
from datetime import datetime
from dotenv import load_dotenv
from apify_client import ApifyClient

# Impor fungsi pembaca konfigurasi
from config_parser import load_config, build_twitter_query
# Impor fungsi basis data
from db_manager import simpan_data_ke_db, buat_tabel, get_scraping_mode

# Memuat file .env — override=False agar env var sistem (GitHub Actions) tidak tertimpa
load_dotenv(override=False)

def get_apify_client():
    """
    Menginisialisasi klien Apify secara aman dengan memvalidasi token API.
    """
    token = os.getenv("APIFY_API_TOKEN")
    if not token or token == "YOUR_APIFY_API_TOKEN_HERE":
        print("[ERROR] Token API Apify ('APIFY_API_TOKEN') tidak dikonfigurasi di file .env.")
        print("[ERROR] Silakan edit file .env dan masukkan token API Apify Anda yang valid.")
        return None
    return ApifyClient(token)

def scrape_twitter(client, general_cfg):
    """
    Menggunakan aktor 'apidojo/tweet-scraper' untuk menarik cuitan dari Twitter (X).
    """
    print("[INFO] Memulai penarikan data dari Twitter (X)...")
    
    # Rangkai kueri pencarian tingkat lanjut
    query_string = build_twitter_query({"config": {"general": general_cfg}})
    max_tweets = general_cfg.get("max_results", 100)
    
    print(f"[INFO] Menggunakan kueri Twitter: '{query_string}'")
    print(f"[INFO] Batas maksimal data: {max_tweets}")
    
    run_input = {
        "searchTerms": [query_string],
        "maxTweets": max_tweets
    }
    
    try:
        run = client.actor("apidojo/tweet-scraper").call(run_input=run_input)
        dataset_id = run["defaultDatasetId"]
        
        results = []
        for item in client.dataset(dataset_id).iterate_items():
            # Ekstraksi tweet_id
            tweet_id = item.get("id") or item.get("id_str")
            if not tweet_id:
                continue
                
            # Pemetaan tanggal
            raw_date = item.get("createdAt") or item.get("created_at") or item.get("date")
            if raw_date:
                # Upayakan standarisasi ke format ISO 8601
                try:
                    # Contoh format Twitter: "Mon Jul 13 06:45:00 +0000 2026" atau ISO string
                    # Jika berupa angka timestamp (ms)
                    if isinstance(raw_date, (int, float)):
                        date_str = datetime.fromtimestamp(raw_date / 1000.0).isoformat() + "Z"
                    else:
                        date_str = str(raw_date)
                except Exception:
                    date_str = str(raw_date)
            else:
                date_str = datetime.utcnow().isoformat() + "Z"
                
            # Pemetaan profil
            user_info = item.get("twitterUser") or item.get("user") or {}
            username = user_info.get("username") or user_info.get("screen_name") or item.get("username") or "unknown"
            if not username.startswith("@"):
                username = f"@{username}"
                
            raw_text = item.get("fullText") or item.get("text") or ""
            likes = item.get("likeCount") or item.get("favoriteCount") or item.get("likes") or 0
            retweets = item.get("retweetCount") or item.get("retweet_count") or item.get("retweets") or 0
            
            results.append({
                "tweet_id": str(tweet_id),
                "date": date_str,
                "username": username,
                "raw_text": raw_text,
                "likes": int(likes),
                "retweets": int(retweets),
                "source_platform": "Twitter"
            })
            
        return results
        
    except Exception as e:
        print(f"[ERROR] Kesalahan saat memanggil Aktor Twitter Apify: {e}")
        return []

def scrape_instagram(client, general_cfg):
    """
    Menggunakan aktor 'apify/instagram-scraper' untuk menarik postingan/komentar Instagram.
    """
    print("[INFO] Memulai penarikan data dari Instagram...")
    profiles = general_cfg.get("profiles", [])
    max_results = general_cfg.get("max_results", 10)
    
    if not profiles:
        print("[WARNING] Profil target tidak ditemukan di konfigurasi. Proses Instagram dibatalkan.")
        return []
        
    run_input = {
        "directUrls": [f"https://www.instagram.com/{p.strip()}/" for p in profiles],
        "resultsType": "posts",
        "resultsLimit": max_results,
        "addParentData": True
    }
    
    try:
        run = client.actor("apify/instagram-scraper").call(run_input=run_input)
        dataset_id = run["defaultDatasetId"]
        
        results = []
        for item in client.dataset(dataset_id).iterate_items():
            post_id = item.get("id")
            if not post_id:
                continue
                
            raw_date = item.get("timestamp") or item.get("datetime")
            username = item.get("ownerUsername") or "unknown"
            if not username.startswith("@"):
                username = f"@{username}"
                
            results.append({
                "tweet_id": f"IG_POST_{post_id}",
                "date": str(raw_date) if raw_date else datetime.utcnow().isoformat() + "Z",
                "username": username,
                "raw_text": item.get("caption") or "No Caption",
                "likes": int(item.get("likesCount", 0) or 0),
                "retweets": 0,
                "source_platform": "Instagram"
            })
            
            # Tarik komentar terbaru jika ada
            latest_comments = item.get("latestComments", [])
            for comment in latest_comments:
                comm_id = comment.get("id")
                if not comm_id:
                    continue
                comm_user = comment.get("owner", {}).get("username") or "unknown"
                if not comm_user.startswith("@"):
                    comm_user = f"@{comm_user}"
                results.append({
                    "tweet_id": f"IG_COMM_{comm_id}",
                    "date": comment.get("createdAt") or str(raw_date),
                    "username": comm_user,
                    "raw_text": comment.get("text") or "",
                    "likes": 0,
                    "retweets": 0,
                    "source_platform": "Instagram"
                })
                
        return results
    except Exception as e:
        print(f"[ERROR] Kesalahan saat memanggil Aktor Instagram Apify: {e}")
        return []

def scrape_linkedin(client, general_cfg):
    """
    Menggunakan aktor LinkedIn Scraper untuk mengambil data postingan korporasi.
    """
    print("[INFO] Memulai penarikan data dari LinkedIn...")
    profiles = general_cfg.get("profiles", [])
    max_results = general_cfg.get("max_results", 10)
    
    if not profiles:
        print("[WARNING] Profil target tidak ditemukan di konfigurasi. Proses LinkedIn dibatalkan.")
        return []
        
    # Susun URL profil LinkedIn
    urls = []
    for p in profiles:
        p = p.strip()
        if p.startswith("http"):
            urls.append(p)
        else:
            urls.append(f"https://www.linkedin.com/company/{p}")
            
    run_input = {
        "urls": urls,
        "limit": max_results
    }
    
    try:
        # Menggunakan bebity/linkedin-post-comments-scraper atau aktor sejenis
        run = client.actor("bebity/linkedin-post-comments-scraper").call(run_input=run_input)
        dataset_id = run["defaultDatasetId"]
        
        results = []
        for item in client.dataset(dataset_id).iterate_items():
            urn = item.get("urn") or item.get("id")
            if not urn:
                continue
                
            results.append({
                "tweet_id": f"LI_POST_{urn}",
                "date": item.get("postedAt") or datetime.utcnow().isoformat() + "Z",
                "username": item.get("authorName") or "LinkedIn User",
                "raw_text": item.get("text") or "No Content",
                "likes": int(item.get("numLikes", 0) or 0),
                "retweets": int(item.get("numShares", 0) or 0),
                "source_platform": "LinkedIn"
            })
            
        return results
    except Exception as e:
        print(f"[ERROR] Kesalahan saat memanggil Aktor LinkedIn Apify: {e}")
        return []

def scrape_news_portal(client, general_cfg):
    """
    Menggunakan cheerio-scraper untuk menarik konten berita berdasarkan kata kunci.
    """
    print("[INFO] Memulai penarikan data dari Portal Berita...")
    keywords = general_cfg.get("keywords", [])
    max_results = general_cfg.get("max_results", 10)
    
    if not keywords:
        print("[WARNING] Kata kunci tidak ditemukan di konfigurasi. Proses Portal Berita dibatalkan.")
        return []
        
    # Daftar domain portal berita Indonesia
    domains = ["kompas.com", "cnnindonesia.com", "katadata.co.id"]
    start_urls = []
    
    for kw in keywords:
        k_encoded = kw.replace(" ", "%20")
        for domain in domains:
            if "kompas.com" in domain:
                start_urls.append({"url": f"https://search.kompas.com/search/?q={k_encoded}"})
            elif "cnnindonesia.com" in domain:
                start_urls.append({"url": f"https://www.cnnindonesia.com/search/?query={k_encoded}"})
            elif "katadata.co.id" in domain:
                start_urls.append({"url": f"https://katadata.co.id/search?q={k_encoded}"})
                
    run_input = {
        "startUrls": start_urls,
        "maxPagesPerCrawl": max_results,
        "pageFunction": """
        async function pageFunction(context) {
            const { $, request } = context;
            const title = $('h1').text().trim();
            const body = $('article p, .post__content p, .detail-text p').text().trim();
            const date = $('.read__time, .date, .detail__date').text().trim();
            
            return {
                url: request.url,
                title: title,
                content: body.slice(0, 1000),
                date: date || new Date().toISOString()
            };
        }
        """
    }
    
    try:
        run = client.actor("apify/cheerio-scraper").call(run_input=run_input)
        dataset_id = run["defaultDatasetId"]
        
        results = []
        for item in client.dataset(dataset_id).iterate_items():
            url = item.get("url")
            if not url or not item.get("title") or not item.get("content"):
                continue
                
            # Buat hash unik dari URL untuk tweet_id
            url_hash = hashlib.md5(url.encode('utf-8')).hexdigest()
            domain_name = url.split("/")[2] if len(url.split("/")) > 2 else "News Portal"
            
            results.append({
                "tweet_id": f"NEWS_{url_hash}",
                "date": item.get("date") or datetime.utcnow().isoformat() + "Z",
                "username": domain_name,
                "raw_text": f"JUDUL: {item['title']} | ISI: {item['content']}",
                "likes": 0,
                "retweets": 0,
                "source_platform": "News"
            })
            
        return results
    except Exception as e:
        print(f"[ERROR] Kesalahan saat memanggil Aktor Portal Berita Apify: {e}")
        return []

def main():
    # 1. Pastikan tabel database siap
    buat_tabel()
    
    # 1b. Cek Mode Scraping (Manual vs Otomatis)
    mode = get_scraping_mode()
    if mode == 'manual':
        print("[INFO] Mode penarikan data saat ini diatur ke MANUAL. Cronjob otomatis dilewati.")
        sys.exit(0)
    
    # 2. Muat konfigurasi
    config = load_config()
    if not config:
        print("[ERROR] Konfigurasi kosong atau gagal dimuat. Proses dihentikan.")
        sys.exit(1)
        
    # Ambil daftar sumber (dukung format baru source_types array & format lama source_type string)
    raw_sources = config.get("source_types")
    if not raw_sources:
        single = config.get("source_type", "")
        raw_sources = [single] if single else []
    if isinstance(raw_sources, str):
        raw_sources = [raw_sources]
    
    source_types = [str(s).strip().lower() for s in raw_sources if s and str(s).strip()]
    if not source_types:
        print("[ERROR] Tidak ada platform sasaran yang diaktifkan di konfigurasi.")
        print("[ERROR] Silakan buka dasbor Streamlit > tab Pengaturan Target > pilih minimal 1 platform.")
        sys.exit(1)
    
    general_cfg = config.get("config", {}).get("general", {})
    
    # 3. Muat Apify Client
    client = get_apify_client()
    if not client:
        sys.exit(1)
        
    # 4. Iterasi scraping untuk SETIAP platform yang dipilih (multi-platform sekaligus)
    all_results = []
    for source_type in source_types:
        print(f"\n{'='*60}")
        print(f"[INFO] >>> Memulai proses scraping untuk platform: {source_type}")
        print(f"{'='*60}")
        
        if source_type.startswith("twitter"):
            partial = scrape_twitter(client, general_cfg)
        elif source_type == "instagram":
            partial = scrape_instagram(client, general_cfg)
        elif source_type == "linkedin":
            partial = scrape_linkedin(client, general_cfg)
        elif source_type in ["portal_berita", "news_portal", "news"]:
            partial = scrape_news_portal(client, general_cfg)
        else:
            print(f"[WARNING] Tipe sumber '{source_type}' tidak dikenal. Dilewati.")
            continue
        
        print(f"[INFO] Platform '{source_type}' menghasilkan {len(partial)} baris data.")
        all_results.extend(partial)
        
    # 5. Simpan ke database jika ada hasil gabungan
    print(f"\n{'='*60}")
    if all_results:
        print(f"[INFO] Total gabungan {len(all_results)} baris data dari {len(source_types)} platform. Menyimpan ke database...")
        simpan_data_ke_db(all_results)
        print("[SUCCESS] Penarikan data multi-platform selesai dengan sukses!")
    else:
        print("[INFO] Tidak ada data baru yang berhasil ditarik dari seluruh platform atau terjadi kesalahan.")
    print(f"{'='*60}")

if __name__ == "__main__":
    main()
