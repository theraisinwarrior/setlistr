"""Data access. Phase 1: reads attended_shows.csv. Phase 2: swap for Supabase/setlist.fm sync."""
import json

import pandas as pd
import streamlit as st

ATTENDANCE_CSV = "attended_shows.csv"


@st.cache_data
def load_attendance():
    """Return (df_att, df_concerts, df_songs). Raises FileNotFoundError if the CSV is missing."""
    df_att = pd.read_csv(ATTENDANCE_CSV)

    df_att['eventDate_dt'] = pd.to_datetime(df_att['eventDate'], errors='coerce')
    df_att['Date'] = df_att['eventDate_dt'].dt.strftime('%m-%d-%Y')
    df_att['year'] = df_att['eventDate_dt'].dt.year
    df_att['lat'] = pd.to_numeric(df_att['lat'], errors='coerce')
    df_att['long'] = pd.to_numeric(df_att['long'], errors='coerce')

    # Deduplicate same-day setlists at the same venue for high-level statistics
    df_concerts = df_att.groupby(
        ['eventDate_dt', 'Date', 'venue', 'city', 'state', 'lat', 'long', 'year'],
        as_index=False
    ).agg({
        'artist': lambda x: ", ".join(dict.fromkeys(x)),  # Headliners + Openers
        'song_count': 'sum',
        'tour': lambda x: next((str(t) for t in x if pd.notna(t) and str(t).strip() not in ['None', '']), 'N/A'),
        'url': 'first'
    }).sort_values('eventDate_dt', ascending=False)

    # Individual song names from the JSON column (deduplicated per show)
    all_songs = []
    for _, row in df_att.iterrows():
        song_json = row.get('songs')
        if pd.notna(song_json):
            try:
                s_list = json.loads(song_json)
                unique = list(dict.fromkeys(
                    [s.strip() for s in s_list if s and isinstance(s, str) and s.strip()]))
                for s in unique:
                    all_songs.append({
                        'song': s,
                        'artist': row['artist'],
                        'venue': row['venue'],
                        'Date': row['Date'],
                        'track_artist': f"{s} — {row['artist']}",
                    })
            except Exception:
                pass

    df_songs = (pd.DataFrame(all_songs) if all_songs
                else pd.DataFrame(columns=['song', 'artist', 'venue', 'Date', 'track_artist']))

    return df_att, df_concerts, df_songs
