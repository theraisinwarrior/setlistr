"""Tiered Spotify track matching. Pure logic, no Streamlit imports."""
import re

STOP_WORDS = {
    'a', 'an', 'the', 'and', 'or', 'of', 'to', 'in', 'on', 'for', 'with', 'by',
    'is', 'it', 'you', 'me', 'i', 'my', 'your', 'we', 'our', 'us', 'he', 'she',
    'him', 'her', 'they', 'them', 'their', 'this', 'that', 'be', 'do', 'are', 'was',
}


def is_artist_match(target_artist, item_artists):
    target_clean = re.sub(r'[^a-zA-Z0-9]', '', target_artist.lower())
    for a in item_artists:
        a_clean = re.sub(r'[^a-zA-Z0-9]', '', a.get("name", "").lower())
        if target_clean in a_clean or a_clean in target_clean:
            return True
    return False


def is_reasonable_match(requested_title, matched_title):
    req_clean = re.sub(r'[^a-zA-Z0-9]', '', requested_title.lower())
    match_clean = re.sub(r'[^a-zA-Z0-9]', '', matched_title.lower())

    if req_clean in match_clean or match_clean in req_clean:
        return True

    req_words = set(re.findall(r'\w+', requested_title.lower())) - STOP_WORDS
    match_words = set(re.findall(r'\w+', matched_title.lower())) - STOP_WORDS

    if not req_words:
        return req_clean in match_clean or match_clean in req_clean

    return len(req_words.intersection(match_words)) > 0


def _format_match(item):
    artist_names = ", ".join(a["name"] for a in item.get("artists", []))
    return f"{item.get('name')} by {artist_names}"


def _run_spotify_search_tiers(sp, search_artist, song_title):
    clean_title = re.sub(r'[\(\[\{\}\]\)].*?[\)\]\}]', '', song_title)
    clean_title = clean_title.split('/')[0].strip()
    target_title = clean_title if clean_title else song_title

    safe_title = re.sub(r'["\\]', '', target_title).strip()
    safe_artist = re.sub(r'["\\]', '', search_artist).strip()
    clean_terms_title = re.sub(r'[^a-zA-Z0-9\s]', ' ', target_title).strip()

    tiers = [
        (f'track:"{safe_title}" artist:"{safe_artist}"', 5, "Exact Field Match"),
        (f'track:{clean_terms_title} artist:"{safe_artist}"', 5, "Cleaned Field Match"),
        (f'"{safe_artist}" "{safe_title}"', 5, "Exact Phrase Match"),
        (f'{safe_artist} {safe_title}', 10, "Fuzzy Verified Match"),
    ]

    for query, limit, label in tiers:
        try:
            res = sp.search(q=query, type="track", limit=limit)
            for item in res.get("tracks", {}).get("items", []):
                if (is_artist_match(search_artist, item.get("artists", []))
                        and is_reasonable_match(target_title, item.get("name", ""))):
                    return item["uri"], _format_match(item), label
        except Exception:
            pass

    return None, None, None


def search_spotify_track(sp, artist, song_title, orig_artist):
    """Return (uri, matched details, method). Falls back to the original artist for covers."""
    uri, details, method = _run_spotify_search_tiers(sp, artist, song_title)
    if uri:
        return uri, details, method

    if orig_artist and orig_artist != "Official Release":
        uri_cov, details_cov, _ = _run_spotify_search_tiers(sp, orig_artist, song_title)
        if uri_cov:
            return uri_cov, details_cov, f"Cover Fallback ({orig_artist})"

    return None, "None", "❌ Not Found"
