"""Deep-cut rarity from setlist.fm API data. Pure functions, no Streamlit."""
import json
import re
from collections import Counter

import pandas as pd


def song_key(name: str) -> str:
    """Normalize a song title so 'Love Story (Taylor's Version)' matches 'Love Story'."""
    no_parens = re.sub(r"\(.*?\)|\[.*?\]", "", str(name))
    return re.sub(r"[^a-z0-9]", "", no_parens.lower())


def song_frequency(setlists: list, min_songs: int = 5):
    """Count how many shows each song appeared in (once per show, tape playbacks ignored).

    Shows with fewer than `min_songs` songs (festival snippets, partial sets) are skipped.
    Returns (number_of_shows_used, Counter keyed by song_key).
    """
    counts, n_shows = Counter(), 0
    for sl in setlists:
        keys = set()
        for s in (sl.get("sets") or {}).get("set", []):
            for song in s.get("song", []):
                if song.get("tape", False):
                    continue
                name = song.get("name")
                if name and song_key(name):
                    keys.add(song_key(name))
        if len(keys) < min_songs:
            continue
        n_shows += 1
        counts.update(keys)
    return n_shows, counts


def scan_plan(df_att: pd.DataFrame, min_year=None) -> list:
    """Unique (artist, mbid, year) combinations that need a setlist sample."""
    if "artist_mbid" not in df_att.columns:
        return []
    d = df_att.dropna(subset=["artist_mbid", "year"])
    if min_year is not None:
        d = d[d["year"] >= min_year]
    d = d.drop_duplicates(subset=["artist", "artist_mbid", "year"])
    return [(r.artist, r.artist_mbid, int(r.year)) for r in d.itertuples()]


def global_rare_songs(df_att: pd.DataFrame, samples: dict, min_sample: int = 8):
    """Rank every song you heard live by how rarely that artist played it that year.

    `samples` maps (mbid, year) -> (n_shows, Counter) from song_frequency().
    A song's frequency is the share of that artist's sampled shows from the year you saw
    them that included it. Your own show counts, so the minimum is 1 play.

    Returns (DataFrame sorted rarest first, stats dict).
    """
    best = {}
    scored_shows = skipped_shows = 0

    for _, row in df_att.iterrows():
        sample = samples.get((row.get("artist_mbid"), row.get("year")))
        if not sample or sample[0] < min_sample or pd.isna(row.get("songs")):
            skipped_shows += 1
            continue
        n, counts = sample
        try:
            songs = json.loads(row["songs"])
        except Exception:
            skipped_shows += 1
            continue
        scored_shows += 1

        for title in dict.fromkeys(s.strip() for s in songs if isinstance(s, str) and s.strip()):
            played = max(counts.get(song_key(title), 0), 1)
            pct = played / n * 100.0
            key = (row["artist"], song_key(title))
            cand = {"Song": title, "Artist": row["artist"], "Heard On": row["Date"],
                    "Venue": row["venue"], "Played In": f"{played} of {n} shows in {int(row['year'])}",
                    "pct": pct, "n": n, "_dt": row["eventDate_dt"]}
            old = best.get(key)
            if old is None or (cand["pct"], -cand["n"]) < (old["pct"], -old["n"]):
                best[key] = cand

    cols = ["Song", "Artist", "Heard On", "Venue", "Played In", "pct", "n", "_dt"]
    df = pd.DataFrame(list(best.values()), columns=cols)
    df = df.sort_values(["pct", "n", "_dt"], ascending=[True, False, False]).reset_index(drop=True)
    df["Frequency"] = df["pct"].map(lambda v: f"{v:.0f}%")
    return df.drop(columns=["_dt"]), {"scored_shows": scored_shows, "skipped_shows": skipped_shows}
