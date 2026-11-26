"""watchlist.ics: a calendar feed of dated Want to See shows, for Apple Calendar. No Streamlit.

Only shows with a date that aren't marked as bought (status "tickets") are included, so a show
leaves the calendar when you press Got tickets. Each event has alerts 2 weeks and 1 week before.
Times are "floating" (no time zone), so 8 PM shows as 8 PM wherever the calendar is.
"""
import hashlib

import pandas as pd

from analytics.watchlist import TICKETS

ALERT_DAYS = (14, 7)
START, END = "T200000", "T230000"  # set times aren't known: 8-11 PM


def _escape(text) -> str:
    text = "" if text is None or (isinstance(text, float) and pd.isna(text)) else str(text)
    return (text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
            .replace("\r\n", "\\n").replace("\n", "\\n"))


def _fold(line: str) -> list:
    """iCalendar lines longer than 75 bytes continue on the next line after a space."""
    out, raw = [], line.encode("utf-8")
    while len(raw) > 75:
        cut = 75
        while (raw[cut] & 0xC0) == 0x80:  # don't split a multi-byte character
            cut -= 1
        out.append(raw[:cut].decode("utf-8"))
        raw = b" " + raw[cut:]
    out.append(raw.decode("utf-8"))
    return out


def watchlist_ics(df_watch: pd.DataFrame, now=None) -> str:
    """The whole .ics file for the watchlist (an empty calendar if nothing qualifies)."""
    stamp = pd.Timestamp(now or pd.Timestamp.now('UTC')).strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Setlistr//Watchlist//EN",
             "CALSCALE:GREGORIAN", "METHOD:PUBLISH", "X-WR-CALNAME:Setlistr Watchlist",
             "X-PUBLISHED-TTL:PT6H", "REFRESH-INTERVAL;VALUE=DURATION:PT6H"]
    rows = [] if df_watch is None or df_watch.empty else df_watch.to_dict("records")
    for r in rows:
        day = pd.to_datetime(r.get("date"), errors="coerce")
        artist = str(r.get("artist") or "").strip()
        if pd.isna(day) or not artist or str(r.get("status") or "").strip().lower() == TICKETS:
            continue
        ymd = day.strftime("%Y%m%d")
        place = ", ".join(str(x).strip() for x in (r.get("city"), r.get("state")) if x and not pd.isna(x))
        where = ", ".join(x for x in (str(r.get("venue") or "").strip(), place) if x)
        details = [str(r.get(k) or "").strip() for k in ("notes", "link")]
        uid = hashlib.sha1(f"{artist.lower()}|{ymd}".encode()).hexdigest()[:16]
        lines += ["BEGIN:VEVENT", f"UID:{uid}@setlistr", f"DTSTAMP:{stamp}",
                  f"DTSTART:{ymd}{START}", f"DTEND:{ymd}{END}",
                  f"SUMMARY:{_escape('👀 ' + artist)}"]
        if where:
            lines.append(f"LOCATION:{_escape(where)}")
        desc = "\n".join(["On your Setlistr watchlist (no tickets yet)."] + [d for d in details if d])
        lines.append(f"DESCRIPTION:{_escape(desc)}")
        if details[1].startswith("http"):
            lines.append(f"URL:{details[1]}")
        for days in ALERT_DAYS:
            lines += ["BEGIN:VALARM", "ACTION:DISPLAY", f"TRIGGER:-P{days}D",
                      f"DESCRIPTION:{_escape(f'{artist} is in {days // 7} week' + ('s' if days > 7 else '') + '. Get tickets?')}",
                      "END:VALARM"]
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return "\r\n".join(part for line in lines for part in _fold(line)) + "\r\n"
