import json

import pandas as pd

from analytics.compare import compare_histories
from analytics.early_fans import early_fan_table, find_early_sightings, growth_plan
from data.attendance import process_attendance


def _rows(shows):
    """shows: list of (date, venue, [(artist, mbid, song_count), ...])."""
    rows = []
    for date, venue, acts in shows:
        for artist, mbid, n in acts:
            rows.append({"eventDate": date, "artist": artist, "artist_mbid": mbid, "venue": venue,
                         "city": "NYC", "state": "NY", "lat": 1, "long": 1, "song_count": n,
                         "tour": None, "url": "", "songs": json.dumps(["x"] * n)})
    df_att, _, _ = process_attendance(pd.DataFrame(rows))
    return df_att


def test_early_sightings_and_growth():
    df = _rows([
        ("2018-05-01", "Small Club", [("Rising Star", "r1", 8), ("Big Band", "b1", 20)]),
        ("2019-06-01", "Arena", [("Rising Star", "r1", 9), ("Big Band", "b1", 21)]),   # opened again
        ("2021-07-01", "Theater", [("Rising Star", "r1", 18), ("New Opener", "n1", 5)]),  # headlines
        ("2020-01-01", "Bar", [("Tie A", "t1", 10), ("Tie B", "t2", 10)]),            # ambiguous, skipped
        ("2026-03-01", "Hall", [("Too Recent", "z1", 4), ("Big Band", "b1", 20)]),
    ])
    s = find_early_sightings(df).set_index("artist")
    assert set(s.index) == {"Rising Star", "New Opener", "Too Recent"}
    assert s.loc["Rising Star", "opened_for"] == "Big Band"
    assert str(s.loc["Rising Star", "eventDate_dt"].date()) == "2018-05-01"          # first time only
    assert s.loc["Rising Star", "headline_venue"] == "Theater"
    assert pd.isna(s.loc["New Opener", "headline_dt"])

    sightings = find_early_sightings(df)
    plan = growth_plan(sightings, this_year=2026)
    assert ("Rising Star", "r1", 2018) in plan and ("Rising Star", "r1", 2025) in plan
    assert not any(p[0] == "Too Recent" for p in plan)                              # no 'later' yet

    counts = {("r1", 2018): 10, ("r1", 2025): 80, ("n1", 2021): 20, ("n1", 2025): 10}
    t = early_fan_table(sightings, {"rising star": 500}, counts, this_year=2026)
    assert list(t["Artist"])[:2] == ["Rising Star", "New Opener"]
    top = t.iloc[0]
    assert top["Growth"] == "×8.0" and top["Later Headlined"] == "Theater (Jul 2021)"
    assert top["Shows Logged"] == 500 and top["Shows That Year"] == 10

    # Before growth is measured: later-headliners first, then most recent
    t0 = early_fan_table(sightings, {}, None, this_year=2026)
    assert list(t0["Artist"]) == ["Rising Star", "Too Recent", "New Opener"]
    assert t0["Growth"].tolist() == ["", "", ""]

    # An act with no logged shows last year isn't shown as ×0.0
    t2 = early_fan_table(sightings, {}, {("r1", 2018): 10, ("r1", 2025): 0}, this_year=2026)
    assert t2.set_index("Artist").loc["Rising Star", "Growth"] == "No shows last year"


def test_compare_histories():
    me = _rows([
        ("2024-01-01", "MSG", [("Band A", "a", 15), ("Opener", "o", 5)]),
        ("2024-02-01", "Beacon", [("Band B", "b", 12)]),
        ("2024-03-01", "Beacon", [("Band A", "a", 14)]),
        ("2024-04-01", "Club", [("Only Mine", "m", 10)]),
    ])
    friend = _rows([
        ("2024-01-01", "msg", [("Band A", "a", 15)]),                 # same night, venue case differs
        ("2023-05-01", "Beacon", [("Band B", "b", 11)]),
        ("2023-06-01", "Stadium", [("Only Theirs", "t", 20)]),
        ("2023-07-01", "Stadium", [("Only Theirs", "t", 20)]),
    ])
    res = compare_histories(me, friend)
    st = res["stats"]
    assert st["same_shows"] == 1 and st["shared_artists"] == 2
    assert res["same_shows"].iloc[0]["Lineup"] == "Band A, Opener"
    shared = res["shared_artists"].set_index("Artist")
    assert shared.loc["Band A", "You"] == 2 and shared.loc["Band A", "Them"] == 1
    assert list(res["only_me"]["Artist"]) == ["Only Mine", "Opener"] or set(res["only_me"]["Artist"]) == {"Only Mine", "Opener"}
    assert res["only_them"].iloc[0]["Artist"] == "Only Theirs" and res["only_them"].iloc[0]["Times Seen"] == 2
    assert "Beacon" in res["shared_venues"] and st["my_concerts"] == 4 and st["their_concerts"] == 4


def test_relive_a_night_order_and_covers():
    from analytics.nights import night_options, night_playlist_name, night_tracklist
    rows = [
        {"eventDate": "2024-05-01", "artist": "Headliner", "artist_mbid": "h", "venue": "Arena", "city": "NYC",
         "state": "NY", "lat": 1, "long": 1, "song_count": 3, "tour": None, "url": "",
         "songs": json.dumps(["Big Hit", "Cover Tune", "Big Hit"]),
         "covers": json.dumps([{"song": "Cover Tune", "original": "Legends"}])},
        {"eventDate": "2024-05-01", "artist": "Opener", "artist_mbid": "o", "venue": "Arena", "city": "NYC",
         "state": "NY", "lat": 1, "long": 1, "song_count": 1, "tour": None, "url": "",
         "songs": json.dumps(["Warm Up"]), "covers": "[]"},
        {"eventDate": "2023-01-01", "artist": "No Setlist", "artist_mbid": "n", "venue": "Bar", "city": "NYC",
         "state": "NY", "lat": 1, "long": 1, "song_count": 0, "tour": None, "url": "",
         "songs": "[]", "covers": "[]"},
    ]
    df, _, _ = process_attendance(pd.DataFrame(rows))
    opts = night_options(df)
    assert len(opts) == 1 and opts[0]["headliner"] == "Headliner"
    assert opts[0]["label"].startswith("May 01, 2024 · Headliner + Opener")
    t = night_tracklist(df, opts[0]["day"], opts[0]["venue"])
    assert list(t["Song"]) == ["Warm Up", "Big Hit", "Cover Tune"]          # opener first, repeat dropped
    assert list(t["#"]) == [1, 2, 3] and t.iloc[2]["Original"] == "Legends"
    assert list(night_tracklist(df, opts[0]["day"], "Arena", include_openers=False)["Artist"]) == ["Headliner"] * 2
    assert night_playlist_name("Headliner", "Arena", opts[0]["day"]) == "Headliner · Arena · May 01, 2024"


def test_heard_live_modes():
    from analytics.heard_live import apply_heard_mode, heard_song_keys
    df = _rows([("2024-01-01", "Club", [("The Band", "b", 2)])])
    df.loc[:, "songs"] = json.dumps(["Old Favorite (Live)", "Another One"])
    heard, shows = heard_song_keys(df, "the band")
    assert shows == 1 and len(heard) == 2
    table = pd.DataFrame({"Song Title": ["Old Favorite", "Brand New", "Another One!", "Deep Cut"],
                          "Plays": [9, 8, 7, 6]})
    first = apply_heard_mode(table, heard, "unheard_first")
    assert list(first["Song Title"]) == ["Brand New", "Deep Cut", "Old Favorite", "Another One!"]
    assert list(first["Heard Live"])[:2] == ["🆕 Not yet", "🆕 Not yet"]
    only = apply_heard_mode(table, heard, "unheard_only", max_len=1)
    assert list(only["Song Title"]) == ["Brand New"]
    assert list(apply_heard_mode(table, heard, "all")["Song Title"]) == list(table["Song Title"])
    assert heard_song_keys(df, "Someone Else") == (set(), 0)


def test_wrapped_summary():
    from analytics.wrapped import available_years, wrapped_summary
    df = _rows([
        ("2025-03-01", "MSG", [("Band A", "a", 10)]),
        ("2025-06-01", "MSG", [("Band A", "a", 12), ("Opener", "o", 3)]),
        ("2024-01-01", "Club", [("Band A", "a", 8)]),
    ])
    assert available_years(df) == [2025, 2024]
    rare = pd.DataFrame([{"Song": "x", "Artist": "Band A", "Heard On": "06-01-2025", "Played In": "1 of 20 shows in 2025"}])
    pop = pd.DataFrame([{"Artist": "Band A", "Shows Tracked": 900}, {"Artist": "Opener", "Shows Tracked": 1}])
    w = wrapped_summary(df, 2025, rare, pop)
    assert w["concerts"] == 2 and w["sets"] == 3 and w["artists"] == 2 and w["songs"] == 25
    assert w["new_artists"] == 1 and w["prev_concerts"] == 1
    assert w["top_artist"] == "Band A" and w["top_artist_count"] == 2 and w["top_venue"] == "MSG"
    assert w["rarest_song"] == "x by Band A"
    assert w["biggest_act"].startswith("Band A (900") and w["smallest_act"] == "Opener (1 show logged)"
    assert wrapped_summary(df, 2030) == {}
    assert wrapped_summary(df, None)["concerts"] == 3
