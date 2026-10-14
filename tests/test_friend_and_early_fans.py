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
