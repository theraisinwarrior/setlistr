"""'Haven't heard it live yet': mark Builder songs you've already heard an artist play. Pure pandas."""
import json

import pandas as pd

from analytics.deep_cuts import song_key

MODES = {
    "Show all songs": "all",
    "Songs I haven't heard live first": "unheard_first",
    "Only songs I haven't heard live": "unheard_only",
}


def _norm(value) -> str:
    return " ".join(str(value).lower().split()) if pd.notna(value) else ""


def heard_song_keys(df_att: pd.DataFrame, artist_name: str, artist_mbid=None):
    """(set of song keys you've heard this artist play, number of their shows you've seen)."""
    if df_att is None or df_att.empty or "songs" not in df_att.columns:
        return set(), 0
    mask = df_att["artist"].map(_norm) == _norm(artist_name)
    if artist_mbid and "artist_mbid" in df_att.columns:
        mask = mask | (df_att["artist_mbid"] == artist_mbid)
    rows = df_att[mask]
    keys = set()
    for raw in rows["songs"]:
        try:
            items = json.loads(raw) if pd.notna(raw) else []
        except (ValueError, TypeError):
            continue
        keys.update(song_key(s) for s in items if isinstance(s, str) and song_key(s))
    return keys, int(rows["eventDate_dt"].dt.normalize().nunique()) if not rows.empty else 0


def apply_heard_mode(df: pd.DataFrame, heard: set, mode: str = "all", max_len: int = 0) -> pd.DataFrame:
    """Add a 'Heard Live' column, reorder or filter by mode, then cut to max_len (0 = no limit)."""
    if df is None or df.empty:
        return df
    out = df.copy()
    is_heard = out["Song Title"].map(lambda s: song_key(s) in heard)
    out.insert(1, "Heard Live", is_heard.map({True: "✅ Heard", False: "🆕 Not yet"}))
    if mode == "unheard_first":
        out = out.assign(_h=is_heard.values).sort_values("_h", kind="stable").drop(columns="_h")
    elif mode == "unheard_only":
        out = out[~is_heard.values]
    out = out.reset_index(drop=True)
    if max_len and len(out) > max_len:
        out = out.head(int(max_len))
    return out
