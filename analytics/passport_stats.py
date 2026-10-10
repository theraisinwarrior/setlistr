"""Fun Passport stats and badges. Pure pandas, no Streamlit."""
import calendar
import math
from datetime import datetime

import pandas as pd

MINUTES_PER_SONG = 4  # rough average used for the "hours of live music" estimate


def haversine_miles(lat1, lon1, lat2, lon2) -> float:
    r = 3958.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = p2 - p1
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _longest_month_streak(dates) -> int:
    months = sorted({d.year * 12 + d.month for d in dates})
    best = run = 0
    prev = None
    for m in months:
        run = run + 1 if prev is not None and m == prev + 1 else 1
        best = max(best, run)
        prev = m
    return best


def _badge(icon, name, desc, value, goal, unit=""):
    earned = value >= goal
    return {"icon": icon, "name": name, "desc": desc, "earned": earned,
            "progress": "Earned!" if earned else f"{value}/{goal}{unit}"}


def compute_highlights(df_att: pd.DataFrame, df_concerts: pd.DataFrame,
                       df_songs: pd.DataFrame, today=None) -> dict:
    """Return a dict of headline stats plus a list of badges. Empty dict if no data."""
    today = today or datetime.now()
    if df_concerts is None or df_concerts.empty:
        return {}

    h = {}

    # ---- songs and time ----
    h["total_songs"] = int(pd.to_numeric(df_att["song_count"], errors="coerce").fillna(0).sum())
    h["unique_songs"] = (len(df_songs[["song", "artist"]].drop_duplicates())
                         if df_songs is not None and not df_songs.empty else 0)
    h["est_hours"] = round(h["total_songs"] * MINUTES_PER_SONG / 60, 1)

    # ---- dates ----
    dates = sorted(pd.to_datetime(df_concerts["eventDate_dt"]).dropna().dt.normalize().unique())
    dates = [pd.Timestamp(d) for d in dates]

    ym = df_concerts.dropna(subset=["eventDate_dt"]).copy()
    ym["ym"] = ym["eventDate_dt"].dt.year.astype(int) * 100 + ym["eventDate_dt"].dt.month.astype(int)
    if not ym.empty:
        top_ym = ym["ym"].value_counts().idxmax()
        h["busiest_month"] = f"{calendar.month_name[top_ym % 100]} {top_ym // 100}"
        h["busiest_month_count"] = int(ym["ym"].value_counts().max())
        h["favorite_weekday"] = ym["eventDate_dt"].dt.day_name().value_counts().idxmax()
    h["longest_month_streak"] = _longest_month_streak(dates) if dates else 0

    if len(dates) >= 2:
        gaps = [(dates[i + 1] - dates[i]).days for i in range(len(dates) - 1)]
        i = max(range(len(gaps)), key=gaps.__getitem__)
        h["longest_break_days"] = gaps[i]
        h["longest_break_range"] = f"{dates[i]:%b %d, %Y} → {dates[i + 1]:%b %d, %Y}"

    hot = any((dates[i + 2] - dates[i]).days <= 7 for i in range(len(dates) - 2))
    h["hot_streak"] = hot

    # ---- places ----
    venue_counts = df_concerts["venue"].value_counts()
    h["top_venue"], h["top_venue_count"] = venue_counts.index[0], int(venue_counts.iloc[0])
    states = df_concerts["state"].replace("", pd.NA).dropna()
    h["states_count"] = int(states.nunique())

    geo = df_concerts.dropna(subset=["lat", "long"])
    if not geo.empty:
        home_city = geo.groupby(["city", "state"]).size().idxmax()
        home = geo[(geo["city"] == home_city[0]) & (geo["state"] == home_city[1])]
        hlat, hlon = home["lat"].mean(), home["long"].mean()
        geo = geo.assign(miles=[haversine_miles(hlat, hlon, la, lo)
                                for la, lo in zip(geo["lat"], geo["long"])])
        far = geo.loc[geo["miles"].idxmax()]
        h["home_base"] = f"{home_city[0]}, {home_city[1]}" if home_city[1] else home_city[0]
        h["farthest_miles"] = round(float(far["miles"]))
        h["farthest_show"] = (f"{far['artist']} at {far['venue']} ({far['city']}) "
                              f"on {far['eventDate_dt']:%b %d, %Y}")

    # ---- artists ----
    artist_counts = df_att["artist"].value_counts()
    h["top_artist"], h["top_artist_count"] = artist_counts.index[0], int(artist_counts.iloc[0])
    h["repeat_artists"] = int((artist_counts >= 2).sum())

    festival = (df_att.dropna(subset=["eventDate_dt"])
                .groupby(["eventDate_dt", "venue"])["artist"].nunique())
    h["festival_days"] = int((festival >= 3).sum())

    # ---- on this day ----
    mask = ((df_concerts["eventDate_dt"].dt.month == today.month)
            & (df_concerts["eventDate_dt"].dt.day == today.day))
    h["on_this_day"] = [
        f"{r.eventDate_dt:%Y}: {r.artist} at {r.venue}"
        for r in df_concerts[mask].sort_values("eventDate_dt").itertuples()
    ]

    # ---- badges ----
    n = len(df_concerts)
    h["badges"] = [
        _badge("🎟️", "Concert-goer", "25 concerts attended", n, 25),
        _badge("💯", "Century Club", "100 concerts attended", n, 100),
        _badge("🏠", "Regular", "5 shows at one venue", h["top_venue_count"], 5),
        _badge("🤘", "Superfan", "Seen one artist 5+ times", h["top_artist_count"], 5),
        _badge("🔁", "Repeat Offender", "10 artists seen at least twice", h["repeat_artists"], 10),
        _badge("🧭", "Road Warrior", "Shows in 5 different states or countries", h["states_count"], 5),
        _badge("🎪", "Festival Goer", "A day with 3+ acts at one venue", h["festival_days"], 1),
        {"icon": "🔥", "name": "Hot Streak", "desc": "3 concerts within 7 days",
         "earned": hot, "progress": "Earned!" if hot else "Not yet"},
    ]
    return h


def venue_top_performers(df_att: pd.DataFrame, top_n: int = 3, sep: str = "<br>") -> dict:
    """Map venue -> 'Artist ×N' lines for the artists seen most often there.

    Counts individual artists from the per-artist rows (not the combined
    lineup strings), so each performer appears once with their real count.
    """
    result = {}
    for venue, grp in df_att.groupby("venue"):
        counts = grp["artist"].value_counts().head(top_n)
        result[venue] = sep.join(f"{a} ×{n}" for a, n in counts.items())
    return result
