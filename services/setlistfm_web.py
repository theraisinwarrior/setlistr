"""Read the public "N users were there" count from a setlist.fm setlist page.

The setlist.fm API has no attendance field, so this reads the web page. It is deliberately
gentle (one page at a time, with a pause, identifying itself) and stops at the first sign
of being refused. If setlist.fm changes the page wording, parsing returns None.
"""
import html as html_lib
import re
import time

import requests

ALLOWED_PREFIX = "https://www.setlist.fm/setlist/"
USER_AGENT = "Setlistr personal concert-stats app (reads the public attendance count of my own shows)"
PAUSE_SECONDS = 1.2

_TAGS = re.compile(r"<[^>]+>")
_COUNT = re.compile(r"(\d[\d,.]*)\s+(?:[A-Za-z.]+\s+){0,2}users?\s+(?:were|was)\s+there", re.I)
_CHALLENGE = ("just a moment", "enable javascript and cookies", "attention required", "cf-chl",
              "verify you are human", "access denied")


class AttendanceBlocked(Exception):
    """setlist.fm refused or throttled the request, so the scan should stop."""


def parse_attendance_count(page_html: str):
    """Return the 'N users were there' number from a setlist page, or None if absent."""
    text = html_lib.unescape(_TAGS.sub(" ", page_html or ""))
    text = re.sub(r"\s+", " ", text)
    m = _COUNT.search(text)
    if not m:
        return None
    digits = re.sub(r"\D", "", m.group(1))
    return int(digits) if digits else None


def fetch_attendance_count(url: str):
    """Fetch one setlist page and return its attendance count (None if not found).

    Raises AttendanceBlocked on 403/429/5xx or network trouble, so callers can stop and
    never cache a failure.
    """
    if not isinstance(url, str) or not url.startswith(ALLOWED_PREFIX):
        return None
    try:
        resp = requests.get(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "en"}, timeout=12)
    except requests.RequestException as e:
        raise AttendanceBlocked(f"Could not reach setlist.fm: {e}")
    time.sleep(PAUSE_SECONDS)
    if resp.status_code == 404:
        return None
    if resp.status_code in (403, 429) or resp.status_code >= 500:
        raise AttendanceBlocked(f"setlist.fm answered {resp.status_code}")
    if resp.status_code != 200:
        return None
    count = parse_attendance_count(resp.text)
    if count is None and any(m in resp.text[:20000].lower() for m in _CHALLENGE):
        raise AttendanceBlocked("setlist.fm served a bot-check page instead of the setlist")
    return count


def diagnose(url: str) -> dict:
    """One-off look at what setlist.fm returns for a page, for troubleshooting."""
    try:
        resp = requests.get(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "en"}, timeout=12)
    except requests.RequestException as e:
        return {"error": str(e)}
    body = resp.text or ""
    low = body.lower()
    i = low.find("were there")
    j = low.find("i was there")
    title = re.search(r"<title[^>]*>(.*?)</title>", body, re.I | re.S)
    return {
        "status": resp.status_code, "bytes": len(body),
        "title": re.sub(r"\s+", " ", title.group(1)).strip() if title else "",
        "parsed_count": parse_attendance_count(body),
        "has 'I was there'": j >= 0, "has 'were there'": i >= 0,
        "snippet": re.sub(r"\s+", " ", body[max(0, i - 200): i + 60]) if i >= 0 else body[:300],
    }
