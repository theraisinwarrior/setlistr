"""Compare with a Friend: two setlist.fm concert histories side by side."""
import streamlit as st

from analytics.compare import compare_histories
from data.attendance import process_attendance
from data.store import sync_attended_shows
from services.auth import get_setlist_api_key
from services.setlistfm import SetlistFmError

st.title("🤝 Compare with a Friend")
st.caption("Put two setlist.fm profiles side by side: artists you've both seen, venues you share, "
           "and concerts you were both at, maybe without knowing it.")

api_key = get_setlist_api_key()
default_me = st.secrets.get("SETLISTFM_USERNAME", "raisinwarrior")

with st.form("compare_form"):
    c1, c2 = st.columns(2)
    me_input = c1.text_input("Your setlist.fm username", value=default_me)
    friend_input = c2.text_input("Friend's setlist.fm username", placeholder="their username")
    submitted = st.form_submit_button("🤝 Compare", use_container_width=True)
if submitted:
    st.session_state["compare_pair"] = (me_input.strip(), friend_input.strip())

pair = st.session_state.get("compare_pair")
if not api_key:
    st.warning("Add a Setlist.fm API key to compare profiles.")
    st.stop()
if not pair or not pair[0] or not pair[1]:
    st.info("Enter a friend's setlist.fm username and click Compare. It works with anyone who marks "
            "the concerts they went to as \"I was there\" on setlist.fm.")
    st.stop()

me, friend = pair
if me.lower() == friend.lower():
    st.warning("That's the same username twice. Enter a friend's username to compare.")
    st.stop()

try:
    with st.spinner(f"Loading concerts for {me} and {friend} from setlist.fm..."):
        raw_me = sync_attended_shows(me, api_key)
        raw_friend = sync_attended_shows(friend, api_key)
except SetlistFmError as e:
    st.error(str(e))
    st.stop()

if raw_me.empty:
    st.info(f"{me} hasn't marked any concerts as attended on setlist.fm yet.")
    st.stop()
if raw_friend.empty:
    st.info(f"{friend} hasn't marked any concerts as attended on setlist.fm yet.")
    st.stop()

df_me, _, _ = process_attendance(raw_me)
df_friend, _, _ = process_attendance(raw_friend)
res = compare_histories(df_me, df_friend)
s = res["stats"]

union = s["my_artists"] + s["their_artists"] - s["shared_artists"]
overlap = round(100 * s["shared_artists"] / union) if union else 0

m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("Your concerts", s["my_concerts"])
m2.metric(f"{friend}'s concerts", s["their_concerts"])
m3.metric("Artists in common", s["shared_artists"])
m4.metric("Same concerts", s["same_shows"])
m5.metric("Taste overlap", f"{overlap}%",
          help="Artists you've both seen, as a share of every artist either of you has seen.")

st.divider()
st.subheader("🎉 Concerts you were both at")
if res["same_shows"].empty:
    st.caption("No shared concerts yet. Time to buy two tickets.")
else:
    st.success(f"You and {friend} were at {s['same_shows']} of the same concert"
               f"{'s' if s['same_shows'] != 1 else ''}!")
    st.dataframe(res["same_shows"], use_container_width=True, hide_index=True)

st.subheader("🎤 Artists you've both seen")
if res["shared_artists"].empty:
    st.caption("No artists in common yet.")
else:
    st.dataframe(res["shared_artists"].rename(columns={"Them": friend}), use_container_width=True,
                 hide_index=True, height=min(400, 38 + 35 * len(res["shared_artists"])))

o1, o2 = st.columns(2)
with o1:
    st.markdown(f"**Only you've seen** (your picks for {friend})")
    st.dataframe(res["only_me"], use_container_width=True, hide_index=True)
with o2:
    st.markdown(f"**Only {friend} has seen** (their picks for you)")
    st.dataframe(res["only_them"], use_container_width=True, hide_index=True)

if res["shared_venues"]:
    with st.expander(f"🏟️ {len(res['shared_venues'])} venues you've both been to"):
        st.write(", ".join(res["shared_venues"]))
