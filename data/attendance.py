"""Pure data conversion for attended shows (pandas only, no Streamlit)."""
import json

import pandas as pd

RAW_COLUMNS = ["eventDate", "artist", "artist_mbid", "venue", "city", "state", "lat", "long",
               "song_count", "tour", "url", "songs"]


def _norm(value) -> str:
    return " ".join(str(value).lower().split()) if pd.notna(value) else ""


def apply_venue_overrides(df_raw: pd.DataFrame, overrides: pd.DataFrame):
    """Replace setlist.fm's city-level coordinates with hand-corrected venue coordinates.

    `overrides` needs columns venue, lat, long (and optionally city). Rows earlier in
    `overrides` win. Matching tries venue + city first, then venue name alone.

    Returns (updated_df, needs_coords) where needs_coords lists venues that had no
    override, so they still sit on setlist.fm's city-level point.
    """
    df = df_raw.copy()
    if df.empty:
        return df, pd.DataFrame(columns=["venue", "city", "state", "shows"])

    by_venue_city, by_venue = {}, {}
    if overrides is not None and not overrides.empty:
        for _, r in overrides.iterrows():
            lat = pd.to_numeric(r.get("lat"), errors="coerce")
            lon = pd.to_numeric(r.get("long"), errors="coerce")
            if pd.isna(lat) or pd.isna(lon):
                continue
            v = _norm(r.get("venue"))
            by_venue_city.setdefault((v, _norm(r.get("city"))), (lat, lon))
            by_venue.setdefault(v, (lat, lon))

    matched = []
    for i, row in df.iterrows():
        v = _norm(row["venue"])
        hit = by_venue_city.get((v, _norm(row["city"]))) or by_venue.get(v)
        if hit:
            df.at[i, "lat"], df.at[i, "long"] = hit
        matched.append(bool(hit))

    df["_matched"] = matched
    missing = (df[~df["_matched"]]
               .groupby(["venue", "city", "state"], as_index=False).size()
               .rename(columns={"size": "shows"})
               .sort_values("shows", ascending=False))
    df = df.drop(columns="_matched")
    return df, missing


def setlists_to_dataframe(setlists: list) -> pd.DataFrame:
    """Turn setlist.fm API setlist objects into the table the Passport uses."""
    rows = []
    for sl in setlists:
        venue = sl.get("venue") or {}
        city = venue.get("city") or {}
        coords = city.get("coords") or {}
        country = city.get("country") or {}

        songs = []
        for s in (sl.get("sets") or {}).get("set", []):
            for song in s.get("song", []):
                name = song.get("name")
                if name and not song.get("tape", False):
                    songs.append(name)

        raw_date = sl.get("eventDate", "")  # setlist.fm uses dd-MM-yyyy
        event_date = pd.to_datetime(raw_date, format="%d-%m-%Y", errors="coerce")

        rows.append({
            "eventDate": event_date.strftime("%Y-%m-%d") if pd.notna(event_date) else None,
            "artist": (sl.get("artist") or {}).get("name", "Unknown"),
            "artist_mbid": (sl.get("artist") or {}).get("mbid"),
            "venue": venue.get("name", "Unknown venue"),
            "city": city.get("name", ""),
            "state": city.get("stateCode") or country.get("code") or "",
            "lat": coords.get("lat"),
            "long": coords.get("long"),
            "song_count": len(songs),
            "tour": (sl.get("tour") or {}).get("name"),
            "url": sl.get("url", ""),
            "songs": json.dumps(songs),
        })

    return pd.DataFrame(rows, columns=RAW_COLUMNS)


def process_attendance(df_raw: pd.DataFrame):
    """Return (df_att, df_concerts, df_songs) from the raw attendance table."""
    df_att = df_raw.copy()

    df_att['eventDate_dt'] = pd.to_datetime(df_att['eventDate'], errors='coerce')
    df_att['Date'] = df_att['eventDate_dt'].dt.strftime('%m-%d-%Y')
    df_att['year'] = df_att['eventDate_dt'].dt.year
    df_att['lat'] = pd.to_numeric(df_att['lat'], errors='coerce')
    df_att['long'] = pd.to_numeric(df_att['long'], errors='coerce')

    # Deduplicate same-day setlists at the same venue for high-level statistics.
    # dropna=False keeps shows that have no coordinates.
    df_concerts = df_att.groupby(
        ['eventDate_dt', 'Date', 'venue', 'city', 'state', 'lat', 'long', 'year'],
        as_index=False, dropna=False,
    ).agg({
        'artist': lambda x: ", ".join(dict.fromkeys(x)),  # Headliners + Openers
        'song_count': 'sum',
        'tour': lambda x: next((str(t) for t in x if pd.notna(t) and str(t).strip() not in ['None', '']), 'N/A'),
        'url': 'first',
    }).sort_values('eventDate_dt', ascending=False)

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
