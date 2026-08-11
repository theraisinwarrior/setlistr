import streamlit as st
import requests
import pandas as pd
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
REDIRECT_URI = "https://setlistr2.streamlit.app/"

# ==========================================
# SIDEBAR CONFIGURATION & CREDENTIALS
# ==========================================
st.sidebar.header("1. API Credentials")

# Load Secrets or Manual Inputs
setlist_api_key = st.secrets.get("SETLIST_API_KEY", "")
if not setlist_api_key:
    setlist_api_key = st.sidebar.text_input("Setlist.fm API Key", type="password")

spotify_client_id = st.secrets.get("SPOTIPY_CLIENT_ID", "")
if not spotify_client_id:
    spotify_client_id = st.sidebar.text_input("Spotify Client ID", type="password")

spotify_client_secret = st.secrets.get("SPOTIPY_CLIENT_SECRET", "")
if not spotify_client_secret:
    spotify_client_secret = st.sidebar.text_input("Spotify Client Secret", type="password")

st.sidebar.divider()

# ==========================================
# SPOTIFY AUTHENTICATION HANDLER
# ==========================================
# Step A: Handle OAuth Redirect Back from Spotify
if "code" in st.query_params and "spotify_token" not in st.session_state:
    auth_code = st.query_params["code"]
    try:
        sp_oauth = SpotifyOAuth(
            client_id=spotify_client_id,
            client_secret=spotify_client_secret,
            redirect_uri=REDIRECT_URI,
            scope="playlist-modify-public playlist-modify-private"
        )
        token_info = sp_oauth.get_access_token(auth_code)
        st.session_state["spotify_token"] = token_info["access_token"]
        
        # Clear code from URL bar to prevent token-reuse errors
        st.query_params.clear()
        st.rerun()
    except Exception as e:
        st.sidebar.error(f"Spotify Login Error: {e}")

# Step B: Render Login Status in Sidebar
st.sidebar.header("2. Spotify Account")
if "spotify_token" in st.session_state:
    st.sidebar.success("✅ Spotify Connected!")
    if st.sidebar.button("Log Out of Spotify"):
        del st.session_state["spotify_token"]
        st.rerun()
else:
    if spotify_client_id and spotify_client_secret:
        sp_oauth = SpotifyOAuth(
            client_id=spotify_client_id,
            client_secret=spotify_client_secret,
            redirect_uri=REDIRECT_URI,
            scope="playlist-modify-public playlist-modify-private"
        )
        auth_url = sp_oauth.get_authorize_url()
        st.sidebar.info("Connect your Spotify account once to enable 1-click playlist creation.")
        st.sidebar.markdown(f"👉 **[Connect Spotify Account]({auth_url})**")
    else:
        st.sidebar.warning("Enter Spotify Client ID & Secret to enable login.")

st.sidebar.divider()

# ==========================================
# SETLIST & TRACK FILTERS
# ==========================================
st.sidebar.header("3. Artist & Show Filters")
artist_name_input = st.sidebar.text_input("Artist Name", "Jalen Ngonda")

filter_mode = st.sidebar.selectbox("Filter Mode", ["DAYS", "SHOWS", "BOTH"])

days_lookback = st.sidebar.number_input("Days Lookback", min_value=1, max_value=365, value=120, step=1)
max_shows = st.sidebar.number_input("Max Shows to Fetch", min_value=1, max_value=100, value=15, step=1)
min_songs = st.sidebar.number_input("Min Songs Per Show", min_value=1, max_value=50, value=8, step=1)

st.sidebar.header("4. Track Filters")
min_freq = st.sidebar.number_input("Min Play Frequency (%)", min_value=0, max_value=100, value=20, step=5)
hide_covers = st.sidebar.checkbox("Exclude Cover Songs", value=False)
max_playlist_songs = st.sidebar.number_input("Max Playlist Length (0 = Unlimited)", min_value=0, value=25, step=1)


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
            # 1. Priority: Exact name match (case-insensitive)
            for a in artists:
                if a.get("name", "").strip().lower() == clean_query:
                    return a["mbid"], a["name"]
            
            # 2. Priority: First match without "feat" or "with"
            for a in artists:
                name_lower = a.get("name", "").lower()
                if "feat" not in name_lower and "with" not in name_lower:
                    return a["mbid"], a["name"]

            # 3. Fallback to top API result
            return artists[0]["mbid"], artists[0]["name"]
            
    return None, None


# ==========================================
# MAIN ACTION & DATA PROCESSING
# ==========================================
if st.button("🚀 Fetch Setlists & Analyze"):
    if not setlist_api_key:
        st.error("Please provide a Setlist.fm API key in Secrets or Sidebar.")
    else:
        with st.spinner("Finding artist and fetching setlists..."):
            # Smart MBID Resolution
            artist_mbid, official_artist_name = get_mbid_from_name(artist_name_input, setlist_api_key)
            
            if not artist_mbid:
                st.error(f"Could not find an artist matching '{artist_name_input}' on Setlist.fm.")
            else:
                today = datetime.now()
                cutoff_date = today - timedelta(days=int(days_lookback)) if filter_mode in ["DAYS", "BOTH"] else None
                headers = {"x-api-key": setlist_api_key, "Accept": "application/json"}
                
                fetched_setlists = []
                page = 1
                stop_fetching = False

                while not stop_fetching:
                    url = f"https://api.setlist.fm/rest/1.0/artist/{artist_mbid}/setlists?p={page}"
                    response = requests.get(url, headers=headers)
                    if response.status_code != 200:
                        st.error(f"Setlist.fm API Error HTTP {response.status_code}.")
                        break
                        
                    data = response.json()
                    batch = data.get("setlist", [])
                    if not batch:
                        break
                        
                    for show in batch:
                        event_date_raw = show.get("eventDate")
                        if not event_date_raw:
                            continue
                        show_dt = datetime.strptime(event_date_raw, "%d-%m-%Y")
                        
                        if cutoff_date and show_dt < cutoff_date:
                            stop_fetching = True
                            break
                            
                        sets = show.get("sets", {}).get("set", [])
                        song_count = sum(len(s.get("song", [])) for s in sets)
                        
                        if song_count >= min_songs:
                            fetched_setlists.append(show)
                            if filter_mode in ["SHOWS", "BOTH"] and len(fetched_setlists) == max_shows:
                                stop_fetching = True
                                break
                    page += 1

                total_shows = len(fetched_setlists)

                if total_shows == 0:
                    st.warning(f"No matching full shows found for '{official_artist_name}' with these criteria.")
                else:
                    song_dates = defaultdict(list)
                    song_covers = {}

                    for show in fetched_setlists:
                        event_date = show.get("eventDate")
                        sets = show.get("sets", {}).get("set", [])
                        for s in sets:
                            for song in s.get("song", []):
                                song_name = song.get("name")
                                if song_name:
                                    song_dates[song_name].append(event_date)
                                    cover_data = song.get("cover")
                                    if cover_data and "name" in cover_data:
                                        song_covers[song_name] = cover_data["name"]

                    min_plays = (min_freq / 100.0) * total_shows
                    filtered_songs = [
                        (song, dates) for song, dates in song_dates.items()
                        if len(dates) >= min_plays
                    ]

                    sorted_songs = sorted(filtered_songs, key=lambda item: len(item[1]), reverse=True)

                    table_data = []
                    for song, dates in sorted_songs:
                        is_cover = song in song_covers
                        if hide_covers and is_cover:
                            continue
                            
                        table_data.append({
                            "Song Title": song,
                            "Plays": len(dates),
                            "Frequency": f"{(len(dates) / total_shows) * 100:.1f}%",
                            "Original Artist": song_covers.get(song, "Official Release"),
                            "Last Played": datetime.strptime(dates[0], "%d-%m-%Y").strftime("%m-%d-%y")
                        })

                    df = pd.DataFrame(table_data)
                    if max_playlist_songs > 0 and len(df) > max_playlist_songs:
                        df = df.head(int(max_playlist_songs))

                    # Save to session state
                    st.session_state["df"] = df
                    st.session_state["total_shows"] = total_shows
                    st.session_state["artist_name"] = official_artist_name

# ==========================================
# DISPLAY TABLE & EXPORT
# ==========================================
if "df" in st.session_state and not st.session_state["df"].empty:
    df = st.session_state["df"]
    total_shows = st.session_state["total_shows"]
    current_artist = st.session_state.get("artist_name", artist_name_input)

    st.subheader(f"📊 {current_artist} — Setlist Frequency Table ({total_shows} Shows Analyzed)")
    st.dataframe(df, use_container_width=True)

    st.divider()
    st.subheader("🎧 Export Playlist")

    if "spotify_token" not in st.session_state:
        st.warning("Please connect your Spotify account in the sidebar first to enable 1-click export.")
    else:
        if st.button("✨ Create Spotify Playlist Now"):
            with st.spinner("Building playlist on Spotify..."):
                try:
                    sp = spotipy.Spotify(auth=st.session_state["spotify_token"])
                    playlist_name = f"{current_artist} Tour Prep ({total_shows} Shows)"
                    playlist = sp.current_user_playlist_create(name=playlist_name, public=True)

                    track_uris = []
                    for idx, row in df.iterrows():
                        song = row["Song Title"]
                        orig = row["Original Artist"]
                        
                        query = f'artist:"{current_artist}" track:"{song}"'
                        res = sp.search(q=query, type="track", limit=1)
                        items = res.get("tracks", {}).get("items", [])
                        
                        if not items and orig != "Official Release":
                            query_orig = f'artist:"{orig}" track:"{song}"'
                            res = sp.search(q=query_orig, type="track", limit=1)
                            items = res.get("tracks", {}).get("items", [])

                        if items:
                            track_uris.append(items[0]["uri"])

                    if track_uris:
                        sp.playlist_add_items(playlist_id=playlist["id"], items=track_uris)
                        st.balloons()
                        st.success(f"Created '{playlist_name}' with {len(track_uris)} tracks!")
                        st.markdown(f"### 🎉 [Click Here to Open Your New Spotify Playlist]({playlist['external_urls']['spotify']})")
                    else:
                        st.warning("Could not match any tracks on Spotify.")
                except Exception as e:
                    st.error(f"Failed to create playlist: {e}")
