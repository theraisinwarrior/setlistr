"""Deep-cut rarity from setlist.fm API data. Pure functions, no Streamlit."""
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


def deep_cuts_table(user_songs, counts: Counter, n_shows: int, threshold_pct: float = 25.0):
    """Songs the user heard live that were played in under `threshold_pct` of recent shows."""
    rows = []
    for title in user_songs:
        played = counts.get(song_key(title), 0)
        pct = (played / n_shows) * 100.0 if n_shows else 0.0
        if pct < threshold_pct:
            rows.append({
                "Track Title": title,
                "Played (recent shows)": played,
                "Out of": n_shows,
                "Frequency": f"{pct:.0f}%",
            })
    df = pd.DataFrame(rows, columns=["Track Title", "Played (recent shows)", "Out of", "Frequency"])
    return df.sort_values(["Played (recent shows)", "Track Title"]).reset_index(drop=True)
