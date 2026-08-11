import streamlit as st
import requests
import pandas as pd
from collections import defaultdict
from datetime import datetime, timedelta
import spotipy
from spotipy.oauth2 import SpotifyOAuth

# Page Layout
st.set_page_config(page_title="Tour Setlist Playlist Generator", page_icon="🎵", layout="wide")

st.title("🎵 Tour Setlist Playlist Generator")
st.write("Analyze recent concert setlists from Setlist.fm and automatically build a Spotify prep playlist.")

# ==========================================
# SIDEBAR CONFIGURATION CONTROLS
# ==========================================
st.sidebar.header("1. Artist Settings")
artist_name = st.sidebar.text_input("Artist Name", "Foo Fighters")
artist_mbid = st.sidebar.text_input(
    "Setlist.fm MusicBrainz ID (MBID)", 
    "67f66c07-6e61-4026-ade5-7e782fad3a5d",
    help="Find MBID on MusicBrainz.org or Setlist.fm artist page URL"
)

st.sidebar.header("2. Show Filters")
filter_mode = st.sidebar.selectbox("Filter Mode", ["DAYS", "SHOWS", "BOTH"])
days_lookback = st.sidebar.slider("Days Lookback", 7, 180, 30)
max_shows = st.sidebar.slider("Max Shows to Fetch", 1, 50, 15)
min_songs = st.sidebar.slider("Min Songs Per Show (ignores short sets)", 5, 25, 10)

st.sidebar.header("3. Track Filters")
min_freq = st.sidebar.slider("Min Play Frequency (%)", 0, 100, 20)
hide_covers = st.sidebar.checkbox("Exclude Cover Songs", value=False)
max_playlist_songs = st.sidebar.number_input("Max Playlist Length (0 = Unlimited)", min_value=0, value=25)

# API Keys (Loaded from Streamlit Secrets or User Input)
setlist_api_key = st.secrets.get("SETLIST_API_KEY", "")
if not setlist_api_key:
    setlist_api_key = st.sidebar.text_input("Setlist.fm API Key", type="password")

spotify_client_id = st.secrets.get("SPOTIPY_CLIENT_ID", "")
if not spotify_client_id:
    spotify_client_id = st.sidebar.text_input("Spotify Client ID", type="password")

spotify_client_secret = st.secrets.get("SPOTIPY_CLIENT_SECRET", "")
if not spotify_client_secret:
    spotify_client_secret = st.sidebar.text_input("Spotify Client Secret", type="password")

# ==========================================
# MAIN APPLICATION EXECUTION
# ==========================================
if st.button("🚀 Fetch Setlists & Generate Data"):
    if not setlist_api_key:
        st.error("Please provide a Setlist.fm API key in Secrets or Sidebar.")
    else:
        with st.spinner("Fetching setlists from Setlist.fm..."):
            today = datetime.now()
            cutoff_date = today - timedelta(days=days_lookback) if filter_mode in ["DAYS", "BOTH"] else None
            headers = {"x-api-key": setlist_api_key, "Accept": "application/json"}
            
            fetched_setlists = []
            page = 1
            stop_fetching = False

            while not stop_fetching:
                url = f"https://api.setlist.fm/rest/1.0/artist/{artist_mbid}/setlists?p={page}"
                response = requests.get(url, headers=headers)
                if response.status_code != 200:
                    st.error(f"Setlist.fm API Error HTTP {response.status_code}. Check API key and MBID.")
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
                st.warning("No matching full shows found for these criteria.")
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
                    df = df.head(max_playlist_songs)

                st.session_state["df"] = df
                st.session_state["total_shows"] = total_shows
                st.success(f"Successfully processed {total_shows} show(s) and found {len(df)} qualifying song(s)!")

# Display Table & Spotify Generator if Data Exists
if "df" in st.session_state and not st.session_state["df"].empty:
    df = st.session_state["df"]
    total_shows = st.session_state["total_shows"]
    
    st.subheader("📊 Setlist Frequency Table")
    st.dataframe(df, use_container_width=True)

    st.divider()
    st.subheader("🎧 Create Spotify Playlist")

    if st.button("✨ Export Playlist to Spotify"):
        if not spotify_client_id or not spotify_client_secret:
            st.error("Please provide Spotify Client ID & Secret in Secrets or Sidebar.")
        else:
            with st.spinner("Connecting to Spotify & building playlist..."):
                try:
                    # Web OAuth Callback setup
                    redirect_uri = "https://share.streamlit.io/"  # Updated during Streamlit Cloud deployment
                    
                    sp = spotipy.Spotify(auth_manager=SpotifyOAuth(
                        client_id=spotify_client_id,
                        client_secret=spotify_client_secret,
                        redirect_uri=redirect_uri,
                        scope="playlist-modify-public playlist-modify-private"
                    ))

                    playlist_name = f"{artist_name} Tour Prep ({total_shows} Shows)"
                    playlist = sp.current_user_playlist_create(name=playlist_name, public=True)

                    track_uris = []
                    for idx, row in df.iterrows():
                        song = row["Song Title"]
                        orig = row["Original Artist"]
                        
                        # Search logic
                        query = f'artist:"{artist_name}" track:"{song}"'
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
                        st.markdown(f"### 🎉 [Click Here to Open Your New Spotify Playlist]({playlist['external_urls']['spotify']})")
                    else:
                        st.warning("Could not match any of the tracks on Spotify.")
                        
                except Exception as e:
                    st.error(f"Spotify Export Error: {e}")
