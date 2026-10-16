"""Song rarity across an artist's recent history, and where your show sits in it. Pure Python/pandas.

Works on compact setlist pages from services.setlistfm.compact_setlist_page():
{"total": int, "per_page": int, "shows": [{"date": "dd-mm-yyyy", "songs": [names]}]}, newest first.
"""
import json
import math
from collections import Counter
from datetime import date, datetime

import pandas as pd

from analytics.deep_cuts import song_key

CAREER_PAGES = 10  # 10 pages x 20 setlists = each artist's 200 most recent shows
MIN_LOGGED = 20    # artists with fewer logged shows than this are skipped (every song would look rare)
MIN_SET_SONGS = 3  # setlists with fewer songs (snippets, partial logs) are ignored everywhere
RARE_COLUMNS = ["Song", "Artist", "Heard On", "Venue", "Played In", "Times Played", "Shows Checked",
                "Frequency", "pct", "n"]


def _date(s):
    try:
        return datetime.strptime(str(s), "%d-%m-%Y").date()
    except (TypeError, ValueError):
        return None


def _songs(raw) -> list:
    try:
        items = json.loads(raw) if pd.notna(raw) else []
    except (TypeError, ValueError):
        return []
    return [s.strip() for s in items if isinstance(s, str) and s.strip()]


def career_plan(df_att: pd.DataFrame) -> list:
    """(artist, mbid) for every artist you've heard songs from, most-seen first."""
    if df_att is None or df_att.empty or "artist_mbid" not in df_att.columns:
        return []
    d = df_att.dropna(subset=["artist_mbid"])
    d = d[d["songs"].map(lambda r: len(_songs(r)) > 0)]
    order = d.groupby(["artist", "artist_mbid"]).size().sort_values(ascending=False)
    return [(a, m) for a, m in order.index]


def pages_needed(first_page: dict, cap: int = CAREER_PAGES) -> int:
    total, per = first_page.get("total", 0), first_page.get("per_page", 20) or 20
    return max(1, min(cap, math.ceil(total / per))) if total else 1


def summarize_history(pages: list, min_songs: int = MIN_SET_SONGS) -> dict:
    """Song counts over the fetched pages.

    Setlists with fewer than `min_songs` songs (future dates, snippets, partial logs) are ignored.
    """
    total = pages[0]["total"] if pages else 0
    per = pages[0].get("per_page", 20) if pages else 20
    counts, dates, n = Counter(), set(), 0
    for p in pages:
        for show in p["shows"]:
            keys = {song_key(s) for s in show["songs"] if song_key(s)}
            if len(keys) < min_songs:
                continue
            n += 1
            counts.update(keys)
            dates.add(show["date"])
    parsed = [d for d in (_date(x) for x in dates) if d]
    return {"n": n, "counts": counts, "dates": dates, "total": total,
            "complete": len(pages) * per >= total, "oldest": min(parsed) if parsed else None}


def career_rare_songs(df_att: pd.DataFrame, histories: dict, min_logged: int = MIN_LOGGED,
                      min_songs: int = MIN_SET_SONGS):
    """Every song you heard live, ranked by how few times the artist played it in the shows checked.

    histories: mbid -> summarize_history() result. Your own concerts count (they're in the
    artist's history). Concerts older than the checked window are skipped, since songs a band
    later dropped would look rare only because they moved on.
    Returns (DataFrame rarest first, stats dict).
    """
    best, scored, skipped_small, skipped_old, unchecked, skipped_short = {}, 0, 0, 0, 0, 0
    d = df_att.dropna(subset=["eventDate_dt"])
    for r in d.itertuples():
        songs = _songs(getattr(r, "songs", None))
        if not songs:
            continue
        if len({song_key(x) for x in songs if song_key(x)}) < min_songs:
            skipped_short += 1
            continue
        h = histories.get(getattr(r, "artist_mbid", None))
        if not h:
            unchecked += 1
            continue
        if h["total"] < min_logged:
            skipped_small += 1
            continue
        show_day = r.eventDate_dt.date()
        if not h["complete"] and h["oldest"] and show_day < h["oldest"]:
            skipped_old += 1
            continue
        counts, n = h["counts"], h["n"]
        in_history = r.eventDate_dt.strftime("%d-%m-%Y") in h["dates"]
        if not in_history:  # your setlist wasn't in the pages (missing or empty there): count it too
            counts = counts + Counter({song_key(s) for s in songs if song_key(s)})
            n += 1
        scored += 1
        where = f"all {n} logged shows" if h["complete"] else f"their last {n} shows"
        for title in dict.fromkeys(songs):
            k = song_key(title)
            if not k:
                continue
            played = max(int(counts.get(k, 0)), 1)
            cand = {"Song": title, "Artist": r.artist, "Heard On": r.Date, "Venue": r.venue,
                    "Played In": f"{played} of {where}", "Times Played": played, "Shows Checked": n,
                    "Frequency": f"{played / n * 100:.1f}%" if n else "", "pct": played / n * 100 if n else 100.0,
                    "n": n, "_dt": r.eventDate_dt}
            key = (r.artist, k)
            old = best.get(key)
            if old is None or cand["_dt"] > old["_dt"]:
                best[key] = cand
    df = pd.DataFrame(list(best.values()), columns=RARE_COLUMNS + ["_dt"])
    df = df.sort_values(["Times Played", "n", "_dt"], ascending=[True, False, False]).reset_index(drop=True)
    stats = {"scored_shows": scored, "skipped_short": skipped_short,
             "skipped_shows": skipped_small + skipped_old + unchecked + skipped_short,
             "skipped_small": skipped_small, "skipped_old": skipped_old, "unchecked": unchecked}
    return df.drop(columns=["_dt"]), stats


def show_position(get_page, when: date, today: date = None, max_future_pages: int = 3):
    """How many of an artist's setlist.fm shows were logged before and since a given date.

    get_page(p) returns compact page p (newest first). Uses a binary search, so it needs about
    log2(pages) + 1 lookups. Future-dated placeholders (announced shows) aren't counted as 'since'.
    Returns {"before", "since", "total"} or None if the artist has no history.
    """
    today = today or date.today()
    first = get_page(1)
    total, per = first.get("total", 0), first.get("per_page", 20) or 20
    if not total or not first["shows"]:
        return None
    pages = math.ceil(total / per)

    def dates(p):
        return [d for d in (_date(s["date"]) for s in get_page(p)["shows"]) if d]

    lo, hi = 1, pages
    while lo < hi:  # first page whose oldest show is on/before `when`
        mid = (lo + hi) // 2
        ds = dates(mid)
        if ds and min(ds) > when:
            lo = mid + 1
        else:
            hi = mid
    ds = dates(lo)
    after = (lo - 1) * per + sum(d > when for d in ds)
    on_day = sum(d == when for d in ds)

    future = 0
    for p in range(1, min(pages, max_future_pages) + 1):
        ds_p = dates(p)
        future += sum(d > today for d in ds_p)
        if not ds_p or min(ds_p) <= today:
            break
    return {"before": max(total - after - on_day, 0), "since": max(after - future, 0), "total": total}


def _norm(value) -> str:
    return " ".join(str(value).lower().split()) if pd.notna(value) else ""


def cover_keys(df_att: pd.DataFrame) -> set:
    """(artist, song key) for every cover you heard live, from setlist.fm's cover info."""
    keys = set()
    if df_att is None or df_att.empty or "covers" not in df_att.columns:
        return keys
    for artist, raw in zip(df_att["artist"], df_att["covers"]):
        try:
            items = json.loads(raw) if pd.notna(raw) else []
        except (TypeError, ValueError):
            continue
        for c in items:
            if isinstance(c, dict) and c.get("song") and song_key(c["song"]):
                keys.add((_norm(artist), song_key(c["song"])))
    return keys


def drop_covers(table: pd.DataFrame, df_att: pd.DataFrame) -> pd.DataFrame:
    """Remove cover songs from a rarest-songs table (live result or saved snapshot)."""
    if table is None or table.empty:
        return table
    covers = cover_keys(df_att)
    if not covers:
        return table
    is_cover = [(_norm(a), song_key(s)) in covers for a, s in zip(table["Artist"], table["Song"])]
    return table[[not c for c in is_cover]].reset_index(drop=True)


def floor_by_times_heard(table: pd.DataFrame, df_att: pd.DataFrame) -> pd.DataFrame:
    """A song can't have been played fewer times than you heard it, so raise counts that are lower.

    That can happen when one of your concerts is older than the artist's checked window. Works on a
    live result or a saved snapshot, and re-sorts rarest first.
    """
    if table is None or table.empty or df_att is None or df_att.empty or "songs" not in df_att.columns:
        return table
    heard = Counter()
    d = df_att.dropna(subset=["eventDate_dt"]).drop_duplicates(subset=["eventDate_dt", "artist"])
    for artist, raw in zip(d["artist"], d["songs"]):
        keys = {song_key(s) for s in _songs(raw) if song_key(s)}
        if len(keys) >= MIN_SET_SONGS:
            heard.update({(_norm(artist), k) for k in keys})
    out = table.copy()
    times = [max(int(t), heard.get((_norm(a), song_key(s)), 0))
             for a, s, t in zip(out["Artist"], out["Song"], out["Times Played"])]
    changed = [t != int(o) for t, o in zip(times, out["Times Played"])]
    out["Times Played"] = times
    out["Played In"] = [f"{t}{str(p)[len(str(p).split(' ')[0]):]}" if c else p
                        for t, p, c in zip(times, out["Played In"], changed)]
    if "n" in out.columns:
        out["pct"] = [t / n * 100 if n else 100.0 for t, n in zip(times, out["n"])]
        out["Frequency"] = [f"{v:.1f}%" for v in out["pct"]]
        out = out.sort_values(["Times Played", "n"], ascending=[True, False], kind="stable")
    return out.reset_index(drop=True)
