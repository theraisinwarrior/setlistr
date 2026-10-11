"""Playlist Builder: analyze recent setlists and export a Spotify prep playlist."""
from datetime import datetime

import pandas as pd
import spotipy
import streamlit as st

from analytics.setlist_stats import build_song_table, filter_shows
from services.auth import (get_active_token, get_authorize_url, get_setlist_api_key,
                           is_spotify_connected)
from services.setlistfm import fetch_setlists, get_mbid_from_name
from services.spotify_match import search_spotify_track

st.title("🎵 Tour Setlist Playlist Generator")
st.write("Analyze recent concert setlists from Setlist.fm and automatically build a Spotify prep playlist.")

CURRENT_YEAR = datetime.now().year
YEAR_OPTIONS = list(range(CURRENT_YEAR, 1999, -1))

setlist_api_key = get_setlist_api_key()

# ------------------------------------------
# Filter presets
# ------------------------------------------
BASE_PRESETS = {
    "Custom (Manual Toggles)": None,
    "🎯 Standard Tour Prep": {
        "filter_mode": "SHOWS", "max_shows": 15, "days_lookback": 120, "min_songs": 8,
        "min_freq": 20, "max_days_since_played": 0, "hide_covers": False,
        "hide_tape": True, "max_playlist_songs": 25,
    },
    "⚡ Core Staples Only": {
        "filter_mode": "SHOWS", "max_shows": 20, "days_lookback": 180, "min_songs": 8,
        "min_freq": 50, "max_days_since_played": 0, "hide_covers": False,
        "hide_tape": True, "max_playlist_songs": 20,
    },
    "⏳ Recent 90 Days": {
        "filter_mode": "DAYS", "days_lookback": 90, "max_shows": 20, "min_songs": 5,
        "min_freq": 15, "max_days_since_played": 90, "hide_covers": False,
        "hide_tape": True, "max_playlist_songs": 25,
    },
    "🎵 Deep Cuts & Full History": {
        "filter_mode": "SHOWS", "max_shows": 30, "days_lookback": 365, "min_songs": 3,
        "min_freq": 0, "max_days_since_played": 0, "hide_covers": False,
        "hide_tape": True, "max_playlist_songs": 0,
    },
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
            ("days", "days_lookback"), ("shows", "max_shows"), ("songs", "min_songs"),
            ("freq", "min_freq"), ("recency", "max_days_since_played"),
            ("maxp", "max_playlist_songs"),
        ]:
            val = p.get(key, 0)
            st.session_state[f"{prefix}_slider"] = val
            st.session_state[f"{prefix}_num"] = val


def linked_numeric_input(label, min_v, max_v, default_v, key_prefix, step=1):
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
        st.slider(label, min_value=min_v, max_value=max_v, key=slider_key,
                  on_change=sync_from_slider, step=step, label_visibility="collapsed")
    with c2:
        st.number_input(label, min_value=min_v, max_value=max_v, key=num_key,
                        on_change=sync_from_num, step=step, label_visibility="collapsed")
    return st.session_state[slider_key]


# ------------------------------------------
# Sidebar controls
# ------------------------------------------
st.sidebar.header("2. Artist & Show Filters")

artist_name_input = st.sidebar.text_input("Artist Name", "Taylor Swift")

if "filter_mode_key" not in st.session_state:
    st.session_state["filter_mode_key"] = "SHOWS"
if "hide_covers_key" not in st.session_state:
    st.session_state["hide_covers_key"] = False
if "hide_tape_key" not in st.session_state:
    st.session_state["hide_tape_key"] = True

filter_mode = st.sidebar.selectbox("Filter Mode", ["SHOWS", "DAYS", "BOTH"], key="filter_mode_key")

st.sidebar.selectbox("Filter Presets", list(get_all_presets().keys()),
                     key="preset_choice", on_change=apply_preset)

with st.sidebar.expander("💾 Save Current Toggles as Preset"):
    new_preset_name = st.text_input("Preset Name", placeholder="e.g. Festival Sets",
                                    key="new_preset_name_input")
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
                "max_playlist_songs": st.session_state.get("maxp_slider", 30),
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
max_days_since_played = linked_numeric_input(
    "Played Within Last X Days (0 = Disabled)", 0, 365, 0, "recency", step=5)
hide_covers = st.sidebar.checkbox("Exclude Cover Songs", key="hide_covers_key")
hide_tape = st.sidebar.checkbox("Exclude Tape Playbacks (PA/Intros)", key="hide_tape_key")
max_playlist_songs = linked_numeric_input(
    "Max Playlist Length (0 = Unlimited)", 0, 100, 30, "maxp")

# ------------------------------------------
# Fetch actions
# ------------------------------------------
btn_col1, btn_col2, btn_col3 = st.columns([2, 2, 1])

with btn_col3:
    selected_year = st.selectbox("Year", YEAR_OPTIONS, index=0, label_visibility="collapsed")
with btn_col1:
    fetch_clicked = st.button("🚀 Fetch Setlists & Analyze", use_container_width=True)
with btn_col2:
    ytd_clicked = st.button(f"📅 Most Played ({selected_year})", use_container_width=True)

if fetch_clicked or ytd_clicked:
    st.session_state["ytd_mode"] = bool(ytd_clicked)
    st.session_state["target_year"] = selected_year

    if not setlist_api_key:
        st.error("Please provide a Setlist.fm API key in Secrets or Sidebar.")
    else:
        with st.spinner("Finding artist and fetching setlists from Setlist.fm..."):
            artist_mbid, official_artist_name = get_mbid_from_name(artist_name_input, setlist_api_key)

            if not artist_mbid:
                st.error(f"Could not find an artist matching '{artist_name_input}' on Setlist.fm.")
            else:
                is_ytd = st.session_state["ytd_mode"]
                target_year = st.session_state["target_year"]
                fetched = fetch_setlists(artist_mbid, setlist_api_key, max_shows, is_ytd, target_year)

                if not fetched:
                    if is_ytd:
                        st.warning(f"No shows recorded on Setlist.fm for '{official_artist_name}' in {target_year}.")
                    else:
                        st.warning(f"No setlists found for '{official_artist_name}'.")
                else:
                    st.session_state["raw_setlists"] = fetched
                    st.session_state["artist_name"] = official_artist_name

# ------------------------------------------
# Live recalculation & display
# ------------------------------------------
if st.session_state.get("raw_setlists"):
    raw_setlists = st.session_state["raw_setlists"]
    current_artist = st.session_state.get("artist_name", artist_name_input)
    is_ytd = st.session_state.get("ytd_mode", False)
    target_year = st.session_state.get("target_year", CURRENT_YEAR)

    filtered_shows = filter_shows(raw_setlists, filter_mode, days_lookback, min_songs,
                                  max_shows, is_ytd, target_year)
    total_shows = len(filtered_shows)

    if total_shows == 0:
        if is_ytd:
            st.warning(f"No shows recorded on Setlist.fm for '{current_artist}' in {target_year}.")
        else:
            st.warning(f"No matching full shows found for '{current_artist}' with the current filter settings.")
    else:
        df = build_song_table(filtered_shows, hide_tape, hide_covers, min_freq,
                              max_days_since_played, max_playlist_songs)
        st.session_state["df"] = df

        title_prefix = f"📅 {target_year} Most Played Songs" if is_ytd else "📊 Setlist Frequency Table"
        st.subheader(f"{title_prefix} — {current_artist} ({total_shows} Shows Analyzed)")

        st.dataframe(
            df,
            column_config={
                "Setlist.fm Link": st.column_config.LinkColumn(
                    "Setlist.fm Link", display_text="View Setlist 🔗")
            },
            use_container_width=True,
        )

        st.divider()
        st.subheader("🎧 Export Playlist")

        if not is_spotify_connected():
            st.warning("Connect your Spotify account to export this playlist to your library.")
            st.link_button("🎵 Connect Spotify", get_authorize_url())
        elif st.button("✨ Create Spotify Playlist Now"):
            with st.spinner("Searching Spotify & creating your playlist..."):
                try:
                    active_token = get_active_token()
                    if not active_token:
                        st.error("❌ Could not obtain a valid Spotify access token. Please re-connect in sidebar.")
                    else:
                        sp = spotipy.Spotify(auth=active_token)

                        track_uris, report_rows = [], []
                        total_tracks = len(df)

                        for _, row in df.iterrows():
                            song, orig = row["Song Title"], row["Original Artist"]
                            uri, matched_details, match_method = search_spotify_track(
                                sp, current_artist, song, orig)

                            if uri:
                                track_uris.append(uri)
                            report_rows.append({
                                "Setlist.fm Song": song,
                                "Status": "✅ Matched" if uri else "❌ Missed",
                                "Matched Spotify Track": matched_details,
                                "Match Method": match_method,
                            })

                        st.session_state["match_report_df"] = pd.DataFrame(report_rows)

                        if track_uris:
                            playlist_name = (f"{current_artist} {target_year} Tour Prep" if is_ytd
                                             else f"{current_artist} Tour Prep ({total_shows} Shows)")
                            playlist = sp.current_user_playlist_create(name=playlist_name, public=True)

                            for i in range(0, len(track_uris), 100):
                                sp.playlist_add_items(playlist_id=playlist["id"],
                                                      items=track_uris[i:i + 100])

                            st.balloons()
                            st.success(f"🎉 Created '{playlist_name}' with {len(track_uris)} of {total_tracks} tracks!")
                            st.markdown(f"### 👉 [Click Here to Open Your New Spotify Playlist]({playlist['external_urls']['spotify']})")
                        else:
                            st.error("Could not match any of these tracks on Spotify. Check the report below.")

                except Exception as e:
                    st.error(f"Failed to create playlist: {e}")

        if "match_report_df" in st.session_state:
            report_df = st.session_state["match_report_df"]
            matched_count = len(report_df[report_df["Status"] == "✅ Matched"])
            total_count = len(report_df)
            match_pct = (matched_count / total_count * 100) if total_count > 0 else 0

            with st.expander(f"📋 View Track Matching Report ({matched_count}/{total_count} Matched — {match_pct:.0f}%)"):
                st.dataframe(report_df, use_container_width=True)
