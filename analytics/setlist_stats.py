"""Pure functions that turn raw setlist.fm data into the Builder's song table."""
from collections import defaultdict
from datetime import datetime, timedelta

import pandas as pd


def filter_shows(raw_setlists, filter_mode, days_lookback, min_songs, max_shows,
                 is_ytd, target_year, today=None):
    today = today or datetime.now()
    cutoff_date = today - timedelta(days=int(days_lookback)) if filter_mode in ["DAYS", "BOTH"] else None

    filtered = []
    for show in raw_setlists:
        event_date_raw = show.get("eventDate")
        if not event_date_raw:
            continue
        show_dt = datetime.strptime(event_date_raw, "%d-%m-%Y")

        if is_ytd:
            if show_dt.year != target_year:
                continue
        elif cutoff_date and show_dt < cutoff_date:
            continue

        sets = show.get("sets", {}).get("set", [])
        song_count = sum(len(s.get("song", [])) for s in sets)

        if song_count >= min_songs:
            filtered.append(show)
            if not is_ytd and filter_mode in ["SHOWS", "BOTH"] and len(filtered) == max_shows:
                break

    return filtered


def build_song_table(filtered_shows, hide_tape, hide_covers, min_freq,
                     max_days_since_played, max_playlist_songs, today=None):
    today = today or datetime.now()
    total_shows = len(filtered_shows)

    song_dates = defaultdict(list)
    song_covers = {}

    for show in filtered_shows:
        event_date = show.get("eventDate")
        show_url = show.get("url", "")
        for s in show.get("sets", {}).get("set", []):
            for song in s.get("song", []):
                if hide_tape and song.get("tape", False):
                    continue
                song_name = song.get("name")
                if song_name:
                    song_dates[song_name].append((event_date, show_url))
                    cover_data = song.get("cover")
                    if cover_data and "name" in cover_data:
                        song_covers[song_name] = cover_data["name"]

    min_plays = (min_freq / 100.0) * total_shows
    filtered_songs = [(s, e) for s, e in song_dates.items() if len(e) >= min_plays]
    sorted_songs = sorted(filtered_songs, key=lambda item: len(item[1]), reverse=True)

    rows = []
    for song, entries in sorted_songs:
        if hide_covers and song in song_covers:
            continue

        last_date_raw, last_show_url = entries[0]
        last_played_dt = datetime.strptime(last_date_raw, "%d-%m-%Y")

        if max_days_since_played > 0 and (today - last_played_dt).days > max_days_since_played:
            continue

        rows.append({
            "Song Title": song,
            "Plays": len(entries),
            "Frequency": f"{(len(entries) / total_shows) * 100:.1f}%",
            "Original Artist": song_covers.get(song, "Official Release"),
            "Last Played": last_played_dt.strftime("%m-%d-%y"),
            "Setlist.fm Link": last_show_url,
        })

    df = pd.DataFrame(rows)
    if max_playlist_songs > 0 and len(df) > max_playlist_songs:
        df = df.head(int(max_playlist_songs))
    return df
