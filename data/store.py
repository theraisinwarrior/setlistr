"""Data access for attended shows: live sync from setlist.fm, with the CSV as a fallback."""
import pandas as pd
import streamlit as st

from data.attendance import setlists_to_dataframe
from services.setlistfm import (SetlistFmError, fetch_attended_setlists, fetch_setlists,
                                get_mbid_from_name)

ATTENDANCE_CSV = "attended_shows.csv"


@st.cache_data(ttl=86400, show_spinner=False)  # refreshed at most once a day
def sync_attended_shows(username: str, api_key: str) -> pd.DataFrame:
    """Pull a user's attended shows from setlist.fm as a raw attendance table."""
    return setlists_to_dataframe(fetch_attended_setlists(username, api_key))


@st.cache_data(ttl=86400, show_spinner=False)
def get_artist_recent_setlists(artist_name: str, mbid: str, api_key: str, max_shows: int = 100) -> list:
    """An artist's most recent setlists, used to measure how rare a song is.

    Raises SetlistFmError when nothing can be loaded, so a failed lookup is never cached.
    """
    if not mbid:
        mbid, _ = get_mbid_from_name(artist_name, api_key)
    setlists = fetch_setlists(mbid, api_key, max_shows, False, 0)[:max_shows] if mbid else []
    if not setlists:
        raise SetlistFmError(f"Couldn't load recent setlists for {artist_name} from setlist.fm.")
    return setlists


def clear_sync_cache() -> None:
    sync_attended_shows.clear()


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


def load_csv_attendance() -> pd.DataFrame:
    """Fallback source. Raises FileNotFoundError if the CSV is missing."""
    return pd.read_csv(ATTENDANCE_CSV)
