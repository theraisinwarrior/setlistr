"""Refresh upcoming_shows.csv from a saved copy of your setlist.fm attended page. Run it whenever you like.

setlist.fm's API doesn't return "Upcoming Shows", but the page at setlist.fm/attended/<username>
lists them. That page sits behind a bot check that scripts can't pass, so you save it from
Chrome (⌘S, "Webpage, HTML Only") and this reads the saved copy:

    python3 scripts/sync_upcoming.py              # newest saved page in ~/Downloads
    python3 scripts/sync_upcoming.py --dry-run    # show the changes, don't write
    python3 scripts/sync_upcoming.py --file path/to/page.html

Then review the diff, commit and push upcoming_shows.csv as usual.
"""
import argparse
import csv
import difflib
import html
import io
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UPCOMING_CSV = ROOT / "upcoming_shows.csv"
DOWNLOADS = Path.home() / "Downloads"
SAVED_PAGE_GLOB = "*attended concerts*setlist.fm*.htm*"
FIELDS = ["date", "artist", "venue", "city", "state"]
MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}
# countries whose setlist.fm sublines read "Venue, City, State, Country"
HAS_STATE = {"usa", "canada", "australia", "brazil"}


class PageError(Exception):
    """The page didn't contain an Upcoming Shows list we can read."""


def _text(fragment: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", fragment)).replace("\xa0", " ").strip()


def _upcoming_section(page: str) -> str:
    start = re.search(r"<h2[^>]*>\s*Upcoming Shows\b", page)
    if not start:
        if re.search(r"<h2[^>]*>\s*Attended Shows\b", page):
            return ""  # the page loaded fine; there just aren't any upcoming shows
        raise PageError("No 'Upcoming Shows' or 'Attended Shows' heading on the page. "
                        "setlist.fm probably served its bot check instead.")
    end = re.compile(r"<h2[\s>]").search(page, start.end())
    return page[start.end(): end.start() if end else len(page)]


def _split_place(place: str) -> tuple:
    """'Venue, City, NY, USA' -> (venue, city, state). Venue names may contain commas."""
    parts = [p.strip() for p in place.split(",")]
    if len(parts) >= 4 and parts[-1].lower() in HAS_STATE:
        return ", ".join(parts[:-3]), parts[-3], parts[-2]
    if len(parts) >= 3:
        return ", ".join(parts[:-2]), parts[-2], ""
    return parts[0], (parts[1] if len(parts) > 1 else ""), ""


def parse_upcoming(page: str) -> list:
    """Rows (date, artist, venue, city, state) from the page's Upcoming Shows list, in page order."""
    rows = []
    for item in re.split(r'<li class="setlist"', _upcoming_section(page))[1:]:
        date = re.search(r'<strong class="text-uppercase">\s*(\w{3})\s*</strong>\s*'
                         r'<strong class="big">\s*(\d{1,2})\s*</strong>\s*<span>\s*(\d{4})', item)
        artist = re.search(r'class="column content".*?<strong>(.*?)</strong>', item, re.S)
        place = re.search(r'<span class="subline">\s*<span>(.*?)</span>', item, re.S)
        if not (date and artist and place) or date.group(1).lower() not in MONTHS:
            raise PageError("An Upcoming Shows entry didn't look as expected; "
                            "setlist.fm may have changed its page layout.")
        mon, day, year = date.groups()
        venue, city, state = _split_place(_text(place.group(1)))
        rows.append({"date": f"{year}-{MONTHS[mon.lower()]:02d}-{int(day):02d}",
                     "artist": _text(artist.group(1)), "venue": venue, "city": city, "state": state})
    return rows


def to_csv(rows: list) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=FIELDS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(sorted(rows, key=lambda r: r["date"]))  # stable: keeps page order within a day
    return buf.getvalue()


def newest_saved_page(folder=None):
    """The most recently saved attended page in Downloads, or None."""
    pages = [p for p in Path(folder or DOWNLOADS).glob(SAVED_PAGE_GLOB) if p.is_file()]
    return max(pages, key=lambda p: p.stat().st_mtime) if pages else None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--file", help="saved attended page (default: the newest one in ~/Downloads)")
    ap.add_argument("--dry-run", action="store_true", help="print the changes without writing")
    args = ap.parse_args(argv)

    path = Path(args.file).expanduser() if args.file else newest_saved_page()
    if path is None:
        print("No saved setlist.fm page in ~/Downloads. Open setlist.fm/attended/<you> in Chrome, "
              "press ⌘S, choose 'Webpage, HTML Only', then run this again.", file=sys.stderr)
        return 1
    saved = datetime.fromtimestamp(path.stat().st_mtime).strftime("%b %d %I:%M %p")
    print(f"Reading {path.name} (saved {saved})\n")
    try:
        rows = parse_upcoming(path.read_text(encoding="utf-8"))
    except (OSError, PageError) as e:
        print(f"Couldn't read upcoming shows: {e}", file=sys.stderr)
        return 1

    new = to_csv(rows)
    old = UPCOMING_CSV.read_text(encoding="utf-8") if UPCOMING_CSV.exists() else ""
    if new == old:
        print(f"upcoming_shows.csv is already up to date ({len(rows)} rows).")
        return 0
    sys.stdout.writelines(difflib.unified_diff(
        old.splitlines(True), new.splitlines(True), "upcoming_shows.csv (current)",
        "upcoming_shows.csv (setlist.fm)"))
    if args.dry_run:
        print("\nDry run: nothing written.")
        return 0
    UPCOMING_CSV.write_text(new, encoding="utf-8")
    print(f"\nWrote {len(rows)} rows to upcoming_shows.csv. Review, then commit and push.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
