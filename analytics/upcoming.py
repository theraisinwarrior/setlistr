"""Upcoming shows you've marked on setlist.fm. Pure pandas, no Streamlit."""
import pandas as pd

COLUMNS = ["Date", "When", "Lineup", "Venue", "City"]


def countdown(day, today) -> str:
    days = (pd.Timestamp(day).normalize() - pd.Timestamp(today).normalize()).days
    if days <= 0:
        return "Tonight"
    if days == 1:
        return "Tomorrow"
    if days < 14:
        return f"In {days} days"
    if days < 60:
        return f"In {round(days / 7)} weeks"
    return f"In {round(days / 30.4)} months"


def upcoming_table(df_upcoming: pd.DataFrame, today=None) -> pd.DataFrame:
    """One row per upcoming concert (same day + venue), soonest first."""
    if df_upcoming is None or df_upcoming.empty:
        return pd.DataFrame(columns=COLUMNS)
    today = pd.Timestamp(today or pd.Timestamp.now()).normalize()
    d = df_upcoming.assign(_day=pd.to_datetime(df_upcoming["eventDate"], errors="coerce").dt.normalize())
    d = d.dropna(subset=["_day"])
    d = d[d["_day"] >= today]  # a show in the list whose date has passed is no longer upcoming
    if d.empty:
        return pd.DataFrame(columns=COLUMNS)
    # the same act listed twice (setlist.fm sync + upcoming_shows.csv) counts once
    d = d.assign(_key=d["artist"].astype(str).str.lower().str.replace(r"[^a-z0-9]", "", regex=True))
    d = d.drop_duplicates(subset=["_day", "_key"])
    rows = []
    for (day, venue), g in d.groupby(["_day", "venue"], sort=False):
        acts = [a for a in dict.fromkeys(g["artist"]) if str(a).lower() != "various artists"]
        if len(acts) < g["artist"].nunique():
            acts.append("various artists")
        city, state = g.iloc[0].get("city"), g.iloc[0].get("state")
        rows.append({"Date": day.strftime("%Y-%m-%d"), "When": countdown(day, today),
                     "Lineup": ", ".join(acts), "Venue": venue,
                     "City": f"{city}, {state}" if pd.notna(state) and state else city, "_day": day})
    out = pd.DataFrame(rows).sort_values("_day")
    return out[COLUMNS].reset_index(drop=True)
