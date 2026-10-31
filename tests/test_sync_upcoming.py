"""scripts/sync_upcoming.py: reading Upcoming Shows from a saved setlist.fm attended page."""
from pathlib import Path

import pytest

from scripts.sync_upcoming import PageError, _split_place, main, parse_upcoming, to_csv

FIXTURE = Path(__file__).parent / "fixtures" / "setlistfm_attended_page.html"


def test_parse_upcoming_reads_only_the_upcoming_list():
    rows = parse_upcoming(FIXTURE.read_text(encoding="utf-8"))
    assert len(rows) == 16  # the page's "Upcoming Shows (16)"; the attended Gryffin show is left out
    assert rows[0] == {"date": "2026-11-11", "artist": "Michigander",
                       "venue": "Music Hall of Williamsburg", "city": "Brooklyn", "state": "NY"}
    assert {"date": "2026-12-08", "artist": "Jalen Ngonda", "venue": "Webster Hall",
            "city": "New York", "state": "NY"} in rows
    assert any(r["artist"] == "Uncle Roy & Spice" for r in rows)  # &amp; unescaped
    assert all(r["artist"] != "Gryffin" for r in rows)


def test_split_place_handles_commas_and_countries_without_states():
    assert _split_place("Webster Hall, New York, NY, USA") == ("Webster Hall", "New York", "NY")
    assert _split_place("Hammersmith Apollo, London, England") == ("Hammersmith Apollo", "London", "")
    assert _split_place("Bowery Ballroom, Inc., New York, NY, USA") == (
        "Bowery Ballroom, Inc.", "New York", "NY")


def test_bot_check_page_is_an_error_not_an_empty_list():
    with pytest.raises(PageError):
        parse_upcoming("<html><body>Please verify you are human</body></html>")
    assert parse_upcoming('<h2 class="x">Attended Shows (<span>3</span>)</h2>') == []


def test_to_csv_sorts_by_date_and_matches_the_app_format():
    out = to_csv([{"date": "2027-01-01", "artist": "B", "venue": "V", "city": "C", "state": ""},
                  {"date": "2026-12-01", "artist": "A", "venue": "V", "city": "C", "state": "NY"}])
    assert out.splitlines() == ["date,artist,venue,city,state", "2026-12-01,A,V,C,NY",
                                "2027-01-01,B,V,C,"]


def test_main_writes_csv_from_file(tmp_path, monkeypatch):
    import scripts.sync_upcoming as su
    target = tmp_path / "upcoming_shows.csv"
    monkeypatch.setattr(su, "UPCOMING_CSV", target)
    assert main(["--file", str(FIXTURE)]) == 0
    assert target.read_text().count("\n") == 17
    assert main(["--file", str(FIXTURE)]) == 0  # second run: already up to date


def test_newest_saved_page_picks_latest_chrome_save(tmp_path):
    import os
    from scripts.sync_upcoming import newest_saved_page
    assert newest_saved_page(tmp_path) is None
    old = tmp_path / "raisinwarrior's attended concerts _ setlist.fm.html"
    new = tmp_path / "raisinwarrior's attended concerts _ setlist.fm (1).html"
    (tmp_path / "unrelated.html").write_text("x")
    for i, p in enumerate((old, new)):
        p.write_text("x")
        os.utime(p, (1000 + i, 1000 + i))
    assert newest_saved_page(tmp_path) == new
