"""services/ticket_links.py: reading show details from ticket links (no network)."""
from pathlib import Path

import pytest

import services.ticket_links as tl

FIXTURE = Path(__file__).parent / "fixtures" / "dice_event_page.html"

SG_EVENT = {
    "id": 6123456, "title": "Noah Kahan with Remi Wolf", "url": "https://seatgeek.com/noah-kahan-tickets/x/concert/6123456",
    "datetime_local": "2027-06-18T19:00:00", "date_tbd": False, "status": "normal",
    "venue": {"name": "MetLife Stadium", "city": "East Rutherford", "state": "NJ"},
    "performers": [{"name": "Remi Wolf", "primary": False}, {"name": "Noah Kahan", "primary": True}],
}
OTHER_EVENT = {**SG_EVENT, "id": 1, "title": "Noah", "performers": [{"name": "Noah", "primary": True}],
               "venue": {"name": "Small Club", "city": "Newark", "state": "NJ"}}


def test_reads_schema_org_event_from_a_ticket_page():
    out = tl.parse_event_html(FIXTURE.read_text(), "https://dice.fm/event/abc")
    assert out == {"artist": "Big Thief", "date": "2027-04-10", "venue": "Kings Theatre",
                   "city": "Brooklyn", "state": "NY", "on_sale": "2026-12-01",
                   "link": "https://dice.fm/event/abc", "notes": "with Fenne Lily"}


def test_page_without_event_data_falls_back_to_title():
    out = tl.parse_event_html("<html><title>Waxahatchee Tickets - Brooklyn Steel</title></html>")
    assert out["artist"] == "Waxahatchee" and out["date"] == ""


def test_cancelled_event_is_noted():
    page = ('<script type="application/ld+json">{"@type":"Event","name":"X","startDate":"2027-01-01",'
            '"eventStatus":"https://schema.org/EventCancelled"}</script>')
    assert tl.parse_event_html(page)["notes"].startswith("Cancelled")


def test_seatgeek_event_fields():
    out = tl.from_seatgeek_event(SG_EVENT, "https://link")
    assert out["artist"] == "Noah Kahan" and out["notes"] == "with Remi Wolf"
    assert (out["date"], out["venue"], out["city"], out["state"], out["link"]) == (
        "2027-06-18", "MetLife Stadium", "East Rutherford", "NJ", "https://link")
    assert tl.from_seatgeek_event({**SG_EVENT, "date_tbd": True})["date"] == ""


def test_seatgeek_event_id_only_for_seatgeek_links():
    assert tl.seatgeek_event_id("https://seatgeek.com/noah-kahan-tickets/east-rutherford-2027-06-18/concert/6123456") == "6123456"
    assert tl.seatgeek_event_id("https://www.ticketmaster.com/x/event/6123456") == ""


def test_url_slug_gives_date_and_state():
    out = tl.parse_url_slug(
        "https://www.ticketmaster.com/jalen-ngonda-new-york-new-york-12-08-2026/event/3B00")
    assert out["date"] == "2026-12-08" and out["state"] == "NY"
    assert out["artist"] == "Jalen Ngonda New York"  # city left in: the link doesn't say where it starts


class _Resp:
    def __init__(self, status=200, text="", data=None):
        self.status_code, self.text, self._data = status, text, data
        self.ok = status < 400
        self.headers = {"Content-Type": "text/html"}

    def json(self):
        return self._data


def test_lookup_uses_seatgeek_api_for_seatgeek_links(monkeypatch):
    seen = []
    monkeypatch.setattr(tl.requests, "get", lambda url, **kw: seen.append(url) or _Resp(data=SG_EVENT))
    out = tl.lookup_link("https://seatgeek.com/noah-kahan-tickets/x/concert/6123456", "ID")
    assert out["artist"] == "Noah Kahan" and out["source"] == "SeatGeek"
    assert seen == [f"{tl.SG_API}/events/6123456"]


def test_ticketmaster_link_is_matched_on_seatgeek(monkeypatch):
    seen = []

    def fake_get(url, params=None, **kw):
        if "ticketmaster" in url:
            return _Resp(status=403)  # Ticketmaster blocks apps
        seen.append(params)
        return _Resp(data={"events": [OTHER_EVENT, SG_EVENT]})
    monkeypatch.setattr(tl.requests, "get", fake_get)
    link = "https://www.ticketmaster.com/noah-kahan-east-rutherford-new-jersey-06-18-2027/event/02006ABC"
    out = tl.lookup_link(link, "ID")
    assert out["artist"] == "Noah Kahan" and out["venue"] == "MetLife Stadium"  # longest name match wins
    assert out["link"] == link and "SeatGeek" in out["source"]
    assert seen[0]["datetime_local.gte"] == "2027-06-18" and seen[0]["datetime_local.lt"] == "2027-06-19"
    assert seen[0]["venue.state"] == "NJ"


def test_search_keeps_only_shows_by_that_artist(monkeypatch):
    unrelated = {**SG_EVENT, "title": "Tribute Night", "performers": [{"name": "Kahan Tribute Band"}]}
    monkeypatch.setattr(tl.requests, "get", lambda url, **kw: _Resp(data={"events": [SG_EVENT, unrelated]}))
    assert [r["artist"] for r in tl.search_seatgeek("noah kahan", "ID")] == ["Noah Kahan"]


def test_lookup_falls_back_to_link_text_when_page_is_blocked(monkeypatch):
    monkeypatch.setattr(tl.requests, "get", lambda url, **kw: _Resp(status=403))
    out = tl.lookup_link("https://www.ticketmaster.com/greta-van-fleet-brooklyn-new-york-03-08-2027/event/1")
    assert out["date"] == "2027-03-08" and "double-check" in out["source"]


def test_lookup_reads_the_page(monkeypatch):
    monkeypatch.setattr(tl.requests, "get", lambda url, **kw: _Resp(text=FIXTURE.read_text()))
    assert tl.lookup_link("https://dice.fm/event/abc")["venue"] == "Kings Theatre"


def test_lookup_rejects_non_links():
    with pytest.raises(tl.LinkError):
        tl.lookup_link("big thief")
