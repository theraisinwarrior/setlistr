"""analytics/watchlist_calendar.py: the Apple Calendar feed."""
import pandas as pd

from analytics.watchlist_calendar import watchlist_ics


def _unfold(ics):
    return ics.replace("\r\n ", "")


def test_only_dated_shows_without_tickets_with_two_alerts():
    df = pd.DataFrame([
        {"artist": "Big Thief", "date": "2027-04-10", "venue": "Kings Theatre", "city": "Brooklyn",
         "state": "NY", "link": "https://seatgeek.com/x", "notes": "with Fenne Lily", "status": ""},
        {"artist": "Bought Band", "date": "2027-05-01", "status": "tickets"},
        {"artist": "No Date Band", "date": "", "status": ""},
    ])
    ics = _unfold(watchlist_ics(df, now="2026-11-26"))
    assert ics.count("BEGIN:VEVENT") == 1 and "Bought Band" not in ics and "No Date Band" not in ics
    assert "DTSTART:20270410T200000" in ics and "SUMMARY:👀 Big Thief" in ics
    assert "LOCATION:Kings Theatre\\, Brooklyn\\, NY" in ics
    assert "with Fenne Lily" in ics and "URL:https://seatgeek.com/x" in ics
    assert ics.count("BEGIN:VALARM") == 2 and "TRIGGER:-P14D" in ics and "TRIGGER:-P7D" in ics


def test_same_show_keeps_its_id_and_lines_are_folded():
    df = pd.DataFrame([{"artist": "A" * 200, "date": "2027-01-01"}])
    a, b = watchlist_ics(df, now="2026-11-26"), watchlist_ics(df, now="2026-12-01")
    uid = [ln for ln in a.splitlines() if ln.startswith("UID:")]
    assert uid == [ln for ln in b.splitlines() if ln.startswith("UID:")]
    assert all(len(ln.encode()) <= 75 for ln in a.split("\r\n"))


def test_empty_watchlist_is_a_valid_empty_calendar():
    ics = watchlist_ics(pd.DataFrame())
    assert ics.startswith("BEGIN:VCALENDAR") and ics.rstrip().endswith("END:VCALENDAR")
    assert "VEVENT" not in ics


def test_saving_the_watchlist_updates_the_calendar_only_when_it_changes(monkeypatch):
    import data.store as store
    import services.github_store as gh
    files = {"watchlist.csv": "artist,date\nOld Band,2027-01-01\n", "watchlist.ics": ""}
    writes = []
    monkeypatch.setattr(gh, "read_file", lambda repo, path, token: (files[path], "sha"))

    def fake_write(repo, path, token, text, sha, message):
        files[path] = text
        writes.append(path)
    monkeypatch.setattr(gh, "write_file", fake_write)
    store.save_watchlist("me/repo", "t", lambda df: df, "msg")
    assert writes == ["watchlist.csv", "watchlist.ics"] and "Old Band" in files["watchlist.ics"]
    store.save_watchlist("me/repo", "t", lambda df: df, "msg")
    assert writes == ["watchlist.csv", "watchlist.ics", "watchlist.csv"]  # calendar unchanged: no commit
