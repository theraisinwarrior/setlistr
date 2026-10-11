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
_COUNT = re.compile(r"([\d][\d,.\s]*)\s+(?:setlist\.fm\s+)?users?\s+(?:were|was)\s+there", re.I)


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
    return parse_attendance_count(resp.text)
