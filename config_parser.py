import json

def load_config(config_path='target_config.json'):
    """
    Membaca berkas konfigurasi target_config.json dan mengembalikan dictionary.
    """
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"[ERROR] Berkas konfigurasi '{config_path}' tidak ditemukan.")
        return {}
    except json.JSONDecodeError as e:
        print(f"[ERROR] Gagal mem-parsing JSON: {e}")
        return {}

def build_twitter_query(config):
    """
    Merangkai kata kunci, hashtag, dan profil dari konfigurasi menjadi 
    format kueri pencarian tingkat lanjut Twitter (X) yang valid.
    """
    general = config.get("config", {}).get("general", {})
    keywords = general.get("keywords", [])
    hashtags = general.get("hashtags", [])
    profiles = general.get("profiles", [])
    
    parts = []
    
    # 1. Proses kata kunci
    if keywords:
        kw_parts = []
        for k in keywords:
            k = k.strip()
            if not k:
                continue
            # Gunakan tanda kutip ganda jika kata kunci mengandung spasi
            if ' ' in k:
                kw_parts.append(f'"{k}"')
            else:
                kw_parts.append(k)
        if kw_parts:
            parts.append(f"({' OR '.join(kw_parts)})")
            
    # 2. Proses hashtag
    if hashtags:
        hash_parts = []
        for h in hashtags:
            h = h.strip()
            if not h:
                continue
            # Tambahkan simbol '#' jika belum ada
            if not h.startswith('#'):
                h = f"#{h}"
            hash_parts.append(h)
        if hash_parts:
            parts.append(f"({' OR '.join(hash_parts)})")
            
    # 3. Proses profil penulis (usernames)
    if profiles:
        prof_parts = []
        for p in profiles:
            p = p.strip()
            if not p:
                continue
            # Bersihkan karakter '@' jika ada
            if p.startswith('@'):
                p = p[1:]
            prof_parts.append(f"from:{p}")
        if prof_parts:
            parts.append(f"({' OR '.join(prof_parts)})")
            
    # Jika tidak ada parameter yang terisi, gunakan kueri default
    if not parts:
        return 'IKN OR "Ibu Kota Baru"'
        
    # Gabungkan semua komponen utama dengan operator OR
    query = " OR ".join(parts)
    return query

def get_source_types(config):
    """
    Mendapatkan daftar platform sumber dari konfigurasi.
    Dukung format baru (source_types array) dan backward compat (source_type string).
    """
    raw = config.get("source_types")
    if not raw:
        single = config.get("source_type", "")
        raw = [single] if single else []
    if isinstance(raw, str):
        raw = [raw]
    return [str(s).strip().lower() for s in raw if s and str(s).strip()]


if __name__ == "__main__":
    # Uji coba parser kueri secara mandiri
    cfg = load_config()
    if cfg:
        print("[INFO] Konfigurasi berhasil dimuat.")
        sources = get_source_types(cfg)
        print(f"[INFO] Daftar platform sasaran ({len(sources)}): {sources}")
        if "twitter_" in sources or any(s.startswith("twitter") for s in sources):
            query = build_twitter_query(cfg)
            print(f"[INFO] Twitter Query hasil rancangan: {query}")
        else:
            print("[INFO] Twitter tidak termasuk dalam platform aktif, query Twitter dilewati.")
