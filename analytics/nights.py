"""'Relive a night': turn one attended concert into an ordered tracklist. Pure pandas."""
import json

import pandas as pd


def _songs(raw) -> list:
    try:
        items = json.loads(raw) if pd.notna(raw) else []
    except (ValueError, TypeError):
        return []
    return [s.strip() for s in items if isinstance(s, str) and s.strip()]


def _covers(raw) -> dict:
    try:
        items = json.loads(raw) if pd.notna(raw) else []
    except (ValueError, TypeError):
        return {}
    return {c.get("song"): c.get("original") for c in items if isinstance(c, dict) and c.get("song")}


def _night_rows(df_att: pd.DataFrame) -> pd.DataFrame:
    d = df_att.dropna(subset=["eventDate_dt"]).copy()
    d["n_songs"] = d["songs"].map(lambda r: len(_songs(r))) if "songs" in d.columns else 0
    return d


def night_options(df_att: pd.DataFrame) -> list:
    """Concerts with at least one known song, newest first: [{label, day, venue}]."""
    if df_att is None or df_att.empty or "songs" not in df_att.columns:
        return []
    d = _night_rows(df_att)
    out = []
    for (day, venue), g in d.groupby(["eventDate_dt", "venue"]):
        if g["n_songs"].sum() == 0:
            continue
        acts = g.sort_values("n_songs", ascending=False)["artist"].drop_duplicates().tolist()
        lineup = acts[0] + (f" + {len(acts) - 1} more" if len(acts) > 2 else
                            f" + {acts[1]}" if len(acts) == 2 else "")
        out.append({"label": f"{day:%b %d, %Y} · {lineup} · {venue}", "day": day, "venue": venue,
                    "headliner": acts[0]})
    return sorted(out, key=lambda o: o["day"], reverse=True)


def night_tracklist(df_att: pd.DataFrame, day, venue, include_openers: bool = True) -> pd.DataFrame:
    """Ordered songs for one night: openers first (fewest songs), headliner last."""
    d = _night_rows(df_att)
    g = d[(d["eventDate_dt"] == day) & (d["venue"] == venue)]
    g = g.drop_duplicates(subset=["artist"]).sort_values("n_songs")
    if not include_openers and len(g) > 1:
        g = g.tail(1)
    rows = []
    for r in g.itertuples():
        covers = _covers(getattr(r, "covers", None))
        for song in dict.fromkeys(_songs(r.songs)):
            rows.append({"Song": song, "Artist": r.artist, "Original": covers.get(song, "")})
    df = pd.DataFrame(rows, columns=["Song", "Artist", "Original"])
    df.insert(0, "#", range(1, len(df) + 1))
    return df


def night_playlist_name(headliner: str, venue: str, day) -> str:
    return f"{headliner} · {venue} · {day:%b %d, %Y}"
