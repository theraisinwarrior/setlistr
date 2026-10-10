from collections import Counter
from datetime import datetime

import pandas as pd

from analytics.deep_cuts import deep_cuts_table, song_frequency, song_key
from analytics.passport_stats import compute_highlights, haversine_miles
from data.attendance import process_attendance


def _show(artists_songs):
    return {"sets": {"set": [{"song": [{"name": s} for s in artists_songs]}]}}


def test_song_key_ignores_version_tags_and_punctuation():
    assert song_key("Love Story (Taylor's Version)") == song_key("Love Story")
    assert song_key("Don't Stop!") == "dontstop"


def test_song_frequency_counts_once_per_show_and_skips_short_sets():
    full = ["A", "B", "C", "D", "E"]
    shows = [_show(full), _show(full + ["F"]), _show(["A", "A"])]  # last is a snippet
    n, counts = song_frequency(shows, min_songs=5)
    assert n == 2
    assert counts[song_key("A")] == 2 and counts[song_key("F")] == 1


def test_deep_cuts_table_flags_rare_and_unseen_songs():
    counts = Counter({song_key("Hit"): 9, song_key("Rare"): 1})
    t = deep_cuts_table(["Hit", "Rare", "Never Played"], counts, n_shows=10, threshold_pct=25)
    assert list(t["Track Title"]) == ["Never Played", "Rare"]  # fewest plays first, Hit excluded
    assert t.iloc[1]["Frequency"] == "10%"


def _fake_attendance():
    rows = []

    def add(date, artist, venue, city, state, lat, lon, songs=("a", "b")):
        import json
        rows.append({"eventDate": date, "artist": artist, "venue": venue, "city": city,
                     "state": state, "lat": lat, "long": lon, "song_count": len(songs),
                     "tour": None, "url": "", "songs": json.dumps(list(songs))})

    # three shows in one week at MSG, one far-away show, plus a 3-act festival day
    add("2024-03-01", "Band A", "MSG", "New York", "NY", 40.75, -73.99)
    add("2024-03-04", "Band A", "MSG", "New York", "NY", 40.75, -73.99)
    add("2024-03-06", "Band B", "MSG", "New York", "NY", 40.75, -73.99)
    add("2024-09-10", "Band C", "Red Rocks", "Morrison", "CO", 39.67, -105.20)
    for artist in ("X", "Y", "Z"):
        add("2025-06-01", artist, "Field", "Newark", "NJ", 40.73, -74.17)
    return pd.DataFrame(rows)


def test_haversine_known_distance():
    assert 2400 < haversine_miles(40.71, -74.0, 34.05, -118.24) < 2500  # NYC to LA


def test_highlights_and_badges():
    df_att, df_concerts, df_songs = process_attendance(_fake_attendance())
    h = compute_highlights(df_att, df_concerts, df_songs, today=datetime(2026, 3, 1))
    assert h["total_songs"] == 14 and h["unique_songs"] >= 2
    assert h["top_venue"] == "MSG" and h["top_venue_count"] == 3
    assert h["hot_streak"] is True
    assert h["festival_days"] == 1
    assert h["farthest_miles"] > 1500  # Colorado is far from the New York home base
    assert h["states_count"] == 3
    assert h["longest_month_streak"] == 1
    assert any("Band A" in line for line in h["on_this_day"])  # 03-01 anniversary
    earned = {b["name"] for b in h["badges"] if b["earned"]}
    assert {"Hot Streak", "Festival Goer"} <= earned and "Century Club" not in earned


def test_highlights_empty():
    assert compute_highlights(pd.DataFrame(), pd.DataFrame(), pd.DataFrame()) == {}
