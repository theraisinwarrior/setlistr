"""analytics/watchlist.py and the watchlist.csv loader."""
import pandas as pd

from analytics.watchlist import COLUMNS, on_sale_label, watchlist_table

TODAY = "2026-11-25"


def _watch(rows):
    return pd.DataFrame(rows)


def test_empty_watchlist_gives_empty_table():
    assert list(watchlist_table(pd.DataFrame(), None, TODAY).columns) == COLUMNS
    assert watchlist_table(None, None, TODAY).empty


def test_dated_shows_first_then_tba_and_past_shows_drop_off():
    df = _watch([
        {"artist": "Band TBA"},
        {"artist": "Band Later", "date": "2027-03-01", "venue": "V", "city": "Brooklyn", "state": "NY"},
        {"artist": "Band Soon", "date": "2026-12-01"},
        {"artist": "Band Gone", "date": "2026-11-01"},
    ])
    out = watchlist_table(df, None, TODAY)
    assert list(out["Artist"]) == ["Band Soon", "Band Later", "Band TBA"]
    assert out.iloc[2]["When"] == "Date TBA" and pd.isna(out.iloc[2]["Date"])
    assert out.iloc[1]["City"] == "Brooklyn, NY"
    assert set(out["Status"]) == {"👀 Interested"}


def test_marks_shows_you_already_have_tickets_for():
    tickets = pd.DataFrame([{"eventDate": "2027-01-14", "artist": "Bright Eyes", "venue": "Paramount"}])
    df = _watch([
        {"artist": "bright eyes"},                          # no date: any upcoming ticket counts
        {"artist": "Bright Eyes", "date": "2027-01-14"},    # same date
        {"artist": "Bright Eyes", "date": "2027-05-01"},    # a different night
    ])
    out = watchlist_table(df, tickets, TODAY)
    status = dict(zip(out["Date"].fillna(""), out["Status"]))
    assert status["2027-01-14"] == "🎟️ Got tickets"
    assert status["2027-05-01"] == "👀 Interested"
    assert status[""] == "🎟️ Got tickets"


def test_on_sale_label():
    assert on_sale_label(pd.NaT, TODAY) == ""
    assert on_sale_label(pd.Timestamp("2026-11-20"), TODAY) == "On sale now"
    assert on_sale_label(pd.Timestamp("2026-11-26"), TODAY) == "On sale tomorrow"
    assert on_sale_label(pd.Timestamp("2026-11-30"), TODAY) == "On sale in 5 days"


def test_loader_handles_header_only_and_missing_file(tmp_path, monkeypatch):
    import data.store as store
    monkeypatch.chdir(tmp_path)
    assert store.load_watchlist_csv().empty  # missing file
    (tmp_path / "watchlist.csv").write_text("artist,date,venue,city,state,on_sale,link,notes\n")
    assert store.load_watchlist_csv().empty
    (tmp_path / "watchlist.csv").write_text("Artist,Date\n Big Thief ,2027-02-02\n,2027-01-01\n")
    df = store.load_watchlist_csv()
    assert list(df["artist"]) == ["Big Thief"]
    assert df.iloc[0]["on_sale"] == ""


def test_watchlist_csv_round_trip_keeps_commas_and_blanks():
    from data.store import parse_watchlist, watchlist_to_csv
    df = pd.DataFrame([{"artist": "Crosby, Stills & Nash", "date": "", "notes": "presale, Tue"},
                       {"artist": "  "}])
    text = watchlist_to_csv(df)
    assert text.splitlines()[0] == "artist,date,venue,city,state,on_sale,link,notes,status"
    back = parse_watchlist(text)
    assert len(back) == 1 and back.iloc[0]["artist"] == "Crosby, Stills & Nash"
    assert back.iloc[0]["notes"] == "presale, Tue" and back.iloc[0]["date"] == ""
    assert watchlist_table(back, None, TODAY).iloc[0]["When"] == "Date TBA"


def test_save_watchlist_rereads_github_and_commits(monkeypatch):
    import data.store as store
    import services.github_store as gh
    calls = {}
    monkeypatch.setattr(gh, "read_file", lambda repo, path, token: (
        ("artist,date\nOld Band,2027-01-01\n", "sha1") if path == "watchlist.csv" else ("", None)))

    def fake_write(repo, path, token, text, sha, message):
        if path == "watchlist.csv":
            calls.update(text=text, sha=sha, message=message, path=path)
    monkeypatch.setattr(gh, "write_file", fake_write)
    row = {"artist": "New Band", "date": "2027-02-02"}
    store.save_watchlist("me/repo", "token", lambda df: pd.concat([df, pd.DataFrame([row])]), "Watchlist: add")
    assert calls["sha"] == "sha1" and calls["path"] == "watchlist.csv"
    assert "Old Band,2027-01-01" in calls["text"] and "New Band,2027-02-02" in calls["text"]


def test_bought_shows_move_to_tickets_with_openers():
    from analytics.upcoming import upcoming_table
    from analytics.watchlist import ticket_rows
    df = _watch([
        {"artist": "Leon Bridges", "date": "2027-05-01", "venue": "Madison Square Garden", "city": "New York",
         "state": "NY", "notes": "with El Michels Affair, Mari Froes", "status": "tickets"},
        {"artist": "Big Thief", "date": "2027-04-10", "status": ""},
        {"artist": "Undated Band", "date": "", "status": "tickets"},
    ])
    rows = ticket_rows(df)
    assert list(rows["artist"]) == ["Leon Bridges", "El Michels Affair", "Mari Froes"]
    up = upcoming_table(rows, today=TODAY)
    assert up.iloc[0]["Lineup"] == "Leon Bridges, El Michels Affair, Mari Froes"
    out = watchlist_table(df, rows, TODAY, keep_row=True)
    # the dated bought show left the watchlist; the undated one stays, marked
    assert list(out["Artist"]) == ["Big Thief", "Undated Band"]
    assert out.set_index("Artist").loc["Undated Band", "Status"] == "🎟️ Got tickets"
    assert list(out["_row"]) == [1, 2]
