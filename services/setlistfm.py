"""Setlist.fm API access and the (fragile) career-stats page scrape."""
import re
import time

import requests
import streamlit as st

API_BASE = "https://api.setlist.fm/rest/1.0"
TIMEOUT = 10


def _headers(api_key: str) -> dict:
    return {"x-api-key": api_key, "Accept": "application/json"}


def _get(url: str, api_key: str, retries: int = 3):
    """GET with a timeout and simple backoff on HTTP 429."""
    resp = None
    for attempt in range(retries):
        resp = requests.get(url, headers=_headers(api_key), timeout=TIMEOUT)
        if resp.status_code != 429:
            return resp
        time.sleep(1.5 * (attempt + 1))
    return resp


class SetlistFmError(Exception):
    """A problem talking to setlist.fm, with a message that is safe to show the user."""


def fetch_attended_setlists(username: str, api_key: str, max_pages: int = 100) -> list:
    """Return every setlist the user has marked as attended on setlist.fm.

    Raises SetlistFmError with a friendly message on failure.
    """
    username = username.strip()
    if not username:
        raise SetlistFmError("Enter a setlist.fm username.")

    all_setlists, page = [], 1
    while page <= max_pages:
        url = f"{API_BASE}/user/{requests.utils.quote(username)}/attended?p={page}"
        try:
            resp = _get(url, api_key)
        except requests.RequestException:
            raise SetlistFmError("Couldn't reach setlist.fm. Try again in a minute.")

        if resp is None:
            raise SetlistFmError("Couldn't reach setlist.fm. Try again in a minute.")
        if resp.status_code == 404:
            raise SetlistFmError(f"No setlist.fm user named '{username}' was found.")
        if resp.status_code in (401, 403):
            raise SetlistFmError("setlist.fm rejected the API key.")
        if resp.status_code == 429:
            raise SetlistFmError("setlist.fm is rate-limiting requests. Try again in a minute.")
        if resp.status_code != 200:
            raise SetlistFmError(f"setlist.fm returned an error (HTTP {resp.status_code}).")

        data = resp.json()
        batch = data.get("setlist", [])
        if not batch:
            break
        all_setlists.extend(batch)

        per_page = data.get("itemsPerPage") or len(batch)
        total = data.get("total", 0)
        if page * per_page >= total:
            break

        page += 1
        time.sleep(0.6)  # stay under setlist.fm's 2 requests/second limit

    return all_setlists


def get_mbid_from_name(artist_query: str, api_key: str):
    """Resolve an artist name to (mbid, canonical name), or (None, None)."""
    clean_query = artist_query.strip().lower()
    url = f"{API_BASE}/search/artists?artistName={requests.utils.quote(artist_query)}&sort=relevance"

    response = _get(url, api_key)
    if response is not None and response.status_code == 200:
        artists = response.json().get("artist", [])
        if artists:
            for a in artists:
                if a.get("name", "").strip().lower() == clean_query:
                    return a["mbid"], a["name"]
            for a in artists:
                name_lower = a.get("name", "").lower()
                if "feat" not in name_lower and "with" not in name_lower:
                    return a["mbid"], a["name"]
            return artists[0]["mbid"], artists[0]["name"]
    return None, None


def fetch_setlists(artist_mbid: str, api_key: str, max_shows: int,
                   is_ytd: bool, target_year: int) -> list:
    """Page through setlists for an artist (recent shows, or a whole year)."""
    needed_raw = max(max_shows + 15, 40) if not is_ytd else 100
    fetched, page = [], 1

    while len(fetched) < needed_raw and page <= 10:
        if is_ytd:
            url = f"{API_BASE}/search/setlists?artistMbid={artist_mbid}&year={target_year}&p={page}"
        else:
            url = f"{API_BASE}/artist/{artist_mbid}/setlists?p={page}"

        response = _get(url, api_key)
        if response is None or response.status_code != 200:
            break
        batch = response.json().get("setlist", [])
        if not batch:
            break

        fetched.extend(batch)
        page += 1
        time.sleep(0.3)

    return fetched


@st.cache_data(ttl=86400)  # cache career stats for 24 hours
def get_global_artist_stats(artist_name: str, api_key: str = ""):
    """Scrape an artist's career setlist count and per-song play counts.

    NOTE: this parses setlist.fm HTML with regexes and can break if the page
    changes. Phase 3 plan: replace with frequencies computed from API data.
    Returns (total_career_shows | None, {song_lower: {...}}).
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    stats_url = None
    mbid = ""

    if api_key:
        try:
            search_url = f"{API_BASE}/search/artists?artistName={requests.utils.quote(artist_name)}&sort=relevance"
            resp = requests.get(search_url, headers=_headers(api_key), timeout=5)
            if resp.status_code == 200:
                artists = resp.json().get("artist", [])
                if artists:
                    top = artists[0]
                    mbid = top.get("mbid", "")
                    artist_url = top.get("url", "")
                    if "/setlists/" in artist_url:
                        stats_url = artist_url.replace("/setlists/", "/stats/")
        except Exception:
            pass

    candidate_urls = []
    if stats_url:
        candidate_urls.append(stats_url)
    if mbid:
        candidate_urls.append(f"https://www.setlist.fm/stats/artist/{mbid}")
    slug = re.sub(r"[^a-zA-Z0-9\s-]", "", artist_name).strip().lower().replace(" ", "-")
    candidate_urls.append(f"https://www.setlist.fm/stats/{slug}.html")

    html_text = None
    for url in candidate_urls:
        try:
            res = requests.get(url, headers=headers, timeout=5, allow_redirects=True)
            if res.status_code == 200 and ("setlist" in res.text.lower() or "song" in res.text.lower()):
                html_text = res.text
                break
        except Exception:
            continue

    if not html_text:
        return None, {}

    shows_match = re.search(r"setlists?:?\s*<[^>]+>(\d[\d,]*)<", html_text, re.IGNORECASE)
    if not shows_match:
        shows_match = re.search(r"(\d[\d,]*)\s+setlists", html_text, re.IGNORECASE)
    if not shows_match:
        shows_match = re.search(r"Setlists:\s*<b>(\d[\d,]*)</b>", html_text, re.IGNORECASE)

    total_career_shows = int(shows_match.group(1).replace(",", "")) if shows_match else 100

    song_matches = re.findall(
        r'href="[^"]*/song/[^"]*">([^<]+)</a>.*?<span[^>]*>(\d+)</span>', html_text, re.DOTALL)
    if not song_matches:
        song_matches = re.findall(
            r'href="[^"]*/song/[^"]*">([^<]+)</a>.*?<td[^>]*>\s*(\d+)\s*</td>', html_text, re.DOTALL)

    stats = {}
    for song_name, count in song_matches:
        cnt = int(count)
        stats[song_name.strip().lower()] = {
            "global_count": cnt,
            "global_pct": (cnt / total_career_shows) * 100.0,
        }

    return total_career_shows, stats
