"""Rank the artists you've seen by how big they are. Pure pandas, no Streamlit."""
import pandas as pd

COLUMNS = ["Artist", "Shows Tracked", "Times Seen", "Last Seen"]


def artists_to_scan(df_att: pd.DataFrame) -> list:
    """Unique (artist, mbid) pairs that can be looked up."""
    if "artist_mbid" not in df_att.columns:
        return []
    d = df_att.dropna(subset=["artist_mbid"]).drop_duplicates(subset=["artist", "artist_mbid"])
    return [(r.artist, r.artist_mbid) for r in d.itertuples()]


SHOW_COLUMNS = ["Date", "Artist", "Venue", "City", "Users There"]


def shows_to_scan(df_att: pd.DataFrame) -> list:
    """(artist, venue, url) for every attended show that has a setlist.fm page."""
    if "url" not in df_att.columns:
        return []
    d = df_att[df_att["url"].fillna("").astype(str).str.startswith("http")]
    d = d.drop_duplicates(subset=["url"])
    return [(r.artist, r.venue, r.url) for r in d.itertuples()]


def rank_shows_by_attendance(df_att: pd.DataFrame, counts: dict) -> pd.DataFrame:
    """One row per show with a known count, most attended first.

    `counts` maps setlist url -> number of setlist.fm users who marked "I was there".
    """
    if "url" not in df_att.columns or not counts:
        return pd.DataFrame(columns=SHOW_COLUMNS)
    d = df_att.drop_duplicates(subset=["url"])
    rows = []
    for r in d.itertuples():
        n = counts.get(r.url)
        if n is None:
            continue
        rows.append({"Date": r.Date, "Artist": r.artist, "Venue": r.venue, "City": r.city,
                     "Users There": int(n), "_dt": r.eventDate_dt})
    if not rows:
        return pd.DataFrame(columns=SHOW_COLUMNS)
    df = pd.DataFrame(rows)
    df = df.sort_values(["Users There", "_dt"], ascending=[False, False]).reset_index(drop=True)
    return df[SHOW_COLUMNS]


def rank_artists_by_popularity(df_att: pd.DataFrame, counts: dict) -> pd.DataFrame:
    """One row per artist, biggest first.

    `counts` maps artist mbid -> number of that artist's concerts logged on setlist.fm.
    Artists missing from `counts` are left out.
    """
    if "artist_mbid" not in df_att.columns or not counts:
        return pd.DataFrame(columns=COLUMNS)

    rows = []
    for (artist, mbid), g in df_att.dropna(subset=["artist_mbid"]).groupby(["artist", "artist_mbid"]):
        if mbid not in counts:
            continue
        last = g["eventDate_dt"].max()
        rows.append({
            "Artist": artist,
            "Shows Tracked": int(counts[mbid]),
            "Times Seen": int(g["eventDate_dt"].nunique()),
            "Last Seen": f"{last:%b %d, %Y}" if pd.notna(last) else "",
        })

    df = pd.DataFrame(rows, columns=COLUMNS)
    return df.sort_values(["Shows Tracked", "Artist"], ascending=[False, True]).reset_index(drop=True)
