"""'Saw them before they were big': support acts you caught early. Pure pandas, no Streamlit.

setlist.fm doesn't label openers, so at any concert with 2+ acts the act with the most
songs is treated as the headliner and everyone else as support. Nights where the top
song count is tied (or zero) are skipped because the order can't be told.
"""
import pandas as pd

SKIP_ARTISTS = {"various artists"}
COLUMNS = ["Artist", "Opened For", "Date", "Venue", "Later Headlined", "Shows Before",
           "Shows Since", "Glow-up"]


def _key(name) -> str:
    return " ".join(str(name).lower().split())


def _roles(df_att: pd.DataFrame) -> pd.DataFrame:
    """One row per artist per concert with role 'headliner' or 'support' (ambiguous nights dropped)."""
    if df_att is None or df_att.empty:
        return pd.DataFrame(columns=["artist", "artist_mbid", "eventDate_dt", "venue", "role", "headliner"])
    d = df_att.dropna(subset=["eventDate_dt"]).copy()
    d = d[~d["artist"].map(_key).isin(SKIP_ARTISTS)]
    if "artist_mbid" not in d.columns:
        d["artist_mbid"] = None
    d["songs_n"] = pd.to_numeric(d["song_count"], errors="coerce").fillna(0)
    rows = []
    for (dt, venue), g in d.groupby(["eventDate_dt", "venue"]):
        g = g.drop_duplicates(subset=["artist"])
        if len(g) == 1:
            r = g.iloc[0]
            rows.append((r["artist"], r["artist_mbid"], dt, venue, "headliner", r["artist"]))
            continue
        top = g["songs_n"].max()
        leaders = g[g["songs_n"] == top]
        if top <= 0 or len(leaders) > 1:
            continue  # can't tell who headlined
        head = leaders.iloc[0]["artist"]
        for r in g.itertuples():
            rows.append((r.artist, r.artist_mbid, dt, venue,
                         "headliner" if r.artist == head else "support", head))
    return pd.DataFrame(rows, columns=["artist", "artist_mbid", "eventDate_dt", "venue", "role", "headliner"])


def find_early_sightings(df_att: pd.DataFrame) -> pd.DataFrame:
    """Each artist's first support set you saw, plus the first time you later saw them headline."""
    roles = _roles(df_att)
    cols = ["artist", "artist_mbid", "eventDate_dt", "venue", "opened_for",
            "headline_dt", "headline_venue"]
    support = roles[roles["role"] == "support"].sort_values("eventDate_dt")
    if support.empty:
        return pd.DataFrame(columns=cols)
    first = support.drop_duplicates(subset=["artist"], keep="first")
    heads = roles[roles["role"] == "headliner"]
    out = []
    for r in first.itertuples():
        later = heads[(heads["artist"] == r.artist) & (heads["eventDate_dt"] > r.eventDate_dt)]
        later = later.sort_values("eventDate_dt")
        h = later.iloc[0] if not later.empty else None
        out.append((r.artist, r.artist_mbid, r.eventDate_dt, r.venue, r.headliner,
                    h["eventDate_dt"] if h is not None else pd.NaT,
                    h["venue"] if h is not None else None))
    return pd.DataFrame(out, columns=cols)


def position_plan(sightings: pd.DataFrame) -> list:
    """(artist, mbid, date) for each early sighting that can be looked up on setlist.fm."""
    return [(r.artist, r.artist_mbid, r.eventDate_dt) for r in sightings.itertuples()
            if isinstance(r.artist_mbid, str) and r.artist_mbid]


def position_key(mbid, when) -> tuple:
    return (mbid, pd.Timestamp(when).strftime("%Y-%m-%d"))


def early_fan_table(sightings: pd.DataFrame, positions=None) -> pd.DataFrame:
    """The display table, biggest glow-ups first.

    positions: position_key(mbid, date) -> {"before", "since"}: shows the artist had logged on
    setlist.fm before the night you saw them, and since. Glow-up = since / before.
    Ranking: biggest glow-up first (being at their first-ever logged show beats everything),
    then acts you later saw headline, then the most recent sightings.
    """
    if sightings is None or sightings.empty:
        return pd.DataFrame(columns=COLUMNS)
    positions = positions or {}
    rows = []
    for r in sightings.itertuples():
        pos = positions.get(position_key(r.artist_mbid, r.eventDate_dt)) if r.artist_mbid else None
        before = since = None
        label, g = "", -1.0
        if pos:
            before, since = int(pos["before"]), int(pos["since"])
            if before == 0:
                label, g = "Their first logged show!", float("inf")
            else:
                g = since / before
                label = f"×{g:.1f}"
        later = f"{r.headline_venue} ({r.headline_dt:%b %Y})" if pd.notna(r.headline_dt) else ""
        rows.append({"Artist": r.artist, "Opened For": r.opened_for, "Date": f"{r.eventDate_dt:%b %d, %Y}",
                     "Venue": r.venue, "Later Headlined": later, "Shows Before": before,
                     "Shows Since": since, "Glow-up": label,
                     "_g": g, "_h": 1 if later else 0, "_dt": r.eventDate_dt})
    df = pd.DataFrame(rows).sort_values(["_g", "_h", "_dt"], ascending=[False, False, False])
    df = df[COLUMNS].reset_index(drop=True)
    for col in ("Shows Before", "Shows Since"):
        df[col] = pd.array(df[col].tolist(), dtype="Int64")
    return df
