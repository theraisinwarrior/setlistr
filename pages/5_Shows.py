"""My Shows: upcoming shows you have tickets to, plus a watchlist of shows you'd like to see."""
from datetime import date

import pandas as pd
import streamlit as st

from analytics.upcoming import upcoming_table
from analytics.watchlist import FIELDS, TICKETS, bought, ticket_rows, watchlist_table
from data.display import dated_table
from data.store import (get_watchlist, load_upcoming_csv, load_watchlist_csv, lookup_ticket_link,
                        save_watchlist, search_upcoming_shows)
from services.auth import get_github_token, get_seatgeek_client_id, is_owner
from services.github_store import GitHubStoreError
from services.ticket_links import LinkError, blank

REPO = st.secrets.get("GITHUB_REPO", "theraisinwarrior/setlistr")

st.title("🎟️ My Shows")
st.caption("Shows you have tickets to, and shows you're keeping an eye on.")

owner, token, sg_id = is_owner(), get_github_token(), get_seatgeek_client_id()
can_save = owner and bool(token)

# The watchlist is read from GitHub when a token is set, so a save shows up right away
# (Streamlit Cloud forgets files the app writes, so saves are commits to watchlist.csv).
watch_raw = load_watchlist_csv()
if token:
    try:
        watch_raw = get_watchlist(REPO, token)
    except GitHubStoreError as e:
        st.warning(f"{e} Showing the watchlist from the last deploy.")

# Got Tickets = setlist.fm Upcoming Shows (./sync) + watchlist shows marked as bought.
# upcoming_table counts a show once when it's in both.
tickets_raw = pd.concat([load_upcoming_csv(), ticket_rows(watch_raw)], ignore_index=True)
tickets = upcoming_table(tickets_raw)
watch = watchlist_table(watch_raw, tickets_raw, keep_row=True)


def _key(name) -> str:
    return "".join(ch for ch in str(name).lower() if ch.isalnum())


def _same_show(df: pd.DataFrame, show: dict) -> pd.Series:
    return (df["artist"].map(_key) == _key(show.get("artist"))) & (df["date"].fillna("") == (show.get("date") or ""))


def already_listed(show: dict) -> str:
    """'' if the show is new, otherwise where it already is."""
    if _same_show(watch_raw, show).any():
        return "on your list"
    k, day = _key(show.get("artist")), show.get("date") or ""
    if day and any(_key(a) == k and str(d) == day
                   for a, d in zip(tickets_raw["artist"], tickets_raw["eventDate"])):
        return "in your tickets"
    return ""


def _save(change, message: str, done: str) -> None:
    try:
        with st.spinner("Saving..."):
            save_watchlist(REPO, token, change, message)
    except GitHubStoreError as e:
        st.error(str(e))
        return
    for k in ("draft", "results", "query"):
        st.session_state.pop(k, None)
    st.session_state["just_saved"] = done
    st.rerun()


def _label(show: dict) -> str:
    return str(show.get("artist", "")).strip() + (f" ({show['date']})" if show.get("date") else "")


def add_show(show: dict, got_tickets: bool = False) -> None:
    """Commit one show to watchlist.csv, then rerun so it appears on the page."""
    row = {f: str(show.get(f) or "").strip() for f in FIELDS}
    row["status"] = TICKETS if got_tickets else ""
    where = "Got Tickets" if got_tickets and row["date"] else "your watchlist"
    _save(lambda df: pd.concat([df, pd.DataFrame([row])], ignore_index=True),
          f"Watchlist: add {_label(row)}", f"Added {_label(row)} to {where}.")


def mark_bought(show: dict) -> None:
    def change(df):
        df.loc[_same_show(df, show), "status"] = TICKETS
        return df
    _save(change, f"Watchlist: got tickets for {_label(show)}",
          f"🎟️ Moved {_label(show)} to Got Tickets." if show.get("date")
          else f"🎟️ Marked {_label(show)} as bought. Add its date to move it to Got Tickets.")


def unmark_bought(show: dict) -> None:
    def change(df):
        df.loc[_same_show(df, show), "status"] = ""
        return df
    _save(change, f"Watchlist: no tickets for {_label(show)}", f"Moved {_label(show)} back to your watchlist.")


def remove_show(show: dict) -> None:
    _save(lambda df: df[~_same_show(df, show)], f"Watchlist: remove {_label(show)}",
          f"Removed {_label(show)}.")


def _as_date(value):
    try:
        return date.fromisoformat(str(value)) if value else None
    except ValueError:
        return None


def _when(day: str) -> str:
    return pd.Timestamp(day).strftime("%a %b %-d, %Y") if day else "Date TBA"


def show_form(draft: dict) -> None:
    """Editable details for one show, prefilled from a lookup. Only the artist is required."""
    with st.form("show_form", clear_on_submit=True):
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
                              placeholder="e.g. with openers, or a presale code")
        c1, c2, _ = st.columns([2, 2, 3])
        want = c1.form_submit_button("👀 Add to watchlist", type="primary", use_container_width=True)
        have = c2.form_submit_button("🎟️ I have tickets", use_container_width=True)
    if want or have:
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
        add_show(show, got_tickets=have)
    if st.button("Cancel"):
        st.session_state.pop("draft", None)
        st.rerun()


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
# 0. Add a show: one box for a link or an artist name
# ------------------------------------------
if can_save:
    st.subheader("➕ Add a Show")
    with st.form("add_box", border=False):
        q1, q2 = st.columns([5, 1], vertical_alignment="bottom")
        query = q1.text_input("Paste a ticket link or type an artist",
                              placeholder="songkick.com/concerts/…, seatgeek.com/…, ticketmaster.com/…, or Big Thief")
        go = q2.form_submit_button("Go", type="primary", use_container_width=True)
    if go and query.strip():
        q = query.strip()
        st.session_state.pop("draft", None)
        st.session_state.pop("results", None)
        st.session_state["query"] = q
        if q.lower().startswith(("http://", "https://", "www.")):
            url = q if q.lower().startswith("http") else "https://" + q
            try:
                with st.spinner("Reading the link..."):
                    st.session_state["draft"] = lookup_ticket_link(url, sg_id)
            except LinkError as e:
                st.warning(str(e))
                st.session_state["draft"] = {**blank(url), "source": ""}
        elif sg_id:
            try:
                with st.spinner(f"Looking up {q}'s upcoming shows..."):
                    st.session_state["results"] = search_upcoming_shows(q, "", sg_id)
            except LinkError as e:
                st.warning(str(e))
                st.session_state["draft"] = {**blank(), "artist": q}
        else:
            st.session_state["draft"] = {**blank(), "artist": q}

    results = st.session_state.get("results")
    if results is not None and "draft" not in st.session_state:
        if not results:
            st.caption(f"No upcoming dates found for {st.session_state.get('query', '')}.")
        for i, show in enumerate(results[:15]):
            r1, r2, r3 = st.columns([5, 1.3, 1.3], vertical_alignment="center")
            place = ", ".join(x for x in (show["venue"], show["city"], show["state"]) if x)
            r1.markdown(f"**{show['artist']}** · {_when(show['date'])} · {place}"
                        + (f"  \n:gray[{show['notes']}]" if show["notes"] else ""))
            where = already_listed(show)
            if where:
                r2.caption(f"✓ Already {where}")
            else:
                if r2.button("👀 Want to see", key=f"want_{i}", use_container_width=True):
                    add_show(show)
                if r3.button("🎟️ Got tickets", key=f"have_{i}", use_container_width=True):
                    add_show(show, got_tickets=True)
        if st.button("Not listed? Add it yourself"):
            st.session_state["draft"] = {**blank(), "artist": st.session_state.get("query", "")}
            st.rerun()

    draft = st.session_state.get("draft")
    if draft is not None:
        if draft.get("source"):
            st.caption(f"Filled in from {draft['source']}. Fix anything that's off, then save.")
        if already_listed(draft):
            st.info(f"Heads up: {draft['artist']} on that date is already {already_listed(draft)}.")
        show_form(draft)
elif owner and not token:
    st.info("To add shows from this page, add a GitHub token to the app's secrets as GITHUB_TOKEN "
            "(see the setup steps in the README).")

# ------------------------------------------
# 1. Got tickets
# ------------------------------------------
st.subheader("🎫 Got Tickets")
if tickets.empty:
    st.caption("Nothing yet. Press 🎟️ on a watchlist show when you buy tickets.")
else:
    if can_save:
        # Shows marked 🎟️ on this page can be removed or moved back here; setlist.fm ones can't
        bought_rows = watch_raw[bought(watch_raw)]
        for i, t in tickets.iterrows():
            lineup = {_key(a) for a in t["Lineup"].split(", ")}
            mine = bought_rows[(bought_rows["date"] == t["Date"]) & bought_rows["artist"].map(_key).isin(lineup)]
            r1, r2, r3 = st.columns([6, 1.3, 0.5], vertical_alignment="center")
            place = ", ".join(str(x) for x in (t["Venue"], t["City"]) if pd.notna(x) and x)
            r1.markdown(f"**{t['Lineup']}** · {_when(t['Date'])} ({t['When']})" + (f" · {place}" if place else ""))
            if mine.empty:
                r2.caption("From setlist.fm", help="Remove it on setlist.fm, then run ./sync.")
                continue
            show = mine.iloc[0].to_dict()
            if r2.button("↩️ Watchlist", key=f"unbuy_{i}", use_container_width=True,
                         help="Didn't get tickets after all? Moves it back to Want to See."):
                unmark_bought(show)
            if r3.button("🗑️", key=f"tdel_{i}", help="Remove this show"):
                remove_show(show)
    else:
        dated_table(tickets, use_container_width=True, hide_index=True,
                    height=min(400, 38 + 35 * len(tickets)))
    st.caption("Your setlist.fm Upcoming Shows (refreshed with ./sync) plus shows you marked 🎟️ here. "
               "A show drops off once its date passes.")

# ------------------------------------------
# 2. Watchlist
# ------------------------------------------
st.subheader("👀 Want to See")
if watch.empty:
    st.caption("Nothing on your watchlist yet." + (" Add a show above." if can_save else ""))
elif can_save:
    for _, w in watch.iterrows():
        show = watch_raw.loc[w["_row"]].to_dict()
        r1, r2, r3 = st.columns([6, 1.3, 0.5], vertical_alignment="center")
        bits = [f"**{w['Artist']}**", f"{_when(show['date'])}" + (f" ({w['When']})" if show["date"] else "")]
        place = ", ".join(x for x in (w["Venue"], w["City"]) if x)
        if place:
            bits.append(place)
        if w["On Sale"]:
            bits.append(f"**{w['On Sale']}**" if w["On Sale"] == "On sale now" else w["On Sale"])
        if w["Link"]:
            bits.append(f"[Tickets]({w['Link']})")
        r1.markdown(" · ".join(bits) + (f"  \n:gray[{w['Notes']}]" if w["Notes"] else ""))
        if w["Status"] == "🎟️ Got tickets":
            r2.caption("🎟️ Got tickets")
        elif r2.button("🎟️ Got tickets", key=f"bought_{w['_row']}", use_container_width=True,
                       help="Bought tickets? Moves this show to Got Tickets."):
            mark_bought(show)
        if r3.button("🗑️", key=f"remove_{w['_row']}", help="Remove from your watchlist"):
            remove_show(show)
else:
    dated_table(watch.drop(columns="_row"), use_container_width=True, hide_index=True,
                height=min(400, 38 + 35 * len(watch)),
                column_config={"Link": st.column_config.LinkColumn("Link", display_text="Tickets")})

if owner:
    with st.expander("📅 Get reminders in Apple Calendar"):
        feed = f"raw.githubusercontent.com/{REPO}/main/watchlist.ics"
        st.write("Subscribe once and every dated Want to See show appears in your calendar, with alerts "
                 "2 weeks and 1 week before. Pressing 🎟️ Got tickets takes it off the calendar.")
        st.link_button("📅 Subscribe on this device", f"webcal://{feed}")
        st.caption("Or in Calendar on your Mac: File → New Calendar Subscription, paste this, then set "
                   "Auto-refresh to Every hour:")
        st.code(f"https://{feed}", language=None)

if can_save and not watch_raw.empty:
    with st.expander("✏️ Edit details"):
        st.caption("Fix a date, venue or note here, then save. Status \"tickets\" means you've bought them.")
        edited = st.data_editor(
            watch_raw, num_rows="dynamic", use_container_width=True, hide_index=True, key="watch_editor",
            column_config={"status": st.column_config.SelectboxColumn("status", options=["", TICKETS])})
        if st.button("💾 Save changes", disabled=edited.equals(watch_raw)):
            _save(lambda _df: edited, "Watchlist: edit shows", "Saved your changes.")
