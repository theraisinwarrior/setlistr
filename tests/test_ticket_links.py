"""services/ticket_links.py: reading show details from ticket links (no network)."""
from pathlib import Path

import pytest

import services.ticket_links as tl

FIXTURE = Path(__file__).parent / "fixtures" / "dice_event_page.html"

TM_EVENT = {
    "name": "Noah Kahan - The Great Divide Tour", "url": "https://www.ticketmaster.com/x/event/ABC",
    "dates": {"start": {"localDate": "2027-06-18"}, "status": {"code": "onsale"}},
    "sales": {"public": {"startDateTime": "2026-12-05T15:00:00Z"}},
    "_embedded": {"venues": [{"name": "MetLife Stadium", "city": {"name": "East Rutherford"},
                              "state": {"stateCode": "NJ"}}],
                  "attractions": [{"name": "Noah Kahan"}, {"name": "Remi Wolf"}]},
}


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


def test_ticketmaster_event_fields():
    out = tl.from_ticketmaster_event(TM_EVENT, "https://link")
    assert out["artist"] == "Noah Kahan" and out["notes"] == "with Remi Wolf"
    assert (out["date"], out["venue"], out["city"], out["state"], out["on_sale"]) == (
        "2027-06-18", "MetLife Stadium", "East Rutherford", "NJ", "2026-12-05")


def test_ticketmaster_event_id_only_for_ticketmaster_links():
    assert tl.ticketmaster_event_id(
        "https://www.ticketmaster.com/noah-kahan-east-rutherford-new-jersey-06-18-2027/event/02006123ABC") == "02006123ABC"
    assert tl.ticketmaster_event_id("https://dice.fm/event/02006123ABC") == ""


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


def test_lookup_uses_ticketmaster_api_when_key_is_set(monkeypatch):
    seen = []
    monkeypatch.setattr(tl.requests, "get", lambda url, **kw: seen.append(url) or _Resp(data=TM_EVENT))
    out = tl.lookup_link("https://www.ticketmaster.com/noah-kahan-06-18-2027/event/ABC", "KEY")
    assert out["artist"] == "Noah Kahan" and out["source"] == "Ticketmaster"
    assert seen == [f"{tl.TM_API}/events/ABC.json"]


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
