"""Rank the artists you've seen by how big they are. Pure pandas, no Streamlit."""
import pandas as pd

COLUMNS = ["Artist", "Shows Tracked", "Times Seen", "Last Seen"]


def artists_to_scan(df_att: pd.DataFrame) -> list:
    """Unique (artist, mbid) pairs that can be looked up."""
    if "artist_mbid" not in df_att.columns:
        return []
    d = df_att.dropna(subset=["artist_mbid"]).drop_duplicates(subset=["artist", "artist_mbid"])
    return [(r.artist, r.artist_mbid) for r in d.itertuples()]


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
