import os
import sys
import json
import hashlib
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
from apify_client import ApifyClient

WIB_TZ = timezone(timedelta(hours=7))

def parse_to_wib_iso(raw_date=None) -> str:
    """
    Mengonversi tanggal mentah (ISO UTC, Unix timestamp, string) menjadi string ISO berzona waktu WIB (UTC+7).
    Contoh: '2026-07-29T22:40:45+07:00'
    """
    now_wib = datetime.now(WIB_TZ)
    if raw_date is None or raw_date == "":
        return now_wib.isoformat()
    
    try:
        if isinstance(raw_date, (int, float)):
            dt = datetime.fromtimestamp(raw_date if raw_date < 1e11 else raw_date / 1000.0, tz=timezone.utc)
            return dt.astimezone(WIB_TZ).isoformat()
        
        raw_str = str(raw_date).strip()
        if not raw_str:
            return now_wib.isoformat()

        clean_str = raw_str.replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(clean_str)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(WIB_TZ).isoformat()
        except ValueError:
            pass

        return raw_str
    except Exception:
        return str(raw_date)

# Mapping nama bulan Indonesia untuk format log_activity
_BULAN_ID = {
    1: 'Januari', 2: 'Februari', 3: 'Maret', 4: 'April',
    5: 'Mei', 6: 'Juni', 7: 'Juli', 8: 'Agustus',
    9: 'September', 10: 'Oktober', 11: 'November', 12: 'Desember'
}

def format_log_activity(dt: datetime = None) -> str:
    """
    Menghasilkan string timestamp WIB (UTC+7) format DD-MMMM-YYYY HH:MM:SS dengan nama bulan Indonesia.
    Contoh: '29-Juli-2026 22:48:25'
    """
    if dt is None:
        dt = datetime.now(WIB_TZ)
    elif dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc).astimezone(WIB_TZ)
    else:
        dt = dt.astimezone(WIB_TZ)
    return f"{dt.day:02d}-{_BULAN_ID[dt.month]}-{dt.year} {dt.hour:02d}:{dt.minute:02d}:{dt.second:02d}"

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

def scrape_twitter(client, general_cfg, log_activity: str = "", user_app: str = "local_user"):
    """
    Menggunakan aktor Twitter scraper (ID: ghSpYIW3L1RvT57NT)
    untuk menarik cuitan dari Twitter (X).
    """
    print("[INFO] Memulai penarikan data dari Twitter (X)...")
    
    # Rangkai kueri pencarian tingkat lanjut
    query_string = build_twitter_query({"config": {"general": general_cfg}})
    # Prioritas: field spesifik twitter > general max_results > default 500
    max_tweets = general_cfg.get("max_results_twitter")
    if max_tweets is None:
        max_tweets = general_cfg.get("max_results", 500)
    max_tweets = int(max_tweets)
    
    print(f"[INFO] Menggunakan kueri Twitter: '{query_string}'")
    print(f"[INFO] Batas maksimal cuitan Twitter (X): {max_tweets}")
    print(f"[INFO] Sortir: Top | Aktor: ghSpYIW3L1RvT57NT")
    
    # --- Ekstrak Twitter Handles & Start URLs dari profiles field jika ada ---
    raw_profiles = general_cfg.get("profiles", []) or []
    twitter_handles = []
    twitter_start_urls = []
    for p in raw_profiles:
        p = str(p).strip()
        if not p:
            continue
        if p.startswith("http"):
            twitter_start_urls.append(p)
        else:
            clean_handle = p.lstrip("@")
            twitter_handles.append(clean_handle)
            twitter_start_urls.append(f"https://twitter.com/{clean_handle}")
            
    search_terms = [query_string] if query_string else []
    
    if not search_terms and not twitter_handles and not twitter_start_urls:
        print("[WARNING] Tidak ada kueri pencarian, handle, atau URL Twitter yang valid. Proses Twitter dibatalkan.")

        return []
        
    # --- Bangun run_input sesuai mode ---
    # PENTING: Actor ghSpYIW3L1RvT57NT tidak bisa menggabungkan searchTerms + startUrls/twitterHandles
    # secara bersamaan tanpa konflik. Prioritas: jika ada search query → gunakan mode SEARCH only.
    # Jika tidak ada search query → gunakan mode PROFILE (twitterHandles + startUrls).
    if search_terms:
        # Mode SEARCH: Aktor ghSpYIW3L1RvT57NT menggunakan field 'query' (string), 'search_type' ("Top"), dan 'max_posts' (int)
        run_input = {
            "query": query_string,
            "search_type": "Top",
            "searchType": "Top",
            "max_posts": int(max_tweets),
            # Key kompatibilitas fallback jika versi aktor berubah
            "searchTerms": search_terms,
            "sort": "Top",
            "searchMode": "top",
            "maxItems": int(max_tweets),
            "tweetsPerQuery": int(max_tweets)
        }
        print(f"[INFO] Mode: SEARCH | query: '{query_string}' | search_type: Top | max_posts: {max_tweets}")
    else:
        # Mode PROFILE: tidak ada search query, scrape langsung dari username / profil
        first_handle = twitter_handles[0] if twitter_handles else ""
        formatted_start_urls = [{"url": u} if isinstance(u, str) else u for u in twitter_start_urls]
        run_input = {
            "username": first_handle,
            "query": f"from:{first_handle}" if first_handle else "",
            "search_type": "Top",
            "searchType": "Top",
            "max_posts": int(max_tweets),
            # Key kompatibilitas fallback
            "twitterHandles": twitter_handles,
            "startUrls": formatted_start_urls,
            "sort": "Top",
            "maxItems": int(max_tweets)
        }
        print(f"[INFO] Mode: PROFILE | username: '{first_handle}' | max_posts: {max_tweets}")
    
    try:
        run = client.actor("ghSpYIW3L1RvT57NT").call(run_input=run_input)
        dataset_id = run["defaultDatasetId"]
        
        results = []
        for item in client.dataset(dataset_id).iterate_items():
            author = item.get("author") if isinstance(item.get("author"), dict) else {}
            user_info = item.get("user_info") if isinstance(item.get("user_info"), dict) else {}
            
            # 1. platform_id: diambil dari field 'tweet_id' item (ID asli tweet dari platform)
            platform_id = (
                item.get("tweet_id")
                or item.get("id")
                or item.get("id_str")
                or item.get("url")
            )
            if not platform_id:
                continue
            platform_id = str(platform_id)
                
            # 2. date: diambil dari field 'created_at' (diubah ke WIB UTC+7)
            raw_date = item.get("created_at") or item.get("createdAt") or item.get("date")
            date_str = parse_to_wib_iso(raw_date)
                
            # 3. username: diambil dari field 'user_info/screen_name' (sesuai spesifikasi)
            username = (
                user_info.get("screen_name")
                or author.get("userName")
                or author.get("username")
                or item.get("username")
                or "unknown"
            )
            if not username.startswith("@"):
                username = f"@{username}"
                
            # 4. raw_text: diambil dari field 'text' (sesuai spesifikasi)
            raw_text = item.get("text") or item.get("fullText") or item.get("full_text") or ""
            
            # 5. likes: diambil dari field 'likes' langsung (sesuai spesifikasi)
            likes = (
                item.get("likes")
                if item.get("likes") is not None
                else (item.get("likeCount") or item.get("favorite_count") or 0)
            )
            
            # 6. retweets: diambil dari field 'retweets' langsung (sesuai spesifikasi)
            retweets = (
                item.get("retweets")
                if item.get("retweets") is not None
                else (item.get("retweetCount") or item.get("retweet_count") or 0)
            )
            
            # 7. views: diambil dari field 'views' (tersedia di Twitter/X)
            views = item.get("views") or item.get("viewCount") or 0
            
            results.append({
                "platform_id": platform_id,
                "date": date_str,
                "username": username,
                "raw_text": raw_text,
                "likes": int(likes or 0),
                "retweets": int(retweets or 0),
                "views": int(views or 0),
                "source_platform": "Twitter / X",
                "log_activity": log_activity,
                "user_app": user_app
            })
            
        return results
        
    except Exception as e:
        print(f"[ERROR] Kesalahan saat memanggil Aktor Twitter Apify (ghSpYIW3L1RvT57NT): {e}")
        return []

def scrape_instagram(client, general_cfg, log_activity: str = "", user_app: str = "local_user"):
    """
    Penarikan data Instagram multi-mode / multi-aktor:
    1. Aktor 'apify/instagram-scraper' (reGe1ST3OBgYZSsZJ) untuk Kata Kunci/Hashtag (mode: hashtags / search)
    2. Aktor 'apify/instagram-post-scraper' (nH2AHrwxeTRJoN5hX) untuk Username Profil (mode: username / profiles)
    Jika kedua input terisi, kedua aktor akan dijalankan berurutan (Hashtag terlebih dahulu, lalu Username).
    """
    print("[INFO] Memulai penarikan data dari Instagram...")
    keywords = general_cfg.get("keywords", []) or []
    hashtags = general_cfg.get("hashtags", []) or []
    profiles = general_cfg.get("profiles", []) or []
    
    search_mode = general_cfg.get("search_mode", "hashtags")
    profile_mode = general_cfg.get("profile_mode", "username")
    
    max_results = general_cfg.get("max_results_instagram")
    if max_results is None:
        max_results = general_cfg.get("max_results", 100)
    max_results = int(max_results)

    has_keywords = bool(keywords or hashtags)
    has_profiles = bool(profiles)

    if not has_keywords and not has_profiles:
        print("[WARNING] Tidak ada Kata Kunci/Hashtag maupun Username Instagram yang dikonfigurasi. Penarikan Instagram dibatalkan.")
        return []

    all_results = []

    # -----------------------------------------------------------------
    # AKTOR 1: apify/instagram-hashtag-scraper (reGe1ST3OBgYZSsZJ) -> Hashtag / Search
    # -----------------------------------------------------------------
    if has_keywords:
        print(f"[INFO] >>> Menjalankan Aktor 1: apify/instagram-hashtag-scraper (reGe1ST3OBgYZSsZJ) (keywordSearch=True)...")
        kw_list = keywords if keywords else hashtags
        clean_tags = [str(k).strip().lstrip("#") for k in kw_list if str(k).strip()]
        
        run_input_kw = {
            "hashtags": clean_tags,
            "keywordSearch": True,
            "resultsLimit": max_results,
            "resultsType": "posts"
        }
            
        try:
            print(f"[INFO] Memanggil actor apify/instagram-hashtag-scraper (reGe1ST3OBgYZSsZJ) dengan input: {run_input_kw}")
            # Coba panggil via slug 'apify/instagram-hashtag-scraper', fallback ke ID 'reGe1ST3OBgYZSsZJ'
            try:
                run1 = client.actor("apify/instagram-hashtag-scraper").call(run_input=run_input_kw)
            except Exception:
                run1 = client.actor("reGe1ST3OBgYZSsZJ").call(run_input=run_input_kw)
                
            ds_id1 = run1["defaultDatasetId"]
            
            for item in client.dataset(ds_id1).iterate_items():
                post_id = item.get("id") or item.get("shortCode") or item.get("code")
                if not post_id:
                    continue
                raw_date = item.get("timestamp") or item.get("datetime") or item.get("takenAt")
                username = item.get("ownerUsername") or (item.get("owner", {}) if isinstance(item.get("owner"), dict) else {}).get("username") or "unknown"
                if not username.startswith("@"):
                    username = f"@{username}"
                
                all_results.append({
                    "platform_id": f"IG_HASHTAG_{post_id}",
                    "date": parse_to_wib_iso(raw_date),
                    "username": username,
                    "raw_text": item.get("caption") or item.get("text") or "No Caption",
                    "likes": int(item.get("likesCount", 0) or item.get("likes", 0) or 0),
                    "retweets": 0,
                    "views": 0,
                    "source_platform": "Instagram",
                    "log_activity": log_activity,
                    "user_app": user_app
                })
                
                # Ekstrak komentar terbaru jika ada
                latest_comments = item.get("latestComments", []) or []
                if isinstance(latest_comments, list):
                    for comment in latest_comments:
                        if not isinstance(comment, dict):
                            continue
                        comm_id = comment.get("id")
                        if not comm_id:
                            continue
                        comm_user = (comment.get("owner", {}) if isinstance(comment.get("owner"), dict) else {}).get("username") or "unknown"
                        if not comm_user.startswith("@"):
                            comm_user = f"@{comm_user}"
                        all_results.append({
                            "platform_id": f"IG_COMM_{comm_id}",
                            "date": parse_to_wib_iso(comment.get("createdAt") or comment.get("date") or raw_date),
                            "username": comm_user,
                            "raw_text": comment.get("text") or "",
                            "likes": 0,
                            "retweets": 0,
                            "views": 0,
                            "source_platform": "Instagram",
                            "log_activity": log_activity,
                            "user_app": user_app
                        })
        except Exception as e1:
            print(f"[ERROR] Kesalahan saat memanggil Aktor apify/instagram-scraper: {e1}")

    # -----------------------------------------------------------------
    # AKTOR 2: apify/instagram-post-scraper (nH2AHrwxeTRJoN5hX) -> Username / Profiles
    # -----------------------------------------------------------------
    if has_profiles:
        print(f"[INFO] >>> Menjalankan Aktor 2: apify/instagram-post-scraper (nH2AHrwxeTRJoN5hX) | Mode: {profile_mode}...")
        prof_list = [str(p).strip().lstrip("@") for p in profiles if str(p).strip()]
        
        if profile_mode == "username":
            run_input_prof = {
                "username": prof_list,
                "resultsLimit": max_results
            }
        else:  # "profiles"
            run_input_prof = {
                "profiles": prof_list,
                "directUrls": [f"https://www.instagram.com/{p}/" for p in prof_list],
                "resultsLimit": max_results
            }
            
        try:
            print(f"[INFO] Memanggil actor apify/instagram-post-scraper dengan input: {run_input_prof}")
            run2 = client.actor("apify/instagram-post-scraper").call(run_input=run_input_prof)
            ds_id2 = run2["defaultDatasetId"]
            
            for item in client.dataset(ds_id2).iterate_items():
                post_id = item.get("id") or item.get("shortCode") or item.get("code")
                if not post_id:
                    continue
                raw_date = item.get("timestamp") or item.get("datetime") or item.get("takenAt")
                username = item.get("ownerUsername") or (item.get("owner", {}) if isinstance(item.get("owner"), dict) else {}).get("username") or "unknown"
                if not username.startswith("@"):
                    username = f"@{username}"
                
                all_results.append({
                    "platform_id": f"IG_PROFILE_POST_{post_id}",
                    "date": parse_to_wib_iso(raw_date),
                    "username": username,
                    "raw_text": item.get("caption") or item.get("text") or "No Caption",
                    "likes": int(item.get("likesCount", 0) or item.get("likes", 0) or 0),
                    "retweets": 0,
                    "views": 0,
                    "source_platform": "Instagram",
                    "log_activity": log_activity,
                    "user_app": user_app
                })
        except Exception as e2:
            print(f"[ERROR] Kesalahan saat memanggil Aktor apify/instagram-post-scraper: {e2}")

    return all_results

def scrape_linkedin(client, general_cfg, log_activity: str = "", user_app: str = "local_user"):
    """
    Menggunakan aktor OFFICIAL 'harvestapi/linkedin-profile-posts' untuk mengambil data postingan LinkedIn
    (pribadi / perusahaan / post URLs / activity URN).
    Sesuai spec: catatan_pengerjaan/25 juli 2026/harvestapi_linkedIn_profile_JSON_form.txt
    """
    print("[INFO] Memulai penarikan data dari LinkedIn (Aktor: harvestapi/linkedin-profile-posts)...")
    profiles = general_cfg.get("profiles", [])
    # Prioritas: field spesifik linkedin > general max_results > default 5
    max_results = general_cfg.get("max_results_linkedin")
    if max_results is None:
        max_results = general_cfg.get("max_results", 5)
    max_results = int(max_results)
    
    # maxComments default sedikit (menghemat kredit) karena untuk sentimen yang penting adalah postingan
    max_comments = min(5, max_results) if max_results > 0 else 0
    max_reactions = min(5, max_results) if max_results > 0 else 0
    
    print(f"[INFO] maxPosts: {max_results} | maxComments: {max_comments} | maxReactions: {max_reactions}")
    print(f"[INFO] Jumlah target LinkedIn: {len(profiles)} (estimasi {len(profiles) * max_results} posts)")
    
    if not profiles:
        print("[WARNING] Profil target tidak ditemukan di konfigurasi. Proses LinkedIn dibatalkan.")
        return []
        
    # Susun targetUrls (bisa company page, profile, post URL, atau activity URN)
    target_urls = []
    for p in profiles:
        p = str(p).strip()
        if not p:
            continue
        if p.startswith("http"):
            # Sudah berupa URL penuh (post/activity/company/profile)
            target_urls.append(p)
        elif p.startswith("urn:li:"):
            # Sudah berupa URN activity, wrap ke URL feed/update agar diterima actor
            target_urls.append(f"https://www.linkedin.com/feed/update/{p}/")
        else:
            # Default: dianggap nama company (paling umum untuk kebijakan publik)
            target_urls.append(f"https://www.linkedin.com/company/{p}")
            
    run_input = {
        "targetUrls": target_urls,
        "maxPosts": int(max_results),
        "includeQuotePosts": True,
        "includeReposts": True,
        "maxComments": int(max_comments),
        "maxReactions": int(max_reactions),
        "postNestedComments": False,
        "postNestedReactions": False,
        "scrapeComments": bool(max_comments > 0),
        "scrapeReactions": bool(max_reactions > 0)
    }
    
    try:
        run = client.actor("harvestapi/linkedin-profile-posts").call(run_input=run_input)
        dataset_id = run["defaultDatasetId"]
        
        results = []
        for item in client.dataset(dataset_id).iterate_items():
            # Struktur dataset harvestapi/linkedin-profile-posts:
            # id, urn, url, author, content (text/html), postedAt, reactions.total, repostCount, comments.total, comments.items[]
            
            post_id = (
                item.get("id")
                or item.get("urn")
                or item.get("postId")
                or item.get("activityId")
            )
            if not post_id:
                post_id = hashlib.md5(json.dumps(item, default=str).encode()).hexdigest()
            
            # --- Tanggal (WIB UTC+7) ---
            posted_at = (
                item.get("postedAt")
                or item.get("publishedAt")
                or item.get("timestamp")
                or item.get("date")
            )
            date_str = parse_to_wib_iso(posted_at)
            
            # --- Author ---
            author_obj = item.get("author") if isinstance(item.get("author"), dict) else {}
            username = (
                author_obj.get("name")
                or author_obj.get("fullName")
                or author_obj.get("companyName")
                or author_obj.get("title")
                or item.get("authorName")
                or item.get("author") if isinstance(item.get("author"), str) else None
                or "LinkedIn User"
            )
            if isinstance(username, str):
                username = username.strip() or "LinkedIn User"
            else:
                username = "LinkedIn User"
            
            # --- Konten Teks ---
            content_obj = item.get("content") if isinstance(item.get("content"), dict) else None
            if content_obj:
                raw_text = (
                    content_obj.get("text")
                    or content_obj.get("markdown")
                    or content_obj.get("html")
                    or ""
                )
            else:
                raw_text = (
                    item.get("text")
                    or item.get("body")
                    or item.get("description")
                    or item.get("message")
                    or "No Content"
                )
            if raw_text is None:
                raw_text = "No Content"
            
            # --- Engagement ---
            reactions_obj = item.get("reactions") if isinstance(item.get("reactions"), dict) else {}
            likes = reactions_obj.get("total") or reactions_obj.get("count") or item.get("numLikes") or item.get("likesCount") or 0
            retweets = (
                item.get("repostCount")
                or item.get("numShares")
                or item.get("shareCount")
                or 0
            )
            
            results.append({
                "platform_id": f"LI_POST_{str(post_id)}",
                "date": date_str,
                "username": str(username),
                "raw_text": str(raw_text),
                "likes": int(likes or 0),
                "retweets": int(retweets or 0),
                "views": 0,
                "source_platform": "LinkedIn",
                "log_activity": log_activity,
                "user_app": user_app
            })
            
            # --- Opsional: tarik KOMENTAR (postNestedComments=False → cuma komentar level 1) ---
            comments_obj = item.get("comments") if isinstance(item.get("comments"), dict) else {}
            comment_items = comments_obj.get("items") or comments_obj.get("data") or []
            if isinstance(comment_items, list):
                for c in comment_items[:max_comments]:
                    if not isinstance(c, dict):
                        continue
                    c_id = c.get("id") or c.get("commentId") or hashlib.md5(json.dumps(c, default=str).encode()).hexdigest()
                    c_author = c.get("author") if isinstance(c.get("author"), dict) else {}
                    c_name = (
                        c_author.get("name")
                        or c_author.get("fullName")
                        or c.get("authorName")
                        or "LinkedIn Commenter"
                    )
                    c_date_raw = c.get("postedAt") or c.get("createdAt") or posted_at
                    results.append({
                        "platform_id": f"LI_COMM_{c_id}",
                        "date": parse_to_wib_iso(c_date_raw),
                        "username": str(c_name),
                        "raw_text": str(c.get("text") or c.get("message") or ""),
                        "likes": int(c.get("numLikes") or c.get("likesCount") or 0),
                        "retweets": 0,
                        "views": 0,
                        "source_platform": "LinkedIn",
                        "log_activity": log_activity,
                        "user_app": user_app
                    })
                    
        return results
    except Exception as e:
        print(f"[ERROR] Kesalahan saat memanggil Aktor LinkedIn Apify (harvestapi/linkedin-profile-posts): {e}")
        return []

def scrape_news_portal(client, general_cfg, log_activity: str = "", user_app: str = "local_user"):
    """
    Menggunakan aktor OFFICIAL 'apify/website-content-crawler' (Playwright Adaptive) untuk menarik
    konten berita. Aktor ini MERENDER JAVASCRIPT sehingga halaman portal berita modern yang
    kontennya dimuat via client-side tidak menghasilkan data KOSONG (kelemahan cheerio-scraper).
    Sesuai spec: catatan_pengerjaan/25 juli 2026/apify_website_content_crawling_JSON_form.txt
    """
    print("[INFO] Memulai penarikan data dari Portal Berita (Aktor: apify/website-content-crawler)...")
    keywords = general_cfg.get("keywords", [])
    
    # ---- Baca daftar portal berita dari config (backward compatible) ----
    raw_urls = general_cfg.get("news_portal_urls")
    
    # Mapping domain → template URL pencarian
    SEARCH_URL_MAP = [
        ("kompas.com",          "https://search.kompas.com/search/?q={kw}"),
        ("cnnindonesia.com",    "https://www.cnnindonesia.com/search/?query={kw}"),
        ("katadata.co.id",      "https://katadata.co.id/search?q={kw}"),
        ("detik.com",           "https://www.detik.com/search/searchall?query={kw}"),
        ("tribunnews.com",      "https://www.tribunnews.com/search?q={kw}"),
        ("liputan6.com",        "https://www.liputan6.com/search?q={kw}"),
        ("merdeka.com",         "https://www.merdeka.com/search/?q={kw}"),
        ("tempo.co",            "https://www.tempo.co/search?q={kw}"),
        ("republika.co.id",     "https://www.republika.co.id/search?q={kw}"),
        ("suara.com",           "https://www.suara.com/search?q={kw}"),
    ]
    
    def parse_portal_url(url_str: str):
        try:
            from urllib.parse import urlparse
        except ImportError:
            from urlparse import urlparse
        if not url_str.startswith("http"):
            url_str = "https://" + url_str.lstrip("/")
        parsed = urlparse(url_str.rstrip("/"))
        hostname = parsed.hostname or ""
        return hostname.lower(), parsed
    
    portal_list_normalized = []
    if raw_urls and isinstance(raw_urls, list):
        for entry in raw_urls:
            if isinstance(entry, str) and entry.strip():
                h, p = parse_portal_url(entry)
                if h:
                    portal_list_normalized.append((h, p, entry.strip()))
    if not portal_list_normalized:
        print("[INFO] news_portal_urls belum terdefinisi, pakai default legacy (kompas, cnn, katadata).")
        LEGACY = ["https://www.kompas.com/", "https://www.cnnindonesia.com/", "https://katadata.co.id/"]
        for entry in LEGACY:
            h, p = parse_portal_url(entry)
            if h:
                portal_list_normalized.append((h, p, entry))
    
    # Prioritas: field spesifik news > general max_results > default 50
    max_results = general_cfg.get("max_results_news")
    if max_results is None:
        max_results = general_cfg.get("max_results", 50)
    max_results = int(max_results)
    
    n_portals = len(portal_list_normalized)
    print(f"[INFO] Daftar portal berita aktif ({n_portals}):")
    for h, _, orig in portal_list_normalized:
        print(f"       → {orig}")
    print(f"[INFO] Crawler Engine: Playwright Adaptive | Block Media: Yes | Proxy: Apify Proxy | Output: Markdown")
    est = len(keywords) * n_portals
    print(f"[INFO] Estimasi crawl: {len(keywords)} keyword × {n_portals} portal = {est} start URLs × {max_results} pages ≈ ~{est * max_results} artikel (maks)")
    
    if not keywords:
        print("[WARNING] Kata kunci tidak ditemukan di konfigurasi. Proses Portal Berita dibatalkan.")
        return []
    if not portal_list_normalized:
        print("[ERROR] Tidak ada portal berita valid yang terdaftar. Proses dibatalkan.")
        return []
    
    # --- Generate start URLs pencarian ---
    start_urls = []
    unknown_warned = set()
    for kw in keywords:
        k_encoded = kw.replace(" ", "%20")
        for hostname, parsed_url, orig_entry in portal_list_normalized:
            template_found = None
            for domain_needle, url_template in SEARCH_URL_MAP:
                if domain_needle in hostname:
                    template_found = url_template
                    break
            if template_found:
                start_urls.append({"url": template_found.format(kw=k_encoded)})
            else:
                scheme = parsed_url.scheme or "https"
                netloc = parsed_url.netloc or hostname
                if hostname not in unknown_warned:
                    unknown_warned.add(hostname)
                    print(f"[WARNING] Portal '{hostname}' tidak dikenal, pakai endpoint /search generik.")
                start_urls.append({"url": f"{scheme}://{netloc}/search?q={k_encoded}"})
    
    # --- run_input RESMI sesuai apify/website-content-crawler JSON form ---
    run_input = {
        "startUrls": start_urls,
        "crawlerType": "playwright:adaptive",
        "blockMedia": True,
        "saveMarkdown": True,
        "saveHtml": False,
        "saveFiles": False,
        "saveScreenshots": False,
        "storeSkippedUrls": False,
        "useSitemaps": False,
        "useLlmsTxt": False,
        "expandIframes": True,
        "removeCookieWarnings": True,
        "aggressivePrune": False,
        "ignoreCanonicalUrl": False,
        "ignoreHttpsErrors": False,
        "keepUrlFragments": False,
        "debugLog": False,
        "debugMode": False,
        "respectRobotsTxtFile": True,
        "reuseStoredDetectionResults": False,
        "signHttpRequests": False,
        "readableTextCharThreshold": 100,
        "renderingTypeDetectionPercentage": 10,
        "clientSideMinChangePercentage": 15,
        "clickElementsCssSelector": "[aria-expanded=\"false\"]",
        "removeElementsCssSelector": "nav, footer, script, style, noscript, svg, img[src^='data:'],[role=\"alert\"],[role=\"banner\"],[role=\"dialog\"],[role=\"alertdialog\"],[role=\"region\"][aria-label*=\"skip\" i],[aria-modal=\"true\"]",
        # maxPagesPerCrawl = field batas halaman (sesuai official actor website-content-crawler)
        "maxPagesPerCrawl": int(max_results),
        "proxyConfiguration": {
            "useApifyProxy": True
        }
    }
    
    try:
        run = client.actor("apify/website-content-crawler").call(run_input=run_input)
        dataset_id = run["defaultDatasetId"]
        
        results = []
        for item in client.dataset(dataset_id).iterate_items():
            # Struktur dataset website-content-crawler: url, markdown, html, title, metadata:{date, author,...}, loadedUrl
            url = item.get("url") or item.get("loadedUrl") or item.get("userData", {}).get("url") if isinstance(item.get("userData"), dict) else None
            if not url:
                continue
            
            title = (
                item.get("title")
                or (item.get("metadata") or {}).get("title") if isinstance(item.get("metadata"), dict) else None
                or None
            )
            
            # Ambil body: prioritas markdown yang bersih (tanpa tag nav/footer) > html
            body_text = item.get("markdown") or item.get("text") or item.get("content") or ""
            metadata_obj = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
            date_raw = (
                metadata_obj.get("date")
                or metadata_obj.get("publishedTime")
                or metadata_obj.get("modifiedTime")
                or item.get("date")
                or item.get("timestamp")
            )
            
            # Batasi panjang body agar DB tidak membengkak
            if isinstance(body_text, str):
                body_text = body_text[:3000]
            else:
                body_text = ""
            if isinstance(title, str):
                title = title.strip()[:300]
            
            # Quality filter: skip jika title & body sama-sama kosong
            if (not title or not title.strip()) and (not body_text or len(body_text.strip()) < 80):
                continue
            
            url_hash = hashlib.md5(str(url).encode('utf-8')).hexdigest()
            try:
                from urllib.parse import urlparse as _up
                domain_name = (_up(url).hostname or "").lower() or "News Portal"
            except Exception:
                domain_name = "News Portal"
            
            # Susun raw_text untuk AI processing: JUDUL + ISI (sama format lama agar kompatibel dengan SVM pipeline)
            display_title = title if title else "(Tanpa Judul)"
            raw_text_payload = f"JUDUL: {display_title} | ISI: {body_text}"
            
            results.append({
                "platform_id": f"NEWS_{url_hash}",
                "date": parse_to_wib_iso(date_raw),
                "username": domain_name,
                "raw_text": raw_text_payload,
                "likes": 0,
                "retweets": 0,
                "views": 0,
                "source_platform": "News",
                "log_activity": log_activity,
                "user_app": user_app
            })
            
        return results
    except Exception as e:
        print(f"[ERROR] Kesalahan saat memanggil Aktor Portal Berita Apify (apify/website-content-crawler): {e}")
        return []

def main():
    # 1. Pastikan tabel database siap
    buat_tabel()
    
    # 1b. Cek Mode Scraping (Manual vs Otomatis)
    # Mode 'manual' hanya memblokir eksekusi otomatis yang dipanggil oleh cron/CI.
    # Jika dipanggil secara eksplisit (via tombol Dasbor UI atau CLI manual), scraper HARUS tetap berjalan.
    called_from_cron = (os.environ.get("GITHUB_ACTIONS") == "true") or (os.environ.get("PIPELINE_CRON_RUN") == "1") or ("--cron" in sys.argv)
    mode = get_scraping_mode()
    if called_from_cron and mode == 'manual':
        print("[INFO] Dipanggil dari cron, tetapi mode penarikan data diatur ke MANUAL. Cronjob otomatis dilewati.")
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
    
    cfg_base = config.get("config", {})
    general_cfg = cfg_base.get("general", {})
    
    # Simpan riwayat keysearch ke database dari seluruh platform aktif
    try:
        all_kw, all_prof, all_hash = [], [], []
        for c_key in ["general", "twitter", "instagram", "linkedin", "portal_berita"]:
            sub_cfg = cfg_base.get(c_key, {})
            if isinstance(sub_cfg, dict):
                all_kw.extend(sub_cfg.get("keywords", []))
                all_prof.extend(sub_cfg.get("profiles", []))
                all_hash.extend(sub_cfg.get("hashtags", []))
        simpan_keysearch_history(all_kw, all_prof, all_hash)
    except Exception as _e_hist:
        pass
    
    # 3. Muat Apify Client
    client = get_apify_client()
    if not client:
        sys.exit(1)
    
    # 3b. Generate log_activity — satu timestamp untuk seluruh sesi scraping ini
    sesi_mulai = datetime.now()
    log_activity = format_log_activity(sesi_mulai)
    print(f"[INFO] Sesi scraping dimulai: {log_activity}")
    
    # 3c. User app — belum ada sistem login, gunakan default hostname atau env var
    user_app = os.environ.get("STREAMLIT_USER_APP", "local_user")
        
    # 4. Iterasi scraping untuk SETIAP platform yang dipilih (multi-platform sekaligus)
    all_results = []
    for source_type in source_types:
        print(f"\n{'='*60}")
        print(f"[INFO] >>> Memulai proses scraping untuk platform: {source_type}")
        print(f"{'='*60}")
        
        if source_type.startswith("twitter"):
            plat_cfg = cfg_base.get("twitter", general_cfg)
            partial = scrape_twitter(client, plat_cfg, log_activity=log_activity, user_app=user_app)
        elif source_type == "instagram":
            plat_cfg = cfg_base.get("instagram", general_cfg)
            partial = scrape_instagram(client, plat_cfg, log_activity=log_activity, user_app=user_app)
        elif source_type == "linkedin":
            plat_cfg = cfg_base.get("linkedin", general_cfg)
            partial = scrape_linkedin(client, plat_cfg, log_activity=log_activity, user_app=user_app)
        elif source_type in ["portal_berita", "news_portal", "news"]:
            plat_cfg = cfg_base.get("portal_berita", general_cfg)
            partial = scrape_news_portal(client, plat_cfg, log_activity=log_activity, user_app=user_app)
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
