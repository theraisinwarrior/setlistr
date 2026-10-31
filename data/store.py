"""Data access for attended shows: live sync from setlist.fm, with the CSV as a fallback."""
import pandas as pd
import streamlit as st

from data.attendance import setlists_to_dataframe
from services.setlistfm import (fetch_artist_setlist_page, fetch_artist_show_count,
                                fetch_attended_setlists, fetch_year_setlists,
                                fetch_year_show_count)

ATTENDANCE_CSV = "attended_shows.csv"


@st.cache_data(ttl=86400, show_spinner=False)  # refreshed at most once a day
def sync_attended_shows(username: str, api_key: str) -> pd.DataFrame:
    """Pull a user's attended shows from setlist.fm as a raw attendance table."""
    return setlists_to_dataframe(fetch_attended_setlists(username, api_key))


@st.cache_data(ttl=7 * 86400, show_spinner=False)  # rarity changes slowly, so remember for a week
def get_artist_year_setlists(mbid: str, year: int, api_key: str) -> list:
    """Up to 20 of an artist's setlists from one year (used to judge how rare a song was).

    Failures raise SetlistFmError, so they are never cached.
    """
    return fetch_year_setlists(mbid, int(year), api_key)


@st.cache_data(ttl=7 * 86400, show_spinner=False)
def get_artist_show_count(mbid: str, api_key: str) -> int:
    """Number of an artist's concerts logged on setlist.fm. Failures raise and are never cached."""
    return fetch_artist_show_count(mbid, api_key)


@st.cache_data(ttl=7 * 86400, show_spinner=False)
def get_artist_year_show_count(mbid: str, year: int, api_key: str) -> int:
    """Number of an artist's concerts logged on setlist.fm for one year. Failures raise and aren't cached."""
    return fetch_year_show_count(mbid, int(year), api_key)


@st.cache_data(ttl=7 * 86400, show_spinner=False, max_entries=6000)
def get_artist_setlist_page(mbid: str, page: int, api_key: str) -> dict:
    """One compact page of an artist's setlist history. Failures raise and aren't cached."""
    return fetch_artist_setlist_page(mbid, int(page), api_key)


def clear_sync_cache() -> None:
    sync_attended_shows.clear()


UPCOMING_CSV = "upcoming_shows.csv"  # future shows: setlist.fm's API doesn't share them
VENUE_COORDS_CSV = "venue_coordinates.csv"  # optional: columns venue, lat, long (city optional)


def load_venue_overrides() -> pd.DataFrame:
    """Hand-corrected venue coordinates.

    Priority: venue_coordinates.csv first, then the coordinates already stored in
    attended_shows.csv. Missing files are simply skipped.
    """
    frames = []
    for path in (VENUE_COORDS_CSV, ATTENDANCE_CSV):
        try:
            df = pd.read_csv(path)
        except FileNotFoundError:
            continue
        if {"venue", "lat", "long"}.issubset(df.columns):
            cols = [c for c in ("venue", "city", "lat", "long") if c in df.columns]
            frames.append(df[cols])
    if not frames:
        return pd.DataFrame(columns=["venue", "city", "lat", "long"])
    return pd.concat(frames, ignore_index=True)


def load_upcoming_csv() -> pd.DataFrame:
    """Future shows typed into upcoming_shows.csv (date, artist, venue, city, state).

    setlist.fm keeps "Upcoming Shows" separate from attended ones and its API only returns
    attended shows, so the future ones live in this file (refresh it with
    `python scripts/sync_upcoming.py`). Returns the same column names as
    the synced data (eventDate, artist, venue, city, state). Empty if the file is missing.
    """
    cols = ["eventDate", "artist", "venue", "city", "state", "song_count"]
    try:
        df = pd.read_csv(UPCOMING_CSV, dtype=str)
    except FileNotFoundError:
        return pd.DataFrame(columns=cols)
    df.columns = [c.strip().lower() for c in df.columns]
    if not {"date", "artist", "venue"}.issubset(df.columns):
        return pd.DataFrame(columns=cols)
    df = df.rename(columns={"date": "eventDate"})
    for c in ("city", "state"):
        if c not in df.columns:
            df[c] = None
    df = df.dropna(subset=["eventDate", "artist", "venue"])
    df = df.apply(lambda col: col.str.strip() if col.dtype == object else col)
    df["song_count"] = 0
    return df[cols].reset_index(drop=True)


def load_csv_attendance() -> pd.DataFrame:
    """Fallback source. Raises FileNotFoundError if the CSV is missing."""
    return pd.read_csv(ATTENDANCE_CSV)
