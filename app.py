import streamlit as st
import requests
import pandas as pd
import re
import time
from collections import defaultdict
from datetime import datetime, timedelta
import spotipy
from spotipy.oauth2 import SpotifyOAuth

# ==========================================
# PAGE CONFIGURATION
# ==========================================
st.set_page_config(page_title="Tour Setlist Playlist Generator", page_icon="🎵", layout="wide")

st.title("🎵 Tour Setlist Playlist Generator")
st.write("Analyze recent concert setlists from Setlist.fm and automatically build a Spotify prep playlist.")

# Live Streamlit App Redirect URI
REDIRECT_URI = "https://setlistr.streamlit.app/"

# Current Calendar Year
CURRENT_YEAR = datetime.now().year
YEAR_OPTIONS = list(range(CURRENT_YEAR, 1999, -1))

# ==========================================
# SILENT CREDENTIAL LOADING
# ==========================================
setlist_api_key = st.secrets.get("SETLIST_API_KEY", "")
if not setlist_api_key:
    setlist_api_key = st.sidebar.text_input("Setlist.fm API Key", type="password")

spotify_client_id = st.secrets.get("SPOTIPY_CLIENT_ID", "")
spotify_client_secret = st.secrets.get("SPOTIPY_CLIENT_SECRET", "")
spotify_refresh_token = st.secrets.get("SPOTIFY_REFRESH_TOKEN", "")

# ==========================================
# HYBRID SPOTIFY AUTHENTICATION HANDLER
# ==========================================
st.sidebar.header("1. Spotify Account")

sp_oauth = SpotifyOAuth(
    client_id=spotify_client_id,
    client_secret=spotify_client_secret,
    redirect_uri=REDIRECT_URI,
    scope="playlist-modify-public playlist-modify-private"
)

# 1. Returning from manual OAuth redirect
if "code" in st.query_params:
    auth_code = st.query_params["code"]
    try:
        token_info = sp_oauth.get_access_token(auth_code)
        st.session_state["spotify_token"] = token_info["access_token"]
        st.session_state["user_mode"] = "friend"
        st.query_params.clear()
        st.rerun()
    except Exception as e:
        st.sidebar.error(f"Spotify Login Error: {e}")

# 2. Check current session status
if "spotify_token" in st.session_state:
    if st.session_state.get("user_mode") == "owner":
        st.sidebar.success("✅ Auto-Connected (Your Account)")
    else:
        st.sidebar.success("✅ Connected to Spotify!")

    if st.sidebar.button("Log Out / Switch Account"):
        del st.session_state["spotify_token"]
        st.session_state["user_mode"] = None
        st.rerun()

# 3. Default state: Auto-connect owner token, offer login for friends
else:
    if spotify_refresh_token:
        try:
            token_info = sp_oauth.refresh_access_token(spotify_refresh_token)
            st.session_state["spotify_token"] = token_info["access_token"]
            st.session_state["user_mode"] = "owner"
            st.rerun()
        except Exception:
            pass

    auth_url = sp_oauth.get_authorize_url()
    st.sidebar.info("Connect your Spotify account to save playlists directly to your library.")
    st.sidebar.link_button("🎵 Connect Your Spotify Account", auth_url, use_container_width=True)

st.sidebar.divider()

# ==========================================
# FILTER PRESETS CONFIGURATION
# ==========================================
BASE_PRESETS = {
    "Custom (Manual Toggles)": None,
    "🎯 Standard Tour Prep": {
        "filter_mode": "SHOWS",
        "max_shows": 15,
        "days_lookback": 120,
        "min_songs": 8,
        "min_freq": 20,
        "max_days_since_played": 0,
        "hide_covers": False,
        "hide_tape": True,
        "max_playlist_songs": 25
    },
    "⚡ Core Staples Only": {
        "filter_mode": "SHOWS",
        "max_shows": 20,
        "days_lookback": 180,
        "min_songs": 8,
        "min_freq": 50,
        "max_days_since_played": 0,
        "hide_covers": False,
        "hide_tape": True,
        "max_playlist_songs": 20
    },
    "⏳ Recent 90 Days": {
        "filter_mode": "DAYS",
        "days_lookback": 90,
        "max_shows": 20,
        "min_songs": 5,
        "min_freq": 15,
        "max_days_since_played": 90,
        "hide_covers": False,
        "hide_tape": True,
        "max_playlist_songs": 25
    },
    "🎵 Deep Cuts & Full History": {
        "filter_mode": "SHOWS",
        "max_shows": 30,
        "days_lookback": 365,
        "min_songs": 3,
        "min_freq": 0,
        "max_days_since_played": 0,
        "hide_covers": False,
        "hide_tape": True,
        "max_playlist_songs": 0
    }
}

if "custom_presets" not in st.session_state:
    st.session_state["custom_presets"] = {}

def get_all_presets():
    return {**BASE_PRESETS, **st.session_state["custom_presets"]}

def apply_preset():
    selected = st.session_state.get("preset_choice")
    all_p = get_all_presets()
    if selected and selected in all_p and all_p[selected] is not None:
        p = all_p[selected]
        st.session_state["filter_mode_key"] = p["filter_mode"]
        st.session_state["hide_covers_key"] = p["hide_covers"]
        st.session_state["hide_tape_key"] = p["hide_tape"]

        for prefix, key in [
            ("days", "days_lookback"), 
            ("shows", "max_shows"), 
            ("songs", "min_songs"), 
            ("freq", "min_freq"), 
            ("recency", "max_days_since_played"),
            ("maxp", "max_playlist_songs")
        ]:
            val = p.get(key, 0)
            st.session_state[f"{prefix}_slider"] = val
            st.session_state[f"{prefix}_num"] = val


# ==========================================
# HELPER: DIRECTLY SYNCHRONIZED SLIDER + NUMBER INPUT
# ==========================================
def linked_numeric_input(label, min_v, max_v, default_v, key_prefix, step=1):
    """Creates side-by-side slider and number box that update concurrently."""
    slider_key = f"{key_prefix}_slider"
    num_key = f"{key_prefix}_num"

    if slider_key not in st.session_state:
        st.session_state[slider_key] = default_v
    if num_key not in st.session_state:
        st.session_state[num_key] = default_v

    def sync_from_slider():
        st.session_state[num_key] = st.session_state[slider_key]

    def sync_from_num():
        st.session_state[slider_key] = st.session_state[num_key]

    st.sidebar.caption(label)
    c1, c2 = st.sidebar.columns([3, 2])
    with c1:
        st.slider(
            label,
            min_value=min_v,
            max_value=max_v,
            key=slider_key,
            on_change=sync_from_slider,
            step=step,
            label_visibility="collapsed"
        )
    with c2:
        st.number_input(
            label,
            min_value=min_v,
            max_value=max_v,
            key=num_key,
            on_change=sync_from_num,
            step=step,
            label_visibility="collapsed"
        )
    return st.session_state[slider_key]


# ==========================================
# SETLIST & TRACK FILTERS
# ==========================================
st.sidebar.header("2. Artist & Show Filters")

artist_name_input = st.sidebar.text_input("Artist Name", "Taylor Swift")

if "filter_mode_key" not in st.session_state:
    st.session_state["filter_mode_key"] = "SHOWS"
if "hide_covers_key" not in st.session_state:
    st.session_state["hide_covers_key"] = False
if "hide_tape_key" not in st.session_state:
    st.session_state["hide_tape_key"] = True

filter_mode = st.sidebar.selectbox("Filter Mode", ["SHOWS", "DAYS", "BOTH"], key="filter_mode_key")

st.sidebar.selectbox(
    "Filter Presets", 
    list(get_all_presets().keys()), 
    key="preset_choice", 
    on_change=apply_preset
)

with st.sidebar.expander("💾 Save Current Toggles as Preset"):
    new_preset_name = st.text_input("Preset Name", placeholder="e.g. Festival Sets", key="new_preset_name_input")
    if st.button("Save Preset", use_container_width=True):
        if new_preset_name.strip():
            preset_label = f"⭐ {new_preset_name.strip()}"
            st.session_state["custom_presets"][preset_label] = {
                "filter_mode": st.session_state.get("filter_mode_key", "SHOWS"),
                "max_shows": st.session_state.get("shows_slider", 20),
                "days_lookback": st.session_state.get("days_slider", 120),
                "min_songs": st.session_state.get("songs_slider", 5),
                "min_freq": st.session_state.get("freq_slider", 5),
                "max_days_since_played": st.session_state.get("recency_slider", 0),
                "hide_covers": st.session_state.get("hide_covers_key", False),
                "hide_tape": st.session_state.get("hide_tape_key", True),
                "max_playlist_songs": st.session_state.get("maxp_slider", 30)
            }
            st.session_state["preset_choice"] = preset_label
            st.success(f"Saved '{preset_label}'!")
            st.rerun()
        else:
            st.warning("Please enter a name for your preset.")

st.sidebar.divider()

days_lookback = linked_numeric_input("Days Lookback", 1, 365, 120, "days")
max_shows = linked_numeric_input("Max Shows to Fetch", 1, 100, 20, "shows")
min_songs = linked_numeric_input("Min Songs Per Show", 1, 50, 5, "songs")

st.sidebar.header("3. Track Filters")
min_freq = linked_numeric_input("Min Play Frequency (%)", 0, 100, 5, "freq", step=5)
max_days_since_played = linked_numeric_input("Played Within Last X Days (0 = Disabled)", 0, 365, 0, "recency", step=5)
hide_covers = st.sidebar.checkbox("Exclude Cover Songs", key="hide_covers_key")
hide_tape = st.sidebar.checkbox("Exclude Tape Playbacks (PA/Intros)", key="hide_tape_key")
max_playlist_songs = linked_numeric_input("Max Playlist Length (0 = Unlimited)", 0, 100, 30, "maxp")


# ==========================================
# HELPER: SMART AUTOMATIC MBID LOOKUP
# ==========================================
def get_mbid_from_name(artist_query, api_key):
    """Queries Setlist.fm API and prioritizes exact solo artist matches over guest features."""
    clean_query = artist_query.strip().lower()
    url = f"https://api.setlist.fm/rest/1.0/search/artists?artistName={requests.utils.quote(artist_query)}&sort=relevance"
    headers = {"x-api-key": api_key, "Accept": "application/json"}
    
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        data = response.json()
        artists = data.get("artist", [])
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


# ==========================================
# HELPER: MATCH VERIFICATION GUARDS
# ==========================================
def is_artist_match(target_artist, item_artists):
    """Verifies that the target artist is present in the Spotify track's artist list."""
    target_clean = re.sub(r'[^a-zA-Z0-9]', '', target_artist.lower())
    for a in item_artists:
        a_clean = re.sub(r'[^a-zA-Z0-9]', '', a.get("name", "").lower())
        if target_clean in a_clean or a_clean in target_clean:
            return True
    return False

def is_reasonable_match(requested_title, matched_title):
    """Verifies that Spotify didn't return an unrelated top track."""
    req_clean = re.sub(r'[^a-zA-Z0-9]', '', requested_title.lower())
    match_clean = re.sub(r'[^a-zA-Z0-9]', '', matched_title.lower())
    
    if req_clean in match_clean or match_clean in req_clean:
        return True
    
    stop_words = {
        'a', 'an', 'the', 'and', 'or', 'of', 'to', 'in', 'on', 'for', 'with', 'by', 
        'is', 'it', 'you', 'me', 'i', 'my', 'your', 'we', 'our', 'us', 'he', 'she', 
        'him', 'her', 'they', 'them', 'their', 'this', 'that', 'be', 'do', 'are', 'was'
    }
    
    req_words = set(re.findall(r'\w+', requested_title.lower())) - stop_words
    match_words = set(re.findall(r'\w+', matched_title.lower())) - stop_words
    
    if not req_words: 
        return req_clean in match_clean or match_clean in req_clean
        
    overlap = req_words.intersection(match_words)
    return len(overlap) > 0


# ==========================================
# HELPER: PRECISION MULTI-TIER SPOTIFY SEARCH
# ==========================================
def _run_spotify_search_tiers(sp, search_artist, song_title):
    """Executes 4 search tiers for a given artist/title combo."""
    def format_match(item):
        artist_names = ", ".join([a["name"] for a in item.get("artists", [])])
        return f"{item.get('name')} by {artist_names}"

    clean_title = re.sub(r'[\(\[\{\}\]\)].*?[\)\]\}]', '', song_title)
    clean_title = clean_title.split('/')[0].strip()
    target_title = clean_title if clean_title else song_title

    safe_title = re.sub(r'["\\]', '', target_title).strip()
    safe_artist = re.sub(r'["\\]', '', search_artist).strip()

    # TIER 1: Strict Field Query
    try:
        q1 = f'track:"{safe_title}" artist:"{safe_artist}"'
        res1 = sp.search(q=q1, type="track", limit=5)
        for item in res1.get("tracks", {}).get("items", []):
            if is_artist_match(search_artist, item.get("artists", [])) and is_reasonable_match(target_title, item.get("name", "")):
                return item["uri"], format_match(item), "Exact Field Match"
    except Exception:
        pass

    # TIER 2: Unquoted Field Query
    try:
        clean_terms_title = re.sub(r'[^a-zA-Z0-9\s]', ' ', target_title).strip()
        q2 = f'track:{clean_terms_title} artist:"{safe_artist}"'
        res2 = sp.search(q=q2, type="track", limit=5)
        for item in res2.get("tracks", {}).get("items", []):
            if is_artist_match(search_artist, item.get("artists", [])) and is_reasonable_match(target_title, item.get("name", "")):
                return item["uri"], format_match(item), "Cleaned Field Match"
    except Exception:
        pass

    # TIER 3: Exact Phrase Search
    try:
        q3 = f'"{safe_artist}" "{safe_title}"'
        res3 = sp.search(q=q3, type="track", limit=5)
        for item in res3.get("tracks", {}).get("items", []):
            if is_artist_match(search_artist, item.get("artists", [])) and is_reasonable_match(target_title, item.get("name", "")):
                return item["uri"], format_match(item), "Exact Phrase Match"
    except Exception:
        pass

    # TIER 4: Broad Search with Verification
    try:
        q4 = f'{safe_artist} {safe_title}'
        res4 = sp.search(q=q4, type="track", limit=10)
        for item in res4.get("tracks", {}).get("items", []):
            if is_artist_match(search_artist, item.get("artists", [])) and is_reasonable_match(target_title, item.get("name", "")):
                return item["uri"], format_match(item), "Fuzzy Verified Match"
    except Exception:
        pass

    return None, None, None


def search_spotify_track(sp, artist, song_title, orig_artist):
    """Two-Pass Search: First tries performing artist; if unreleased, falls back to original artist."""
    # PASS 1: Try performing artist first (e.g. Foo Fighters)
    uri, details, method = _run_spotify_search_tiers(sp, artist, song_title)
    if uri:
        return uri, details, method

    # PASS 2: If cover and performing artist has no release on Spotify, try original artist (e.g. Prince / Late!)
    if orig_artist and orig_artist != "Official Release":
        uri_cov, details_cov, method_cov = _run_spotify_search_tiers(sp, orig_artist, song_title)
        if uri_cov:
            return uri_cov, details_cov, f"Cover Fallback ({orig_artist})"

    return None, "None", "❌ Not Found"


# ==========================================
# ACTION BUTTONS & YEAR SELECTOR
# ==========================================
btn_col1, btn_col2, btn_col3 = st.columns([2, 2, 1])

with btn_col3:
    selected_year = st.selectbox("Year", YEAR_OPTIONS, index=0, label_visibility="collapsed")

with btn_col1:
    fetch_clicked = st.button("🚀 Fetch Setlists & Analyze", use_container_width=True)

with btn_col2:
    ytd_clicked = st.button(f"📅 Most Played ({selected_year})", use_container_width=True)

if fetch_clicked or ytd_clicked:
    st.session_state["ytd_mode"] = True if ytd_clicked else False
    st.session_state["target_year"] = selected_year

    if not setlist_api_key:
        st.error("Please provide a Setlist.fm API key in Secrets or Sidebar.")
    else:
        with st.spinner("Finding artist and fetching setlists from Setlist.fm..."):
            artist_mbid, official_artist_name = get_mbid_from_name(artist_name_input, setlist_api_key)
            
            if not artist_mbid:
                st.error(f"Could not find an artist matching '{artist_name_input}' on Setlist.fm.")
            else:
                headers = {"x-api-key": setlist_api_key, "Accept": "application/json"}
                fetched_setlists = []
                page = 1
                stop_fetching = False
                is_ytd = st.session_state["ytd_mode"]
                target_year = st.session_state["target_year"]

                needed_raw = max(max_shows + 15, 40) if not is_ytd else 100

                while len(fetched_setlists) < needed_raw and page <= 10 and not stop_fetching:
                    if is_ytd:
                        url = f"https://api.setlist.fm/rest/1.0/search/setlists?artistMbid={artist_mbid}&year={target_year}&p={page}"
                    else:
                        url = f"https://api.setlist.fm/rest/1.0/artist/{artist_mbid}/setlists?p={page}"

                    response = requests.get(url, headers=headers)
                    if response.status_code != 200:
                        break
                        
                    data = response.json()
                    batch = data.get("setlist", [])
                    if not batch:
                        break
                        
                    fetched_setlists.extend(batch)
                    page += 1
                    time.sleep(0.3)

                if not fetched_setlists:
                    if is_ytd:
                        st.warning(f"No shows recorded on Setlist.fm for '{official_artist_name}' in {target_year}.")
                    else:
                        st.warning(f"No setlists found for '{official_artist_name}'.")
                else:
                    st.session_state["raw_setlists"] = fetched_setlists
                    st.session_state["artist_name"] = official_artist_name


# ==========================================
# LIVE RECALCULATION & DISPLAY
# ==========================================
if "raw_setlists" in st.session_state and st.session_state["raw_setlists"]:
    raw_setlists = st.session_state["raw_setlists"]
    current_artist = st.session_state.get("artist_name", artist_name_input)
    is_ytd = st.session_state.get("ytd_mode", False)
    target_year = st.session_state.get("target_year", CURRENT_YEAR)

    today = datetime.now()
    cutoff_date = today - timedelta(days=int(days_lookback)) if filter_mode in ["DAYS", "BOTH"] else None

    # Filter fetched setlists dynamically based on mode
    filtered_shows = []
    for show in raw_setlists:
        event_date_raw = show.get("eventDate")
        if not event_date_raw:
            continue
        show_dt = datetime.strptime(event_date_raw, "%d-%m-%Y")
        
        if is_ytd:
            if show_dt.year != target_year:
                continue
        else:
            if cutoff_date and show_dt < cutoff_date:
                if filter_mode in ["DAYS", "BOTH"]:
                    continue

        sets = show.get("sets", {}).get("set", [])
        song_count = sum(len(s.get("song", [])) for s in sets)
        
        if song_count >= min_songs:
            filtered_shows.append(show)
            if not is_ytd and filter_mode in ["SHOWS", "BOTH"] and len(filtered_shows) == max_shows:
                break

    total_shows = len(filtered_shows)

    if total_shows == 0:
        if is_ytd:
            st.warning(f"No shows recorded on Setlist.fm for '{current_artist}' in {target_year}.")
        else:
            st.warning(f"No matching full shows found for '{current_artist}' with the current filter settings.")
    else:
        song_dates = defaultdict(list)
        song_covers = {}

        for show in filtered_shows:
            event_date = show.get("eventDate")
            show_url = show.get("url", "")
            sets = show.get("sets", {}).get("set", [])
            for s in sets:
                for song in s.get("song", []):
                    is_tape_playback = song.get("tape", False)
                    if hide_tape and is_tape_playback:
                        continue

                    song_name = song.get("name")
                    if song_name:
                        song_dates[song_name].append((event_date, show_url))
                        cover_data = song.get("cover")
                        if cover_data and "name" in cover_data:
                            song_covers[song_name] = cover_data["name"]

        min_plays = (min_freq / 100.0) * total_shows
        filtered_songs = [
            (song, entries) for song, entries in song_dates.items()
            if len(entries) >= min_plays
        ]

        sorted_songs = sorted(filtered_songs, key=lambda item: len(item[1]), reverse=True)

        table_data = []
        for song, entries in sorted_songs:
            is_cover = song in song_covers
            if hide_covers and is_cover:
                continue
                
            last_date_raw, last_show_url = entries[0]
            last_played_dt = datetime.strptime(last_date_raw, "%d-%m-%Y")

            if max_days_since_played > 0:
                days_ago = (today - last_played_dt).days
                if days_ago > max_days_since_played:
                    continue

            table_data.append({
                "Song Title": song,
                "Plays": len(entries),
                "Frequency": f"{(len(entries) / total_shows) * 100:.1f}%",
                "Original Artist": song_covers.get(song, "Official Release"),
                "Last Played": last_played_dt.strftime("%m-%d-%y"),
                "Setlist.fm Link": last_show_url
            })

        df = pd.DataFrame(table_data)
        if max_playlist_songs > 0 and len(df) > max_playlist_songs:
            df = df.head(int(max_playlist_songs))

        st.session_state["df"] = df

        title_prefix = f"📅 {target_year} Most Played Songs" if is_ytd else "📊 Setlist Frequency Table"
        st.subheader(f"{title_prefix} — {current_artist} ({total_shows} Shows Analyzed)")
        
        st.dataframe(
            df,
            column_config={
                "Setlist.fm Link": st.column_config.LinkColumn(
                    "Setlist.fm Link",
                    display_text="View Setlist 🔗"
                )
            },
            use_container_width=True
        )

        st.divider()
        st.subheader("🎧 Export Playlist")

        if "spotify_token" not in st.session_state and not spotify_refresh_token:
            st.warning("Please connect your Spotify account in the sidebar first to enable 1-click export.")
        else:
            if st.button("✨ Create Spotify Playlist Now"):
                with st.spinner("Searching Spotify & creating your playlist..."):
                    try:
                        active_token = None
                        if spotify_refresh_token:
                            try:
                                fresh_token_info = sp_oauth.refresh_access_token(spotify_refresh_token)
                                active_token = fresh_token_info["access_token"]
                                st.session_state["spotify_token"] = active_token
                            except Exception:
                                pass
                        
                        if not active_token:
                            active_token = st.session_state.get("spotify_token")

                        if not active_token:
                            st.error("❌ Could not obtain a valid Spotify access token. Please re-connect in sidebar.")
                        else:
                            sp = spotipy.Spotify(auth=active_token)
                            
                            track_uris = []
                            report_rows = []
                            total_tracks = len(df)

                            for idx, row in df.iterrows():
                                song = row["Song Title"]
                                orig = row["Original Artist"]
                                
                                uri, matched_details, match_method = search_spotify_track(sp, current_artist, song, orig)
                                
                                if uri:
                                    track_uris.append(uri)
                                    status = "✅ Matched"
                                else:
                                    status = "❌ Missed"
                                    
                                report_rows.append({
                                    "Setlist.fm Song": song,
                                    "Status": status,
                                    "Matched Spotify Track": matched_details,
                                    "Match Method": match_method
                                })

                            report_df = pd.DataFrame(report_rows)
                            st.session_state["match_report_df"] = report_df

                            if track_uris:
                                playlist_name = f"{current_artist} {target_year} Tour Prep" if is_ytd else f"{current_artist} Tour Prep ({total_shows} Shows)"
                                playlist = sp.current_user_playlist_create(name=playlist_name, public=True)
                                
                                for i in range(0, len(track_uris), 100):
                                    sp.playlist_add_items(playlist_id=playlist["id"], items=track_uris[i:i+100])

                                st.balloons()
                                st.success(f"🎉 Created '{playlist_name}' with {len(track_uris)} of {total_tracks} tracks!")
                                st.markdown(f"### 👉 [Click Here to Open Your New Spotify Playlist]({playlist['external_urls']['spotify']})")
                            else:
                                st.error("Could not match any of these tracks on Spotify. Check the report below.")

                    except Exception as e:
                        st.error(f"Failed to create playlist: {e}")

        # Render Match Report Expander if available
        if "match_report_df" in st.session_state:
            report_df = st.session_state["match_report_df"]
            matched_count = len(report_df[report_df["Status"] == "✅ Matched"])
            total_count = len(report_df)
            match_pct = (matched_count / total_count * 100) if total_count > 0 else 0

            with st.expander(f"📋 View Track Matching Report ({matched_count}/{total_count} Matched — {match_pct:.0f}%)"):
                st.dataframe(report_df, use_container_width=True)
