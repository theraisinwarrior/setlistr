"""Turn a ticket link (or an artist search) into watchlist fields. No Streamlit imports.

Three sources, best first:
1. Ticketmaster / Live Nation links and artist search, through Ticketmaster's free Discovery
   API (needs TICKETMASTER_API_KEY). Their web pages block scripts, so this is the reliable route.
2. Any other ticket page (Dice, AXS, Eventbrite, venue sites...): most embed a schema.org
   "Event" block for search engines, which has the artist, date, venue and city.
3. The link's own text: Ticketmaster-style links end in "...-new-york-12-08-2026/event/...",
   which gives at least a date and state when the page can't be read.

Every function returns a dict with the watchlist fields (artist, date, venue, city, state,
on_sale, link, notes), blank where unknown, so the form can be filled in and corrected.
"""
import html as html_lib
import json
import re
from urllib.parse import urlparse

import requests

TIMEOUT = 8
TM_API = "https://app.ticketmaster.com/discovery/v2"
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


# ---------- 1. Ticketmaster Discovery API ----------

def ticketmaster_event_id(url: str) -> str:
    """The event id in a Ticketmaster / Live Nation link, or ''."""
    host = urlparse(url).netloc.lower()
    if "ticketmaster" not in host and "livenation" not in host:
        return ""
    m = re.search(r"/event/([A-Za-z0-9]+)", url)
    return m.group(1) if m else ""


def from_ticketmaster_event(ev: dict, link: str = "") -> dict:
    """Watchlist fields from one Discovery API event."""
    out = blank(link or ev.get("url", ""))
    emb = ev.get("_embedded", {}) or {}
    acts = [a.get("name", "") for a in emb.get("attractions", []) or [] if a.get("name")]
    out["artist"] = acts[0] if acts else ev.get("name", "")
    if len(acts) > 1:
        out["notes"] = "with " + ", ".join(acts[1:])
    dates = ev.get("dates", {}) or {}
    out["date"] = _day((dates.get("start") or {}).get("localDate"))
    status = (dates.get("status") or {}).get("code", "")
    if status in ("cancelled", "postponed", "rescheduled"):
        out["notes"] = f"{status.title()} on Ticketmaster" + (f"; {out['notes']}" if out["notes"] else "")
    out["on_sale"] = _day(((ev.get("sales") or {}).get("public") or {}).get("startDateTime"))
    venues = emb.get("venues", []) or []
    if venues:
        v = venues[0]
        out["venue"] = v.get("name", "")
        out["city"] = (v.get("city") or {}).get("name", "")
        out["state"] = (v.get("state") or {}).get("stateCode", "")
    return out


def _tm_get(path: str, api_key: str, params: dict = None) -> dict:
    try:
        resp = requests.get(f"{TM_API}/{path}", params={**(params or {}), "apikey": api_key},
                            timeout=TIMEOUT)
    except requests.RequestException:
        raise LinkError("Couldn't reach Ticketmaster. Try again in a minute.")
    if resp.status_code == 404:
        raise LinkError("Ticketmaster doesn't know that event (it may be a resale or partner link).")
    if resp.status_code == 429:
        raise LinkError("Ticketmaster is rate-limiting requests. Try again in a minute.")
    if resp.status_code in (401, 403):
        raise LinkError("Ticketmaster rejected the API key. Check TICKETMASTER_API_KEY in the app's secrets.")
    if not resp.ok:
        raise LinkError(f"Ticketmaster returned an error ({resp.status_code}).")
    return resp.json()


def fetch_ticketmaster_event(event_id: str, api_key: str, link: str = "") -> dict:
    return from_ticketmaster_event(_tm_get(f"events/{event_id}.json", api_key), link)


def search_ticketmaster(keyword: str, api_key: str, city: str = "", size: int = 20) -> list:
    """Upcoming music events matching an artist name, soonest first (optionally in one city)."""
    params = {"keyword": keyword.strip(), "classificationName": "music", "sort": "date,asc",
              "size": size}
    if city.strip():
        params["city"] = city.strip()
    data = _tm_get("events.json", api_key, params)
    events = (data.get("_embedded") or {}).get("events", []) or []
    return [from_ticketmaster_event(ev) for ev in events]


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
                out["city"] = _name(addr.get("addressLocality"))
                out["state"] = _state_code(_name(addr.get("addressRegion")))
        offers = ev.get("offers") or {}
        offers = offers[0] if isinstance(offers, list) and offers else offers
        if isinstance(offers, dict):
            sale = _day(offers.get("validFrom") or offers.get("availabilityStarts"))
            if sale and (not out["date"] or sale <= out["date"]):
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


# ---------- putting it together ----------

def lookup_link(url: str, tm_api_key: str = "") -> dict:
    """Best watchlist fields for a pasted link, plus a 'source' saying how they were found."""
    url = url.strip()
    if not re.match(r"https?://", url):
        raise LinkError("That doesn't look like a link. It should start with https://")
    tm_id = ticketmaster_event_id(url)
    if tm_id and tm_api_key:
        try:
            return {**fetch_ticketmaster_event(tm_id, tm_api_key, url), "source": "Ticketmaster"}
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
    guess = parse_url_slug(url)
    if guess["artist"] or guess["date"]:
        return {**guess, "source": "the link text (double-check the artist name)"}
    raise LinkError("Couldn't read that page (some ticket sites block apps). Fill in the details below.")
