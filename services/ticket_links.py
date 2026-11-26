"""Turn a ticket link (or an artist search) into watchlist fields. No Streamlit imports.

Sources, best first:
1. SeatGeek links and artist search, through SeatGeek's free API (needs SEATGEEK_CLIENT_ID).
2. Any other ticket page (Dice, AXS, Eventbrite, venue sites...): most embed a schema.org
   "Event" block for search engines, which has the artist, date, venue and city.
3. Ticketmaster / Live Nation pages block apps, but their links end in
   "...-new-york-12-08-2026/event/...", so the same night is looked up on SeatGeek and matched
   by act name. Without a SeatGeek ID, the link text alone gives the date and state.

Every function returns a dict with the watchlist fields (artist, date, venue, city, state,
on_sale, link, notes), blank where unknown, so the form can be filled in and corrected.
"""
import html as html_lib
import json
import re
from urllib.parse import urlparse

from datetime import date, timedelta

import requests

TIMEOUT = 8
SG_API = "https://api.seatgeek.com/2"
BROWSER_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
}

STATES = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR", "california": "CA",
    "colorado": "CO", "connecticut": "CT", "delaware": "DE", "district of columbia": "DC",
    "florida": "FL", "georgia": "GA", "hawaii": "HI", "idaho": "ID", "illinois": "IL",
    "indiana": "IN", "iowa": "IA", "kansas": "KS", "kentucky": "KY", "louisiana": "LA",
    "maine": "ME", "maryland": "MD", "massachusetts": "MA", "michigan": "MI", "minnesota": "MN",
    "mississippi": "MS", "missouri": "MO", "montana": "MT", "nebraska": "NE", "nevada": "NV",
    "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM", "new york": "NY",
    "north carolina": "NC", "north dakota": "ND", "ohio": "OH", "oklahoma": "OK", "oregon": "OR",
    "pennsylvania": "PA", "rhode island": "RI", "south carolina": "SC", "south dakota": "SD",
    "tennessee": "TN", "texas": "TX", "utah": "UT", "vermont": "VT", "virginia": "VA",
    "washington": "WA", "west virginia": "WV", "wisconsin": "WI", "wyoming": "WY",
}


# Neighborhood-style city names some sites use, mapped to the names upcoming_shows.csv uses
CITY_NAMES = {"Manhattan": "New York", "New York City": "New York", "NYC": "New York"}


class LinkError(Exception):
    """A problem reading a link, with a message that is safe to show the user."""


def blank(link: str = "") -> dict:
    return {"artist": "", "date": "", "venue": "", "city": "", "state": "",
            "on_sale": "", "link": link, "notes": ""}


def _day(value) -> str:
    """'2026-12-08T19:00:00-05:00' -> '2026-12-08'; anything unreadable -> ''."""
    m = re.match(r"(\d{4}-\d{2}-\d{2})", str(value or ""))
    return m.group(1) if m else ""


def _state_code(value) -> str:
    v = str(value or "").strip()
    if len(v) == 2:
        return v.upper()
    return STATES.get(v.lower(), v)


# ---------- 1. SeatGeek API ----------

def _key(text) -> str:
    return "".join(ch for ch in str(text).lower() if ch.isalnum())


def seatgeek_event_id(url: str) -> str:
    """The event id in a SeatGeek link (.../concert/1234567), or ''."""
    if "seatgeek" not in urlparse(url).netloc.lower():
        return ""
    m = re.search(r"/(\d{5,})(?:[/?#]|$)", url)
    return m.group(1) if m else ""


def from_seatgeek_event(ev: dict, link: str = "") -> dict:
    """Watchlist fields from one SeatGeek API event."""
    out = blank(link or ev.get("url", ""))
    performers = sorted(ev.get("performers") or [], key=lambda p: not p.get("primary"))
    acts = [p.get("name", "") for p in performers if p.get("name")]
    out["artist"] = acts[0] if acts else ev.get("short_title") or ev.get("title", "")
    if len(acts) > 1:
        out["notes"] = "with " + ", ".join(acts[1:])
    if not ev.get("date_tbd"):
        out["date"] = _day(ev.get("datetime_local"))
    venue = ev.get("venue") or {}
    out["venue"] = venue.get("name", "") or ""
    out["city"] = venue.get("city", "") or ""
    out["state"] = venue.get("state", "") or ""
    status = str(ev.get("status") or "").lower()
    for word in ("cancel", "postpone", "reschedul"):
        if word in status:
            out["notes"] = f"{status.title()} on SeatGeek" + (f"; {out['notes']}" if out["notes"] else "")
    return out


def _sg_get(path: str, client_id: str, params: dict = None) -> dict:
    try:
        resp = requests.get(f"{SG_API}/{path}", params={**(params or {}), "client_id": client_id},
                            timeout=TIMEOUT)
    except requests.RequestException:
        raise LinkError("Couldn't reach SeatGeek. Try again in a minute.")
    if resp.status_code == 404:
        raise LinkError("SeatGeek doesn't know that event.")
    if resp.status_code == 429:
        raise LinkError("SeatGeek is rate-limiting requests. Try again in a minute.")
    if resp.status_code in (401, 403):
        raise LinkError("SeatGeek rejected the Client ID. Check SEATGEEK_CLIENT_ID in the app's secrets.")
    if not resp.ok:
        raise LinkError(f"SeatGeek returned an error ({resp.status_code}).")
    return resp.json()


def fetch_seatgeek_event(event_id: str, client_id: str, link: str = "") -> dict:
    return from_seatgeek_event(_sg_get(f"events/{event_id}", client_id), link)


def search_seatgeek(keyword: str, client_id: str, city: str = "", size: int = 25) -> list:
    """Upcoming concerts where an act's name contains the search, soonest first (optionally one city)."""
    params = {"q": keyword.strip(), "taxonomies.name": "concert", "sort": "datetime_local.asc",
              "per_page": size}
    if city.strip():
        params["venue.city"] = city.strip()
    events = _sg_get("events", client_id, params).get("events", []) or []
    want = _key(keyword)
    hits = [ev for ev in events
            if any(want in _key(p.get("name", "")) for p in ev.get("performers") or [])
            or want in _key(ev.get("title", ""))]
    return [from_seatgeek_event(ev) for ev in hits]


def match_link_on_seatgeek(url: str, client_id: str):
    """Find the show a ticket link points to (e.g. a Ticketmaster link) among SeatGeek's
    concerts on that date in that state, by matching act names against the link's words.
    Returns watchlist fields with the original link, or None."""
    guess = parse_url_slug(url)
    if not guess["date"]:
        return None
    day = guess["date"]
    nxt = (date.fromisoformat(day) + timedelta(days=1)).isoformat()
    params = {"taxonomies.name": "concert", "datetime_local.gte": day, "datetime_local.lt": nxt,
              "per_page": 100}
    if guess["state"]:
        params["venue.state"] = guess["state"]
    events = _sg_get("events", client_id, params).get("events", []) or []
    words = _key(guess["artist"])
    best, best_len = None, 0
    for ev in events:
        for p in ev.get("performers") or []:
            name = _key(p.get("name", ""))
            if len(name) >= 3 and name in words and len(name) > best_len:
                best, best_len = ev, len(name)
    return from_seatgeek_event(best, url) if best else None


# ---------- 2. schema.org Event data in the page ----------

def _walk(node):
    if isinstance(node, list):
        for item in node:
            yield from _walk(item)
    elif isinstance(node, dict):
        yield node
        for key in ("@graph", "subEvent", "itemListElement", "item"):
            if key in node:
                yield from _walk(node[key])


def _is_event(node: dict) -> bool:
    t = node.get("@type", "")
    types = t if isinstance(t, list) else [t]
    return any(str(x).endswith("Event") for x in types)


def _name(value) -> str:
    if isinstance(value, list):
        value = value[0] if value else ""
    if isinstance(value, dict):
        value = value.get("name", "")
    return html_lib.unescape(str(value or "")).strip()


def parse_event_html(page: str, link: str = "") -> dict:
    """Watchlist fields from a page's schema.org Event block, falling back to its og:title."""
    out = blank(link)
    events = []
    for raw in re.findall(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', page, re.S | re.I):
        try:
            data = json.loads(raw.strip())
        except ValueError:
            continue
        events += [n for n in _walk(data) if _is_event(n)]
    if events:
        ev = events[0]
        performers = ev.get("performer") or []
        performers = performers if isinstance(performers, list) else [performers]
        acts = [_name(p) for p in performers if _name(p)]
        out["artist"] = acts[0] if acts else _name(ev.get("name"))
        if len(acts) > 1:
            out["notes"] = "with " + ", ".join(acts[1:])
        out["date"] = _day(ev.get("startDate"))
        loc = ev.get("location") or {}
        loc = loc[0] if isinstance(loc, list) and loc else loc
        if isinstance(loc, dict):
            out["venue"] = _name(loc)
            addr = loc.get("address") or {}
            if isinstance(addr, dict):
                out["city"] = CITY_NAMES.get(_name(addr.get("addressLocality")),
                                             _name(addr.get("addressLocality")))
                out["state"] = _state_code(_name(addr.get("addressRegion")))
        offers = ev.get("offers") or {}
        offers = offers[0] if isinstance(offers, list) and offers else offers
        if isinstance(offers, dict):
            sale = _day(offers.get("validFrom") or offers.get("availabilityStarts"))
            if sale and (not out["date"] or sale < out["date"]):  # Songkick puts the show date here
                out["on_sale"] = sale
        status = str(ev.get("eventStatus", ""))
        if status.endswith(("Cancelled", "Postponed", "Rescheduled")):
            out["notes"] = status.rsplit("/", 1)[-1].replace("Event", "") + (
                f"; {out['notes']}" if out["notes"] else "")
        return out
    m = (re.search(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)', page, re.I)
         or re.search(r"<title[^>]*>(.*?)</title>", page, re.I | re.S))
    if m:
        out["artist"] = re.split(r"\s+[|–—-]\s+|\s+Tickets\b", html_lib.unescape(m.group(1)).strip())[0]
    return out


# ---------- 3. the link's own text ----------

def parse_url_slug(url: str) -> dict:
    """Best guess from a link like /noah-kahan-east-rutherford-new-jersey-06-18-2027/event/...

    The date and state are reliable; the rest of the words are left as the artist for you
    to trim, since the link doesn't say where the artist's name ends and the city begins.
    """
    out = blank(url)
    path = urlparse(url).path
    slug = max(path.strip("/").split("/"), key=lambda part: part.count("-"), default="")
    words = [w for w in slug.lower().split("-") if w]
    if len(words) < 2:
        return out
    m = re.search(r"(\d{2})-(\d{2})-(\d{4})$", "-".join(words))
    if m:
        out["date"] = f"{m.group(3)}-{m.group(1)}-{m.group(2)}"
        words = words[:-3]
    for size in (3, 2, 1):  # "district of columbia", "new york", "texas"
        if len(words) > size and " ".join(words[-size:]) in STATES:
            out["state"] = STATES[" ".join(words[-size:])]
            words = words[:-size]
            break
    words = [w for w in words if w not in ("tickets", "ticket", "event", "events")]
    out["artist"] = " ".join(w.capitalize() for w in words)
    return out


def parse_songkick_slug(url: str) -> dict:
    """Songkick links name the act and venue: /concerts/43456599-leon-bridges-at-madison-square-garden."""
    out = blank(url)
    m = re.search(r"songkick\.com/concerts/\d+-([a-z0-9-]+)", url.lower())
    if not m:
        return out
    artist, _, venue = m.group(1).partition("-at-")
    out["artist"] = " ".join(w.capitalize() for w in artist.split("-") if w)
    out["venue"] = " ".join(w.capitalize() for w in venue.split("-") if w)
    return out


def match_on_seatgeek_by_venue(guess: dict, client_id: str):
    """The artist's next SeatGeek show at the guessed venue, keeping the original link. Or None."""
    venue = _key(guess["venue"])
    for show in search_seatgeek(guess["artist"], client_id):
        if venue and (venue in _key(show["venue"]) or _key(show["venue"]) in venue):
            return {**show, "link": guess["link"]}
    return None


# ---------- putting it together ----------

def lookup_link(url: str, sg_client_id: str = "") -> dict:
    """Best watchlist fields for a pasted link, plus a 'source' saying how they were found."""
    url = url.strip()
    if not re.match(r"https?://", url):
        raise LinkError("That doesn't look like a link. It should start with https://")
    sg_id = seatgeek_event_id(url)
    if sg_id and sg_client_id:
        try:
            return {**fetch_seatgeek_event(sg_id, sg_client_id, url), "source": "SeatGeek"}
        except LinkError:
            pass  # fall through to reading the page / the link text
    try:
        resp = requests.get(url, headers=BROWSER_HEADERS, timeout=TIMEOUT)
        if resp.ok and "html" in resp.headers.get("Content-Type", "html"):
            found = parse_event_html(resp.text, url)
            if found["artist"] and (found["date"] or found["venue"]):
                return {**found, "source": "the ticket page"}
    except requests.RequestException:
        pass
    songkick = parse_songkick_slug(url)
    if sg_client_id:  # e.g. Ticketmaster, whose pages block apps: find the same show on SeatGeek
        try:
            found = (match_on_seatgeek_by_venue(songkick, sg_client_id) if songkick["artist"]
                     else match_link_on_seatgeek(url, sg_client_id))
        except LinkError:
            found = None
        if found:
            return {**found, "source": "SeatGeek's listing for that show (double-check it's the right one)"}
    if songkick["artist"]:
        return {**songkick, "source": "the link text (add the date)"}
    guess = parse_url_slug(url)
    if guess["artist"] or guess["date"]:
        return {**guess, "source": "the link text (double-check the artist name)"}
    raise LinkError("Couldn't read that page (some ticket sites block apps). Fill in the details below.")
