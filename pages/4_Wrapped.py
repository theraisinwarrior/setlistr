"""Concert Wrapped: a shareable year-in-review of your concerts."""
from datetime import datetime
from html import escape

import streamlit as st

from analytics.wrapped import available_years, wrapped_summary
from data.attendance import apply_venue_overrides, process_attendance
from data.snapshots import load_snapshot
from data.store import load_csv_attendance, load_venue_overrides, sync_attended_shows
from services.auth import get_setlist_api_key
from services.setlistfm import SetlistFmError

st.title("🎁 Concert Wrapped")
st.caption("Your year in live music. Screenshot the card to share it.")

api_key = get_setlist_api_key()
username = st.secrets.get("SETLISTFM_USERNAME", "raisinwarrior")

raw = None
if api_key:
    try:
        with st.spinner("Loading your concerts from setlist.fm..."):
            raw = sync_attended_shows(username, api_key)
        if raw is not None and not raw.empty:
            raw, _ = apply_venue_overrides(raw, load_venue_overrides())
    except SetlistFmError as e:
        st.warning(f"{e} Showing the saved CSV instead.")
if raw is None or raw.empty:
    try:
        raw = load_csv_attendance()
    except FileNotFoundError:
        st.info("No concert data yet. Mark shows as attended on setlist.fm.")
        st.stop()

df_att, _, _ = process_attendance(raw)
years = available_years(df_att)
if not years:
    st.info("No dated concerts found.")
    st.stop()

choices = [str(y) for y in years] + ["All Time"]
pick = st.segmented_control("Year", choices, default=choices[0], key="wrapped_year") or choices[0]
year = None if pick == "All Time" else int(pick)


def _table(state_key, snap_kind):
    res = st.session_state.get(state_key)
    if res and not res["table"].empty:
        return res["table"]
    snap = load_snapshot(snap_kind)
    return snap["table"] if snap else None


w = wrapped_summary(df_att, year, _table("rare_result", "rare_songs"), _table("pop_result", "artist_popularity"))
if not w:
    st.info(f"No concerts in {pick}.")
    st.stop()

e = {k: escape(str(v)) for k, v in w.items()}


def stat(value, label):
    return (f'<div style="flex:1 1 120px;min-width:110px;">'
            f'<div style="font-size:2.4rem;font-weight:800;line-height:1.1;">{value}</div>'
            f'<div style="font-size:0.85rem;opacity:0.85;text-transform:uppercase;letter-spacing:0.06em;">{label}</div></div>')


def line(label, value):
    return (f'<div style="margin-top:0.9rem;"><div style="font-size:0.8rem;opacity:0.8;text-transform:uppercase;'
            f'letter-spacing:0.06em;">{label}</div><div style="font-size:1.25rem;font-weight:700;">{value}</div></div>')


lines = [line("Top artist", f"{e['top_artist']} · {w['top_artist_count']}×"),
         line("Home venue", f"{e['top_venue']} · {w['top_venue_count']}×")]
if "rarest_song" in w:
    lines.append(line("Rarest song you heard", f"{e['rarest_song']} <span style='opacity:0.8;font-weight:400;'>"
                                              f"({e['rarest_detail']})</span>"))
if "top_song" in w:
    lines.append(line("Most heard song", f"{e['top_song']} · {w['top_song_count']}×"))
if "biggest_act" in w:
    lines.append(line("Biggest act", e["biggest_act"]))
if "farthest" in w:
    lines.append(line("Farthest trip", e["farthest"]))

card = f"""
<div style="background:linear-gradient(135deg,#1DB954 0%,#0f6b8f 55%,#5b2a86 100%);color:#fff;
            border-radius:18px;padding:28px 30px;margin:8px 0 18px 0;box-shadow:0 6px 24px rgba(0,0,0,0.18);">
  <div style="font-size:0.9rem;letter-spacing:0.12em;text-transform:uppercase;opacity:0.9;">Setlistr · {escape(username)}</div>
  <div style="font-size:2.2rem;font-weight:800;margin:4px 0 18px 0;">{e['label']} Concert Wrapped 🎁</div>
  <div style="display:flex;flex-wrap:wrap;gap:18px;">
    {stat(w['concerts'], 'concerts')}{stat(w['artists'], 'artists')}{stat(f"{w['songs']:,}", 'songs heard')}{stat(w['hours'], 'hours of music')}
  </div>
  <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:0 28px;">
    {''.join(lines)}
  </div>
</div>
"""
# one line, so Markdown never mistakes indented HTML for a code block
st.markdown("".join(part.strip() for part in card.splitlines()), unsafe_allow_html=True)

m1, m2, m3, m4 = st.columns(4)
if year is not None:
    delta = w["concerts"] - w.get("prev_concerts", 0)
    m1.metric("Concerts", w["concerts"], f"{delta:+d} vs {year - 1}" if w.get("prev_concerts") else None)
    m2.metric("New artists", w["new_artists"], help="Artists you saw live for the first time that year.")
else:
    m1.metric("Concerts", w["concerts"])
    m2.metric("Sets seen", w["sets"])
m3.metric("Venues", w["venues"])
m4.metric("Cities", w["cities"])

d1, d2 = st.columns(2)
with d1:
    st.markdown(f"**🗓️ Busiest month:** {w['busiest_month']} ({w['busiest_month_count']} concerts)")
    st.markdown(f"**🎬 First show:** {w['first_show']}")
    st.markdown(f"**🎬 Last show:** {w['last_show']}")
with d2:
    if "smallest_act" in w:
        st.markdown(f"**💎 Smallest act:** {w['smallest_act']}")
    st.markdown(f"**🎤 Sets seen:** {w['sets']} (openers and headliners)")
    if year is not None and year == datetime.now().year:
        st.caption("This year isn't over yet, so the numbers will keep growing.")
