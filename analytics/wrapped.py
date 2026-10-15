"""Concert Wrapped: a year-in-review summary. Pure pandas, no Streamlit."""
import pandas as pd

from analytics.passport_stats import MINUTES_PER_SONG, haversine_miles
from data.attendance import process_attendance

SKIP_ARTISTS = {"various artists"}


def leader_label(counts: pd.Series, noun: str) -> str:
    """'Name · 3×' for a clear leader; otherwise say it's a tie.

    2-3 tied: 'A, B & C tied at 2×'. More than that: '43 artists tied at 1×'.
    """
    if counts is None or counts.empty:
        return ""
    top = int(counts.max())
    tied = sorted(str(n) for n in counts[counts == top].index)
    if len(tied) == 1:
        return f"{tied[0]} · {top}×"
    if len(tied) <= 3:
        names = ", ".join(tied[:-1]) + f" & {tied[-1]}"
        return f"{names} tied at {top}×"
    return f"{len(tied)} {noun} tied at {top}×"


def available_years(df_att: pd.DataFrame) -> list:
    years = df_att["eventDate_dt"].dropna().dt.year.astype(int).unique().tolist()
    return sorted(years, reverse=True)


def _home(df_concerts: pd.DataFrame):
    geo = df_concerts.dropna(subset=["lat", "long"])
    if geo.empty:
        return None
    city, state = geo.groupby(["city", "state"], dropna=False).size().idxmax()
    home = geo[(geo["city"] == city) & (geo["state"] == state)]
    return home["lat"].mean(), home["long"].mean(), (f"{city}, {state}" if pd.notna(state) and state else city)


def wrapped_summary(df_att: pd.DataFrame, year=None, rare_table=None, pop_table=None) -> dict:
    """Headline facts for one year (or all time when year is None). Empty dict if no shows."""
    d_all = df_att.dropna(subset=["eventDate_dt"])
    d_all = d_all[~d_all["artist"].str.lower().str.strip().isin(SKIP_ARTISTS)]
    d = d_all if year is None else d_all[d_all["eventDate_dt"].dt.year == year]
    if d.empty:
        return {}
    a, c, s = process_attendance(d.drop(columns=["eventDate_dt", "Date", "year"], errors="ignore"))
    _, c_all, _ = process_attendance(d_all.drop(columns=["eventDate_dt", "Date", "year"], errors="ignore"))

    w = {"year": year, "label": str(year) if year else "All Time"}
    w["concerts"] = int(len(c))
    w["sets"] = int(len(a[["eventDate_dt", "venue", "artist"]].drop_duplicates()))
    w["artists"] = int(a["artist"].nunique())
    w["venues"] = int(c["venue"].nunique())
    w["cities"] = int(c["city"].nunique())
    w["songs"] = int(pd.to_numeric(a["song_count"], errors="coerce").fillna(0).sum())
    w["hours"] = round(w["songs"] * MINUTES_PER_SONG / 60, 1)

    if year is not None:
        first_year = d_all.groupby("artist")["eventDate_dt"].min().dt.year
        w["new_artists"] = int((first_year == year).sum())
        prev = d_all[d_all["eventDate_dt"].dt.year == year - 1]
        w["prev_concerts"] = int(prev[["eventDate_dt", "venue"]].drop_duplicates().shape[0]) if not prev.empty else 0

    counts = a.groupby("artist")["eventDate_dt"].nunique().sort_values(ascending=False)
    w["top_artist"], w["top_artist_count"] = counts.index[0], int(counts.iloc[0])
    w["top_artist_label"] = leader_label(counts, "artists")
    venues = c["venue"].value_counts()
    w["top_venue"], w["top_venue_count"] = venues.index[0], int(venues.iloc[0])
    w["top_venue_label"] = leader_label(venues, "venues")
    months = c["eventDate_dt"].dt.strftime("%B %Y" if year is None else "%B").value_counts()
    w["busiest_month"], w["busiest_month_count"] = months.index[0], int(months.iloc[0])

    first, last = c.sort_values("eventDate_dt").iloc[0], c.sort_values("eventDate_dt").iloc[-1]
    fmt = "%b %d" if year is not None else "%b %d, %Y"

    def headliner(night):
        acts = a[(a["eventDate_dt"] == night["eventDate_dt"]) & (a["venue"] == night["venue"])]
        acts = acts.assign(n=pd.to_numeric(acts["song_count"], errors="coerce").fillna(0))
        return acts.sort_values("n", ascending=False)["artist"].iloc[0] if not acts.empty else night["artist"]

    w["first_show"] = f"{headliner(first)} at {first['venue']} ({first['eventDate_dt'].strftime(fmt)})"
    w["last_show"] = f"{headliner(last)} at {last['venue']} ({last['eventDate_dt'].strftime(fmt)})"

    if not s.empty:
        top_song = s["track_artist"].value_counts()
        if top_song.iloc[0] >= 2:
            w["top_song"], w["top_song_count"] = top_song.index[0], int(top_song.iloc[0])

    home = _home(c_all)
    geo = c.dropna(subset=["lat", "long"])
    if home and not geo.empty:
        miles = geo.apply(lambda r: haversine_miles(home[0], home[1], r["lat"], r["long"]), axis=1)
        far = geo.loc[miles.idxmax()]
        if miles.max() >= 25:
            w["farthest"] = f"{far['city']} ({round(miles.max()):,} miles from {home[2]})"

    if rare_table is not None and not rare_table.empty:
        r = rare_table
        if year is not None:
            r = r[r["Heard On"].astype(str).str[-4:] == str(year)]
        if not r.empty:
            top = r.iloc[0]
            w["rarest_song"] = f"{top['Song']} by {top['Artist']}"
            w["rarest_detail"] = str(top["Played In"])

    if pop_table is not None and not pop_table.empty:
        seen = set(a["artist"])
        p = pop_table[pop_table["Artist"].isin(seen)].sort_values("Shows Tracked", ascending=False)
        if len(p) >= 2:
            def logged(row):
                n = int(row["Shows Tracked"])
                return f"{row['Artist']} ({n:,} show{'' if n == 1 else 's'} logged)"
            w["biggest_act"], w["smallest_act"] = logged(p.iloc[0]), logged(p.iloc[-1])
    return w


def highlight_lines(w: dict) -> list:
    """[(label, value)] shown on the card and in the downloadable image, in order."""
    out = [("Top artist", w["top_artist_label"]), ("Home venue", w["top_venue_label"])]
    if "rarest_song" in w:
        out.append(("Rarest song you heard", f"{w['rarest_song']} ({w['rarest_detail']})"))
    if "top_song" in w:
        out.append(("Most heard song", f"{w['top_song']} · {w['top_song_count']}×"))
    if "biggest_act" in w:
        out.append(("Biggest act", w["biggest_act"]))
    if "farthest" in w:
        out.append(("Farthest trip", w["farthest"]))
    return out
