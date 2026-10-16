import json

import pandas as pd

from analytics.compare import compare_histories
from analytics.early_fans import early_fan_table, find_early_sightings, position_key, position_plan
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
    plan = position_plan(sightings)
    assert {p[0] for p in plan} == {"Rising Star", "New Opener", "Too Recent"}

    positions = {position_key("r1", pd.Timestamp("2018-05-01")): {"before": 10, "since": 80},
                 position_key("n1", pd.Timestamp("2021-07-01")): {"before": 0, "since": 30},
                 position_key("z1", pd.Timestamp("2026-03-01")): {"before": 50, "since": 5}}
    t = early_fan_table(sightings, positions)
    assert list(t["Artist"]) == ["New Opener", "Rising Star", "Too Recent"]   # first-ever show ranks top
    assert t.iloc[0]["Glow-up"] == "Their first logged show!"
    top = t.set_index("Artist").loc["Rising Star"]
    assert top["Glow-up"] == "×8.0" and top["Shows Before"] == 10 and top["Shows Since"] == 80
    assert top["Later Headlined"] == "Theater (Jul 2021)"

    # Before growth is measured: later-headliners first, then most recent
    t0 = early_fan_table(sightings)
    assert list(t0["Artist"]) == ["Rising Star", "Too Recent", "New Opener"]
    assert t0["Glow-up"].tolist() == ["", "", ""]


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


def test_wrapped_ties_and_image():
    from analytics.wrapped import highlight_lines, leader_label, wrapped_summary
    from analytics.wrapped_image import render_wrapped_png
    assert leader_label(pd.Series({"A": 3, "B": 1}), "artists") == "A · 3×"
    assert leader_label(pd.Series({"B": 2, "A": 2, "C": 1}), "artists") == "A & B tied at 2×"
    assert leader_label(pd.Series({"C": 1, "A": 1, "B": 1}), "artists") == "A, B & C tied at 1×"
    assert leader_label(pd.Series({n: 1 for n in "ABCDE"}), "artists") == "5 artists tied at 1×"
    df = _rows([("2025-03-01", "MSG", [("Band A", "a", 10)]), ("2025-06-01", "Club", [("Band B", "b", 9)])])
    w = wrapped_summary(df, 2025)
    lines = highlight_lines(w)
    assert lines[0] == ("Top artist", "Band A & Band B tied at 1×")
    png = render_wrapped_png(w, "someone", lines)
    assert png[:8] == b"\x89PNG\r\n\x1a\n" and len(png) > 10_000


def _fake_history(dates_songs, per=20):
    """Newest-first compact pages from [(date, [songs])]."""
    shows = [{"date": d.strftime("%d-%m-%Y"), "songs": songs} for d, songs in dates_songs]
    pages = [{"total": len(shows), "per_page": per, "shows": shows[i:i + per]} for i in range(0, len(shows), per)]
    return pages or [{"total": 0, "per_page": per, "shows": []}]


def test_show_position_before_and_since():
    from datetime import date, timedelta
    from analytics.career import show_position
    today = date(2026, 10, 14)
    # 3 announced future shows, then 92 played shows one day apart going back from Oct 13
    hist = [(today + timedelta(days=30 - i), []) for i in range(3)]
    hist += [(today - timedelta(days=1 + i), ["Song"]) for i in range(92)]
    pages = _fake_history(hist)
    calls = []
    get = lambda p: (calls.append(p), pages[p - 1])[1]
    seen = today - timedelta(days=41)                # the 41st played show back
    pos = show_position(get, seen, today)
    assert pos == {"before": 92 - 41, "since": 40, "total": 95}
    assert len(set(calls)) <= 4                      # binary search, not a full scan
    first = show_position(get, today - timedelta(days=92), today)
    assert first["before"] == 0 and first["since"] == 91
    assert show_position(lambda p: {"total": 0, "per_page": 20, "shows": []}, today, today) is None


def test_career_rare_songs():
    from datetime import date, timedelta
    from analytics.career import career_plan, career_rare_songs, pages_needed, summarize_history
    base = date(2025, 6, 1)
    hist = [(base - timedelta(days=i), ["Hit", "Staple", "Opener"] + (["Debut"] if i == 10 else []))
            for i in range(30)]
    pages = _fake_history(hist)
    assert pages_needed(pages[0]) == 2 and pages_needed({"total": 5000, "per_page": 20}) == 10
    h = summarize_history(pages)
    assert h["n"] == 30 and h["complete"] and h["counts"]["debut"] == 1

    seen_day = base - timedelta(days=10)
    rows = [{"eventDate": seen_day.isoformat(), "artist": "Band", "artist_mbid": "b", "venue": "V",
             "city": "C", "state": "NY", "lat": 1, "long": 1, "song_count": 3, "tour": None, "url": "",
             "songs": json.dumps(["Debut", "Hit", "Staple", "Opener"])},
            {"eventDate": "2024-01-01", "artist": "Tiny", "artist_mbid": "t", "venue": "V", "city": "C",
             "state": "NY", "lat": 1, "long": 1, "song_count": 1, "tour": None, "url": "",
             "songs": json.dumps(["Only", "Two", "Three"])}]
    df, _, _ = process_attendance(pd.DataFrame(rows))
    assert {m for _, m in career_plan(df)} == {"b", "t"}
    tiny = summarize_history(_fake_history([(date(2024, 1, 1), ["Only", "Two", "Three"])]))
    table, stats = career_rare_songs(df, {"b": h, "t": tiny})
    assert list(table["Song"]) == ["Debut", "Hit", "Staple", "Opener"]
    assert table.iloc[0]["Times Played"] == 1 and table.iloc[0]["Played In"] == "1 of all 30 logged shows"
    assert stats["scored_shows"] == 1 and stats["skipped_small"] == 1      # Tiny has < 20 logged shows

    # A show older than an incomplete window is skipped rather than looking falsely rare
    partial = dict(h, complete=False, total=900)
    old_row = dict(rows[0], eventDate="2020-01-01")
    df_old, _, _ = process_attendance(pd.DataFrame([old_row]))
    t2, s2 = career_rare_songs(df_old, {"b": partial})
    assert t2.empty and s2["skipped_old"] == 1

    # Your own show counts even when it's missing from the fetched pages (the old Lorde bug)
    missing = summarize_history(_fake_history([(base - timedelta(days=i), ["Hit", "Staple", "Opener"])
                                               for i in range(30) if i != 10]))
    t3, _ = career_rare_songs(df, {"b": missing})
    assert t3.set_index("Song").loc["Hit", "Times Played"] == 30          # 29 in pages + yours
    assert t3.set_index("Song").loc["Debut", "Times Played"] == 1


def test_wrapped_tiebreak_by_biggest_act():
    from analytics.wrapped import wrapped_summary
    df = _rows([("2025-01-01", "A1", [("Small Band", "s", 5)]), ("2025-02-01", "A2", [("Small Band", "s", 5)]),
                ("2025-03-01", "B1", [("Huge Band", "h", 5)]), ("2025-04-01", "B2", [("Huge Band", "h", 5)]),
                ("2025-05-01", "C1", [("Once", "o", 5)])])
    pop = pd.DataFrame([{"Artist": "Huge Band", "Shows Tracked": 3000}, {"Artist": "Small Band", "Shows Tracked": 40}])
    w = wrapped_summary(df, 2025, None, pop)
    assert w["top_artist_label"] == "Huge Band · 2×" and w["top_artist_tied"] == 1
    assert wrapped_summary(df, 2025)["top_artist_label"] == "Huge Band & Small Band tied at 2×"   # no size data


def test_glowup_skips_tiny_acts_and_reranks_snapshots():
    from analytics.early_fans import rank_early_table
    snap = pd.DataFrame([
        {"Artist": "Sophisticuffs", "Opened For": "Vampire Weekend", "Date": "Sep 15, 2025", "Venue": "W",
         "Later Headlined": "", "Shows Before": 0, "Shows Since": 3, "Glow-up": "Their first logged show!"},
        {"Artist": "Jalen Ngonda", "Opened For": "Lake Street Dive", "Date": "Nov 05, 2018", "Venue": "B",
         "Later Headlined": "Rough Trade Below (Jun 2026)", "Shows Before": 20, "Shows Since": 180, "Glow-up": "x"},
        {"Artist": "Unmeasured", "Opened For": "X", "Date": "Jan 01, 2020", "Venue": "V",
         "Later Headlined": "", "Shows Before": None, "Shows Since": None, "Glow-up": ""},
    ])
    t = rank_early_table(snap)
    assert list(t["Artist"]) == ["Jalen Ngonda", "Sophisticuffs", "Unmeasured"]
    assert list(t["Glow-up"]) == ["×9.0", "Too few shows logged", ""]


def test_drop_covers_from_rare_table():
    from analytics.career import drop_covers
    rows = [{"eventDate": "2025-09-15", "artist": "Vampire Weekend", "artist_mbid": "v", "venue": "W",
             "city": "C", "state": "NJ", "lat": 1, "long": 1, "song_count": 2, "tour": None, "url": "",
             "songs": json.dumps(["Harmony Hall", "Jokerman"]),
             "covers": json.dumps([{"song": "Jokerman", "original": "Bob Dylan"}])}]
    df, _, _ = process_attendance(pd.DataFrame(rows))
    table = pd.DataFrame([{"Song": "Jokerman", "Artist": "Vampire Weekend", "Times Played": 1},
                          {"Song": "Harmony Hall", "Artist": "Vampire Weekend", "Times Played": 50},
                          {"Song": "Jokerman", "Artist": "Bob Dylan", "Times Played": 900}])
    out = drop_covers(table, df)
    assert list(zip(out["Song"], out["Artist"])) == [("Harmony Hall", "Vampire Weekend"), ("Jokerman", "Bob Dylan")]
    assert len(drop_covers(table, df.drop(columns="covers"))) == 3     # no cover info: nothing dropped


def test_floor_by_times_heard():
    from analytics.career import floor_by_times_heard
    df = _rows([("2025-10-01", "MSG", [("Lorde", "l", 3)]), ("2025-12-17", "Barclays", [("Lorde", "l", 3)])])
    df.loc[:, "songs"] = json.dumps(["Crazy", "Other", "Third"])
    table = pd.DataFrame([
        {"Song": "Crazy", "Artist": "Lorde", "Times Played": 1, "Played In": "1 of their last 200 shows", "n": 200},
        {"Song": "Deep", "Artist": "Lorde", "Times Played": 1, "Played In": "1 of their last 200 shows", "n": 200},
        {"Song": "Other", "Artist": "Lorde", "Times Played": 50, "Played In": "50 of their last 200 shows", "n": 200}])
    out = floor_by_times_heard(table, df).set_index("Song")
    assert out.loc["Crazy", "Times Played"] == 2 and out.loc["Crazy", "Played In"] == "2 of their last 200 shows"
    assert out.loc["Deep", "Times Played"] == 1 and out.loc["Other", "Times Played"] == 50
    assert list(floor_by_times_heard(table, df)["Song"]) == ["Deep", "Crazy", "Other"]


def test_short_setlists_are_ignored():
    from datetime import date, timedelta
    from analytics.career import career_rare_songs, floor_by_times_heard, summarize_history
    base = date(2025, 6, 1)
    full = [(base - timedelta(days=i), ["A", "B", "C"]) for i in range(25)]
    snippets = [(base - timedelta(days=100 + i), ["A"]) for i in range(5)]   # 1-song festival snippets
    h = summarize_history(_fake_history(full + snippets))
    assert h["n"] == 25 and h["counts"]["a"] == 25                         # snippets not counted
    rows = [{"eventDate": "2025-06-01", "artist": "Band", "artist_mbid": "b", "venue": "V", "city": "C",
             "state": "NY", "lat": 1, "long": 1, "song_count": 3, "tour": None, "url": "",
             "songs": json.dumps(["A", "B", "C"])},
            {"eventDate": "2025-05-30", "artist": "Band", "artist_mbid": "b", "venue": "Fest", "city": "C",
             "state": "NY", "lat": 1, "long": 1, "song_count": 2, "tour": None, "url": "",
             "songs": json.dumps(["A", "Snippet"])}]
    df, _, _ = process_attendance(pd.DataFrame(rows))
    table, stats = career_rare_songs(df, {"b": h})
    assert "Snippet" not in set(table["Song"]) and stats["skipped_short"] == 1 and stats["scored_shows"] == 1
    floored = floor_by_times_heard(pd.DataFrame([{"Song": "Snippet", "Artist": "Band", "Times Played": 0,
                                                  "Played In": "0 of x", "n": 25}]), df)
    assert floored.iloc[0]["Times Played"] == 0                                   # 2-song show ignored


def test_sortable_dates():
    from data.display import sortable_dates
    df = pd.DataFrame({"Date": ["Apr 09, 2026", "Aug 05, 2017", "Dec 31, 2019"],
                       "Heard On": ["12-31-2019", "01-02-2020", "09-17-2026"],
                       "Last Played": ["01-10-26", "12-31-25", "06-01-24"],
                       "Your Last Time": ["Aug 2026", "Jan 2019", "Sep 2025"],
                       "Song": ["x", "y", "z"]})
    out, fmts = sortable_dates(df)
    assert list(out.sort_values("Date")["Date"].dt.year) == [2017, 2019, 2026]
    assert list(out.sort_values("Heard On")["Song"]) == ["x", "y", "z"]
    assert list(out["Last Played"].dt.year) == [2026, 2025, 2024]
    assert fmts["Your Last Time"] == "MMM YYYY" and fmts["Date"] == "MMM D, YYYY"
    assert out["Song"].tolist() == ["x", "y", "z"] and "Song" not in fmts
    assert df["Date"].tolist()[0] == "Apr 09, 2026"                                # original untouched
    assert sortable_dates(pd.DataFrame(columns=["Date"]))[1] == {}
