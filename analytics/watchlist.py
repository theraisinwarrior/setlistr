"""Shows you'd like to see (watchlist.csv). Pure pandas, no Streamlit."""
import pandas as pd

from analytics.upcoming import countdown

COLUMNS = ["Status", "Artist", "Date", "When", "Venue", "City", "On Sale", "Link", "Notes"]
FIELDS = ["artist", "date", "venue", "city", "state", "on_sale", "link", "notes"]


def _key(name) -> str:
    return "".join(ch for ch in str(name).lower() if ch.isalnum())


def on_sale_label(day, today) -> str:
    """'On sale now' once the date arrives, otherwise a countdown to it. Blank if unknown."""
    if pd.isna(day):
        return ""
    days = (pd.Timestamp(day).normalize() - pd.Timestamp(today).normalize()).days
    if days <= 0:
        return "On sale now"
    return "On sale " + countdown(day, today).replace("In ", "in ").lower()


def watchlist_table(df_watch: pd.DataFrame, df_tickets: pd.DataFrame = None, today=None) -> pd.DataFrame:
    """One row per show you're interested in: dated ones soonest first, then 'date TBA' ones.

    A show whose date has passed drops off. If you already have tickets for that artist
    (on that date, when the watchlist gives one) it's marked "Got tickets".
    """
    if df_watch is None or df_watch.empty:
        return pd.DataFrame(columns=COLUMNS)
    today = pd.Timestamp(today or pd.Timestamp.now()).normalize()
    d = df_watch.copy()
    for c in FIELDS:
        if c not in d.columns:
            d[c] = None
    d = d[d["artist"].notna() & (d["artist"].astype(str).str.strip() != "")]
    d["_day"] = pd.to_datetime(d["date"], errors="coerce").dt.normalize()
    d["_sale"] = pd.to_datetime(d["on_sale"], errors="coerce").dt.normalize()
    d = d[d["_day"].isna() | (d["_day"] >= today)]
    if d.empty:
        return pd.DataFrame(columns=COLUMNS)

    ticket_any, ticket_dated = set(), set()
    if df_tickets is not None and not df_tickets.empty:
        t_days = pd.to_datetime(df_tickets["eventDate"], errors="coerce").dt.normalize()
        for artist, day in zip(df_tickets["artist"], t_days):
            if pd.notna(day) and day >= today:
                ticket_any.add(_key(artist))
                ticket_dated.add((_key(artist), day))

    def has_tickets(row) -> bool:
        k = _key(row["artist"])
        return (k, row["_day"]) in ticket_dated if pd.notna(row["_day"]) else k in ticket_any

    def text(v) -> str:
        return "" if pd.isna(v) else str(v).strip()

    rows = []
    for _, r in d.iterrows():
        city, state = text(r["city"]), text(r["state"])
        rows.append({
            "Status": "🎟️ Got tickets" if has_tickets(r) else "👀 Interested",
            "Artist": text(r["artist"]),
            "Date": r["_day"].strftime("%Y-%m-%d") if pd.notna(r["_day"]) else None,
            "When": countdown(r["_day"], today) if pd.notna(r["_day"]) else "Date TBA",
            "Venue": text(r["venue"]),
            "City": f"{city}, {state}" if city and state else city or state,
            "On Sale": on_sale_label(r["_sale"], today),
            "Link": text(r["link"]),
            "Notes": text(r["notes"]),
            "_sort": r["_day"] if pd.notna(r["_day"]) else pd.Timestamp.max,
        })
    out = pd.DataFrame(rows).sort_values(["_sort", "Artist"], kind="stable")
    return out[COLUMNS].reset_index(drop=True)

