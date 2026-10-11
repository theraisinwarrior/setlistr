from collections import Counter
from datetime import datetime

import pandas as pd

from analytics.deep_cuts import song_frequency, song_key
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


def test_global_rare_songs_ranks_across_artists():
    import json
    from analytics.deep_cuts import global_rare_songs, scan_plan
    rows = [
        {"eventDate": "2024-05-01", "artist": "Band A", "artist_mbid": "a1", "venue": "V1", "city": "NYC",
         "state": "NY", "lat": 1, "long": 1, "song_count": 3, "tour": None, "url": "",
         "songs": json.dumps(["Hit", "Bustout", "Other"])},
        {"eventDate": "2023-05-01", "artist": "Band B", "artist_mbid": "b1", "venue": "V2", "city": "NYC",
         "state": "NY", "lat": 1, "long": 1, "song_count": 1, "tour": None, "url": "",
         "songs": json.dumps(["Only Song"])},
        {"eventDate": "2024-06-01", "artist": "Band C", "artist_mbid": "c1", "venue": "V3", "city": "NYC",
         "state": "NY", "lat": 1, "long": 1, "song_count": 1, "tour": None, "url": "",
         "songs": json.dumps(["Tiny Sample Song"])},
    ]
    df_att, _, _ = process_attendance(pd.DataFrame(rows))

    assert len(scan_plan(df_att)) == 3
    assert len(scan_plan(df_att, min_year=2024)) == 2

    samples = {
        ("a1", 2024): (20, Counter({song_key("Hit"): 19, song_key("Other"): 10})),  # Bustout never in sample
        ("b1", 2023): (10, Counter({song_key("Only Song"): 2})),
        ("c1", 2024): (3, Counter()),  # sample too small, so skipped
    }
    table, stats = global_rare_songs(df_att, samples, min_sample=8)

    assert list(table["Song"]) == ["Bustout", "Only Song", "Other", "Hit"]
    assert table.iloc[0]["Played In"] == "1 of 20 shows in 2024"   # own show counts at minimum
    assert table.iloc[0]["Frequency"] == "5%"
    assert stats == {"scored_shows": 2, "skipped_shows": 1}


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


def test_extract_covers():
    from data.attendance import extract_covers, setlists_to_dataframe
    setlists = [{
        "eventDate": "15-03-2024", "artist": {"name": "Band A"},
        "venue": {"name": "MSG", "city": {"name": "New York"}},
        "sets": {"set": [{"song": [
            {"name": "Original Song"},
            {"name": "Come Together", "cover": {"name": "The Beatles"}},
            {"name": "Tape Cover", "tape": True, "cover": {"name": "Nobody"}},
        ]}]},
    }]
    df_att, _, _ = process_attendance(setlists_to_dataframe(setlists))
    covers = extract_covers(df_att)
    assert len(covers) == 1
    row = covers.iloc[0]
    assert (row["Song"], row["Original Artist"], row["Performed By"]) == ("Come Together", "The Beatles", "Band A")
    # data without cover info (the old CSV) yields an empty table instead of crashing
    assert extract_covers(df_att.drop(columns="covers")).empty


def test_venue_top_performers_counts_individual_artists():
    from analytics.passport_stats import venue_top_performers
    df_att, _, _ = process_attendance(_fake_attendance())
    top = venue_top_performers(df_att)
    assert top["MSG"].split("<br>")[0] == "Band A ×2"   # seen twice there, listed once
    assert "Band B ×1" in top["MSG"]
    assert top["Red Rocks"] == "Band C ×1"


def test_rank_artists_by_popularity():
    from analytics.popularity import artists_to_scan, rank_artists_by_popularity
    df_att, _, _ = process_attendance(pd.DataFrame([
        {"eventDate": "2024-01-01", "artist": "Big Band", "artist_mbid": "m1", "venue": "V", "city": "C",
         "state": "NY", "lat": 1, "long": 1, "song_count": 1, "tour": None, "url": "", "songs": "[]"},
        {"eventDate": "2024-06-01", "artist": "Big Band", "artist_mbid": "m1", "venue": "V", "city": "C",
         "state": "NY", "lat": 1, "long": 1, "song_count": 1, "tour": None, "url": "", "songs": "[]"},
        {"eventDate": "2023-03-01", "artist": "Tiny Band", "artist_mbid": "m2", "venue": "W", "city": "C",
         "state": "NY", "lat": 1, "long": 1, "song_count": 1, "tour": None, "url": "", "songs": "[]"},
        {"eventDate": "2022-03-01", "artist": "Unchecked", "artist_mbid": "m3", "venue": "W", "city": "C",
         "state": "NY", "lat": 1, "long": 1, "song_count": 1, "tour": None, "url": "", "songs": "[]"},
    ]))
    assert len(artists_to_scan(df_att)) == 3
    table = rank_artists_by_popularity(df_att, {"m1": 2500, "m2": 7})   # m3 was never looked up
    assert list(table["Artist"]) == ["Big Band", "Tiny Band"]
    assert table.iloc[0]["Times Seen"] == 2 and table.iloc[0]["Last Seen"] == "Jun 01, 2024"
    assert table.iloc[1]["Shows Tracked"] == 7
    assert rank_artists_by_popularity(df_att, {}).empty


def test_parse_attendance_count():
    from services.setlistfm_web import parse_attendance_count
    html = '<div><a href="/x">110 users</a> were there</div>'
    assert parse_attendance_count(html) == 110
    assert parse_attendance_count("<p><a>1,234 users</a> were there</p>") == 1234
    assert parse_attendance_count("<p>1 user was there</p>") == 1
    assert parse_attendance_count("<p>nothing here</p>") is None
    assert parse_attendance_count("") is None


def test_rank_shows_by_attendance():
    from analytics.popularity import rank_shows_by_attendance, shows_to_scan
    base = {"venue": "V", "city": "C", "state": "NY", "lat": 1, "long": 1, "song_count": 1,
            "tour": None, "songs": "[]"}
    df_att, _, _ = process_attendance(pd.DataFrame([
        {**base, "eventDate": "2024-01-01", "artist": "A", "artist_mbid": "m1", "url": "https://www.setlist.fm/setlist/a/1.html"},
        {**base, "eventDate": "2024-02-01", "artist": "B", "artist_mbid": "m2", "url": "https://www.setlist.fm/setlist/b/2.html"},
        {**base, "eventDate": "2024-03-01", "artist": "C", "artist_mbid": "m3", "url": ""},
    ]))
    assert len(shows_to_scan(df_att)) == 2
    t = rank_shows_by_attendance(df_att, {"https://www.setlist.fm/setlist/a/1.html": 5,
                                          "https://www.setlist.fm/setlist/b/2.html": 90})
    assert list(t["Artist"]) == ["B", "A"] and t.iloc[0]["Users There"] == 90
    assert rank_shows_by_attendance(df_att, {}).empty
