"""'Saw them before they were big': support acts you caught early. Pure pandas, no Streamlit.

setlist.fm doesn't label openers, so at any concert with 2+ acts the act with the most
songs is treated as the headliner and everyone else as support. Nights where the top
song count is tied (or zero) are skipped because the order can't be told.
"""
import pandas as pd

SKIP_ARTISTS = {"various artists"}
COLUMNS = ["Artist", "Opened For", "Date", "Venue", "Later Headlined", "Shows Logged",
           "Shows That Year", "Shows Last Year", "Growth"]


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


def growth_plan(sightings: pd.DataFrame, this_year: int) -> list:
    """(artist, mbid, year) lookups needed: the year you saw them and last year.

    Artists seen in the last two years are skipped since there's no 'later' to compare yet.
    """
    plan, seen = [], set()
    last_year = this_year - 1
    for r in sightings.itertuples():
        if pd.isna(r.artist_mbid) or not r.artist_mbid or r.eventDate_dt.year >= last_year:
            continue
        for y in (r.eventDate_dt.year, last_year):
            if (r.artist_mbid, y) not in seen:
                seen.add((r.artist_mbid, y))
                plan.append((r.artist, r.artist_mbid, y))
    return plan


def early_fan_table(sightings: pd.DataFrame, show_counts=None, year_counts=None,
                    this_year=None) -> pd.DataFrame:
    """The display table, best 'glow-ups' first.

    show_counts: artist name -> total concerts logged on setlist.fm (from the popularity scan).
    year_counts: (mbid, year) -> concerts logged that year (from the growth scan).
    Ranking: biggest growth first when growth is known, then acts you later saw headline,
    then the most recent sightings. (Today's size alone isn't used for ranking, since a
    legend who opened for another legend wasn't 'before they were big'.)
    """
    if sightings is None or sightings.empty:
        return pd.DataFrame(columns=COLUMNS)
    show_counts = {_key(k): v for k, v in (show_counts or {}).items()}
    year_counts = year_counts or {}
    last_year = (this_year - 1) if this_year else None
    rows = []
    for r in sightings.itertuples():
        then = now = growth = None
        if last_year and r.artist_mbid and r.eventDate_dt.year < last_year:
            then = year_counts.get((r.artist_mbid, r.eventDate_dt.year))
            now = year_counts.get((r.artist_mbid, last_year))
            if then is not None and now is not None and then > 0:
                growth = now / then
        later = ""
        if pd.notna(r.headline_dt):
            later = f"{r.headline_venue} ({r.headline_dt:%b %Y})"
        logged = show_counts.get(_key(r.artist))
        rows.append({
            "Artist": r.artist, "Opened For": r.opened_for, "Date": f"{r.eventDate_dt:%b %d, %Y}",
            "Venue": r.venue, "Later Headlined": later,
            "Shows Logged": int(logged) if logged is not None else None,
            "Shows That Year": then, "Shows Last Year": now,
            "Growth": f"×{growth:.1f}" if growth is not None else "",
            "_g": growth if growth is not None else -1, "_h": 1 if later else 0,
            "_s": logged if logged is not None else -1, "_dt": r.eventDate_dt,
        })
    df = pd.DataFrame(rows)
    df = df.sort_values(["_g", "_h", "_dt"], ascending=[False, False, False])
    df = df[COLUMNS].reset_index(drop=True)
    for col in ("Shows Logged", "Shows That Year", "Shows Last Year"):
        df[col] = pd.array(df[col].tolist(), dtype="Int64")
    return df
