"""My Shows: upcoming shows you have tickets to, plus a watchlist of shows you'd like to see."""
from datetime import date

import pandas as pd
import streamlit as st

from analytics.upcoming import upcoming_table
from analytics.watchlist import FIELDS, watchlist_table
from data.display import dated_table
from data.store import (get_watchlist, load_upcoming_csv, load_watchlist_csv, lookup_ticket_link,
                        save_watchlist, search_ticketmaster_shows)
from services.auth import get_github_token, get_ticketmaster_key, is_owner
from services.github_store import GitHubStoreError
from services.ticket_links import LinkError, blank

REPO = st.secrets.get("GITHUB_REPO", "theraisinwarrior/setlistr")

st.title("🎟️ My Shows")
st.caption("Shows you have tickets to, and shows you're keeping an eye on.")

owner, token, tm_key = is_owner(), get_github_token(), get_ticketmaster_key()
can_save = owner and bool(token)

# The watchlist is read from GitHub when a token is set, so a save shows up right away
# (Streamlit Cloud forgets files the app writes, so saves are commits to watchlist.csv).
watch_raw = load_watchlist_csv()
if token:
    try:
        watch_raw = get_watchlist(REPO, token)
    except GitHubStoreError as e:
        st.warning(f"{e} Showing the watchlist from the last deploy.")

tickets_raw = load_upcoming_csv()
tickets = upcoming_table(tickets_raw)
watch = watchlist_table(watch_raw, tickets_raw)


def _key(name) -> str:
    return "".join(ch for ch in str(name).lower() if ch.isalnum())


def already_listed(show: dict) -> str:
    """'' if the show is new, otherwise where it already is."""
    k, day = _key(show.get("artist")), show.get("date") or ""
    if any(_key(a) == k and (d or "") == day for a, d in zip(watch_raw["artist"], watch_raw["date"])):
        return "on your watchlist"
    if day and any(_key(a) == k and str(d) == day
                   for a, d in zip(tickets_raw["artist"], tickets_raw["eventDate"])):
        return "in your tickets"
    return ""


def add_show(show: dict) -> None:
    """Commit one show to watchlist.csv, then rerun so it appears in the table."""
    row = {f: str(show.get(f) or "").strip() for f in FIELDS}
    label = row["artist"] + (f" ({row['date']})" if row["date"] else "")
    try:
        with st.spinner("Saving..."):
            save_watchlist(REPO, token, lambda df: pd.concat([df, pd.DataFrame([row])], ignore_index=True),
                           f"Watchlist: add {label}")
    except GitHubStoreError as e:
        st.error(str(e))
        return
    st.session_state.pop("link_draft", None)
    st.session_state["just_saved"] = f"Added {label} to your watchlist."
    st.rerun()


def show_form(draft: dict, form_key: str) -> None:
    """Editable details for one show, prefilled from a lookup. Only the artist is required."""
    with st.form(form_key, clear_on_submit=True):
        a1, a2 = st.columns(2)
        artist = a1.text_input("Artist", value=draft.get("artist", ""))
        venue = a2.text_input("Venue", value=draft.get("venue", ""))
        b1, b2, b3, b4 = st.columns([3, 1, 2, 2])
        city = b1.text_input("City", value=draft.get("city", ""))
        state = b2.text_input("State", value=draft.get("state", ""))
        show_day = b3.date_input("Show date", value=_as_date(draft.get("date")),
                                 help="Leave blank if it hasn't been announced.")
        sale_day = b4.date_input("Tickets on sale", value=_as_date(draft.get("on_sale")),
                                 help="Optional. Shows a countdown until tickets go on sale.")
        link = st.text_input("Ticket link", value=draft.get("link", ""))
        notes = st.text_input("Notes", value=draft.get("notes", ""),
                              placeholder="e.g. presale code from the newsletter")
        if st.form_submit_button("💾 Save to watchlist", type="primary"):
            if not artist.strip():
                st.warning("Add an artist first.")
                return
            show = {"artist": artist, "venue": venue, "city": city, "state": state,
                    "date": show_day.isoformat() if show_day else "",
                    "on_sale": sale_day.isoformat() if sale_day else "", "link": link, "notes": notes}
            where = already_listed(show)
            if where:
                st.info(f"{artist} on that date is already {where}.")
                return
            add_show(show)


def _as_date(value):
    try:
        return date.fromisoformat(str(value)) if value else None
    except ValueError:
        return None


if "just_saved" in st.session_state:
    st.success(st.session_state.pop("just_saved"))

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
    st.caption("From your setlist.fm Upcoming Shows (refreshed with ./sync). "
               "A show drops off once its date passes.")

# ------------------------------------------
# 2. Watchlist
# ------------------------------------------
st.subheader("👀 Want to See")

if can_save:
    tabs = st.tabs(["🔗 Paste a link", "🔎 Find an artist's shows", "✍️ Type it in"])

    with tabs[0]:
        with st.form("link_lookup", border=False):
            l1, l2 = st.columns([4, 1], vertical_alignment="bottom")
            url = l1.text_input("Ticket link", placeholder="https://www.ticketmaster.com/... (or Dice, AXS, a venue site)")
            looked = l2.form_submit_button("Look it up", use_container_width=True)
        if looked and url.strip():
            try:
                with st.spinner("Reading the link..."):
                    st.session_state["link_draft"] = lookup_ticket_link(url.strip(), tm_key)
            except LinkError as e:
                st.session_state["link_draft"] = {**blank(url.strip()), "source": ""}
                st.warning(str(e))
        draft = st.session_state.get("link_draft")
        if draft:
            if draft.get("source"):
                st.caption(f"Filled in from {draft['source']}. Fix anything that's off, then save.")
            if already_listed(draft):
                st.info(f"Heads up: {draft['artist']} on that date is already {already_listed(draft)}.")
            show_form(draft, "link_form")

    with tabs[1]:
        if not tm_key:
            st.caption("Add a free Ticketmaster API key to the app's secrets as TICKETMASTER_API_KEY "
                       "to search for an artist's upcoming dates here.")
        else:
            with st.form("tm_search", border=False):
                s1, s2, s3 = st.columns([3, 2, 1], vertical_alignment="bottom")
                artist_q = s1.text_input("Artist")
                city_q = s2.text_input("City (optional)", placeholder="e.g. New York")
                searched = s3.form_submit_button("Search", use_container_width=True)
            if searched and artist_q.strip():
                try:
                    with st.spinner("Searching Ticketmaster..."):
                        st.session_state["tm_results"] = search_ticketmaster_shows(
                            artist_q.strip(), city_q.strip(), tm_key)
                except LinkError as e:
                    st.warning(str(e))
            results = st.session_state.get("tm_results")
            if results == []:
                st.caption("No upcoming Ticketmaster dates found. Try without the city, or use another tab.")
            for i, show in enumerate(results or []):
                r1, r2 = st.columns([5, 1], vertical_alignment="center")
                when = pd.Timestamp(show["date"]).strftime("%a %b %-d, %Y") if show["date"] else "Date TBA"
                place = ", ".join(x for x in (show["venue"], show["city"], show["state"]) if x)
                extra = f" · on sale {show['on_sale']}" if show["on_sale"] > date.today().isoformat() else ""
                r1.markdown(f"**{show['artist']}** · {when} · {place}{extra}"
                            + (f"  \n:gray[{show['notes']}]" if show["notes"] else ""))
                where = already_listed(show)
                if where:
                    r2.caption(f"✓ {where.replace('on your ', '').replace('in your ', '').capitalize()}")
                elif r2.button("➕ Add", key=f"tm_add_{i}", use_container_width=True):
                    add_show(show)

    with tabs[2]:
        show_form(blank(), "manual_form")

if watch.empty:
    st.caption("Nothing on your watchlist yet." + (" Add a show above." if can_save else ""))
else:
    dated_table(watch, use_container_width=True, hide_index=True,
                height=min(400, 38 + 35 * len(watch)),
                column_config={"Link": st.column_config.LinkColumn("Link", display_text="Tickets")})
    st.caption("Once you buy tickets and the show reaches your setlist.fm Upcoming Shows, "
               "it's marked 🎟️ Got tickets here.")

if can_save and not watch_raw.empty:
    with st.expander("✏️ Edit or remove shows"):
        st.caption("Change any cell, or tick a row's checkbox and press Delete to remove it. Then save.")
        edited = st.data_editor(watch_raw, num_rows="dynamic", use_container_width=True,
                                hide_index=True, key="watch_editor")
        if st.button("💾 Save changes", disabled=edited.equals(watch_raw)):
            try:
                with st.spinner("Saving..."):
                    save_watchlist(REPO, token, lambda _df: edited, "Watchlist: edit shows")
            except GitHubStoreError as e:
                st.error(str(e))
            else:
                st.session_state["just_saved"] = "Saved your watchlist changes."
                st.rerun()
elif owner and not token:
    st.info("To add shows from this page, add a GitHub token to the app's secrets as GITHUB_TOKEN "
            "(see the setup steps in the README).")
