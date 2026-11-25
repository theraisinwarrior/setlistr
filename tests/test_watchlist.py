"""analytics/watchlist.py and the watchlist.csv loader."""
import pandas as pd

from analytics.watchlist import COLUMNS, on_sale_label, watchlist_csv_line, watchlist_table

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


def test_csv_line_round_trips_commas():
    line = watchlist_csv_line("Crosby, Stills & Nash", "2027-04-01", notes="presale, Tue")
    assert line == '"Crosby, Stills & Nash",2027-04-01,,,,,,"presale, Tue"'
    import io
    row = pd.read_csv(io.StringIO("artist,date,venue,city,state,on_sale,link,notes\n" + line), dtype=str)
    assert row.iloc[0]["artist"] == "Crosby, Stills & Nash"


def test_loader_handles_header_only_and_missing_file(tmp_path, monkeypatch):
    import data.store as store
    monkeypatch.chdir(tmp_path)
    assert store.load_watchlist_csv().empty  # missing file
    (tmp_path / "watchlist.csv").write_text("artist,date,venue,city,state,on_sale,link,notes\n")
    assert store.load_watchlist_csv().empty
    (tmp_path / "watchlist.csv").write_text("Artist,Date\n Big Thief ,2027-02-02\n,2027-01-01\n")
    df = store.load_watchlist_csv()
    assert list(df["artist"]) == ["Big Thief"]
    assert pd.isna(df.iloc[0]["on_sale"])
