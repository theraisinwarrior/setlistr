"""My Shows: upcoming shows you have tickets to, plus a watchlist of shows you'd like to see."""
from datetime import date

import streamlit as st

from analytics.upcoming import upcoming_table
from analytics.watchlist import watchlist_csv_line, watchlist_table
from data.display import dated_table
from data.store import load_upcoming_csv, load_watchlist_csv

REPO = "https://github.com/theraisinwarrior/setlistr"
EDIT_WATCHLIST_URL = f"{REPO}/edit/main/watchlist.csv"

st.title("🎟️ My Shows")
st.caption("Shows you have tickets to, and shows you're keeping an eye on.")

# Both lists are small CSVs in the repo, read fresh on each run (no API calls on this page).
# Streamlit Cloud forgets files the app writes, so edits happen in the repo and redeploy in ~2 min.
tickets_raw = load_upcoming_csv()
tickets = upcoming_table(tickets_raw)
watch = watchlist_table(load_watchlist_csv(), tickets_raw)

m1, m2, m3 = st.columns([2, 1, 1])
if tickets.empty:
    m1.metric("Next up", "Nothing booked yet")
else:
    nxt = tickets.iloc[0]
    m1.metric("Next up", nxt["Lineup"].split(", ")[0], f"{nxt['When']} · {nxt['Venue']}", delta_color="off")
m2.metric("Shows with tickets", len(tickets))
m3.metric("On the watchlist", int((watch["Status"] != "🎟️ Got tickets").sum()) if not watch.empty else 0)

# ------------------------------------------
# 1. Got tickets
# ------------------------------------------
st.subheader("🎫 Got Tickets")
if tickets.empty:
    st.caption("No upcoming shows yet. Mark them as going on setlist.fm, then run ./sync on your Mac.")
else:
    dated_table(tickets, use_container_width=True, hide_index=True,
                height=min(400, 38 + 35 * len(tickets)))
    st.caption("From upcoming_shows.csv (your setlist.fm Upcoming Shows, refreshed with ./sync). "
               "A show drops off once its date passes.")

# ------------------------------------------
# 2. Watchlist
# ------------------------------------------
st.subheader("👀 Want to See")
if watch.empty:
    st.caption("Nothing on your watchlist yet. Use **Add a show** below.")
else:
    dated_table(watch, use_container_width=True, hide_index=True,
                height=min(400, 38 + 35 * len(watch)),
                column_config={"Link": st.column_config.LinkColumn("Link", display_text="Tickets")})
    st.caption("From watchlist.csv. Once you buy tickets and the show reaches your setlist.fm "
               "Upcoming Shows, it's marked 🎟️ Got tickets here, and you can delete its watchlist line.")

with st.expander("➕ Add a show to the watchlist"):
    st.write("Fill in what you know (only the artist is required). Copy the line it makes, "
             "then open watchlist.csv on GitHub, paste it on a new line at the bottom, and click "
             "**Commit changes**. The app updates in about 2 minutes.")
    with st.form("add_watch"):
        a1, a2 = st.columns(2)
        artist = a1.text_input("Artist")
        venue = a2.text_input("Venue")
        b1, b2 = st.columns([3, 1])
        city = b1.text_input("City")
        state = b2.text_input("State")
        c1, c2 = st.columns(2)
        show_day = c1.date_input("Show date (leave blank if TBA)", value=None, min_value=date.today())
        sale_day = c2.date_input("Tickets on sale (optional)", value=None)
        link = st.text_input("Ticket link (optional)")
        notes = st.text_input("Notes (optional)", placeholder="e.g. presale code from the newsletter")
        made = st.form_submit_button("Make the line")
    if made:
        if not artist.strip():
            st.warning("Add an artist first.")
        else:
            st.code(watchlist_csv_line(artist, show_day.isoformat() if show_day else None, venue, city,
                                       state, sale_day.isoformat() if sale_day else None, link, notes),
                    language=None)
            st.caption("Use the copy icon at the top right of the box above.")
    st.link_button("Open watchlist.csv on GitHub", EDIT_WATCHLIST_URL)
