"""Concert Passport: personal attendance dashboard."""
from datetime import datetime

import pandas as pd
import plotly.express as px
import spotipy
import streamlit as st

from data.attendance import apply_venue_overrides, extract_covers, process_attendance, split_upcoming
from data.display import dated_table
from analytics.career import (career_plan, career_rare_songs, drop_covers, floor_by_times_heard,
                              pages_needed,
                              show_position, summarize_history)
from analytics.early_fans import (early_fan_table, find_early_sightings, position_key, position_plan,
                                  rank_early_table)
from analytics.nights import night_options, night_playlist_name, night_tracklist
from analytics.passport_stats import compute_highlights, venue_top_performers
from analytics.popularity import artists_to_scan, rank_artists_by_popularity
from analytics.upcoming import upcoming_table
from data.snapshots import friendly_date, load_snapshot, snapshot_bytes
from data.store import (clear_sync_cache, get_artist_show_count,
                        get_artist_setlist_page,
                        load_csv_attendance, load_venue_overrides, sync_attended_shows)
from services.auth import (get_active_token, get_authorize_url, get_setlist_api_key,
                           is_spotify_connected)
from services.setlistfm import SetlistFmError
from services.spotify_export import create_playlist

SPOTIFY_GREEN = "#1DB954"


def last_checked(result: dict, button: str) -> None:
    """One status line for the slow scans: when the numbers were last checked, and where they came from."""
    snap = result.get("snapshot")
    when = friendly_date(snap.get("created") if snap else result.get("checked"))
    source = "saved results" if snap else "live scan"
    st.caption(f"🕒 Last checked {when} · {source}. Click **{button}** to refresh.")

st.title("🎫 My Concert Passport")
st.caption("Visualizing personal concert attendance history logged on Setlist.fm")

# ------------------------------------------
# Data source: live sync from setlist.fm (CSV is the fallback)
# ------------------------------------------
default_username = st.secrets.get("SETLISTFM_USERNAME", "raisinwarrior")
api_key_for_sync = get_setlist_api_key()

u_col, b_col = st.columns([3, 1], vertical_alignment="bottom")
with u_col:
    username = st.text_input("setlist.fm username", value=default_username,
                             help="Your attended shows are pulled from your public setlist.fm profile.")
with b_col:
    if st.button("🔄 Refresh from setlist.fm", use_container_width=True):
        clear_sync_cache()
        st.rerun()

raw_attendance = None
venues_needing_coords = None
if username.strip() and api_key_for_sync:
    try:
        with st.spinner(f"Syncing attended shows for {username.strip()} from setlist.fm "
                        "(the first load can take a bit if you have a lot of shows)..."):
            raw_attendance = sync_attended_shows(username.strip(), api_key_for_sync)
        if raw_attendance.empty:
            st.info(f"No attended shows found for '{username.strip()}'. "
                    "Mark shows as attended on setlist.fm and refresh.")
            st.stop()
        # setlist.fm only knows city-level coordinates, so use the hand-fixed venue ones
        raw_attendance, venues_needing_coords = apply_venue_overrides(
            raw_attendance, load_venue_overrides())
        st.caption(f"✅ Synced {len(raw_attendance)} setlists from setlist.fm "
                   f"for **{username.strip()}** (refreshes automatically once a day).")
    except SetlistFmError as e:
        st.warning(f"{e} Showing the saved CSV instead.")
elif not api_key_for_sync:
    st.warning("Add a Setlist.fm API key to sync live. Showing the saved CSV instead.")

try:
    if raw_attendance is None:
        raw_attendance = load_csv_attendance()
    # Shows you've marked for the future get their own section and stay out of every stat below
    raw_attendance, raw_upcoming = split_upcoming(raw_attendance)
    upcoming = upcoming_table(raw_upcoming)
    if raw_attendance.empty:
        if not upcoming.empty:
            st.subheader("🗓️ Upcoming Shows")
            dated_table(upcoming, use_container_width=True, hide_index=True)
        st.info("No past concerts yet. Your stats will appear here after your first show.")
        st.stop()
    df_att, df_concerts, df_songs = process_attendance(raw_attendance)

    # 1. Key metric cards
    total_sets = len(df_att[['eventDate_dt', 'venue', 'artist']].drop_duplicates())
    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Total Concerts", len(df_concerts))
    col2.metric("Total Sets Seen", total_sets,
                help="Every performer's set you've watched. Openers and headliners each count, "
                     "so a night with 3 acts is 1 concert but 3 sets.")
    col3.metric("Unique Artists", df_att['artist'].nunique())
    col4.metric("Venues Visited", df_concerts['venue'].nunique())
    col5.metric("Cities Visited", df_concerts['city'].nunique())

    # 1a. Upcoming shows
    st.subheader("🗓️ Upcoming Shows")
    if upcoming.empty:
        st.caption("No upcoming shows. Mark a future concert as attended on setlist.fm and it shows up here "
                   "(it won't count toward your stats until it happens).")
    else:
        nxt = upcoming.iloc[0]
        n1, n2 = st.columns([2, 1])
        n1.metric("Next up", nxt["Lineup"].split(", ")[0], f"{nxt['When']} · {nxt['Venue']}", delta_color="off")
        n2.metric("Shows on the calendar", len(upcoming))
        dated_table(upcoming, use_container_width=True, hide_index=True,
                    height=min(400, 38 + 35 * len(upcoming)))

    # 1b. Highlights & badges
    hl = compute_highlights(df_att, df_concerts, df_songs)
    if hl:
        st.subheader("✨ Highlights")
        h1, h2, h3, h4 = st.columns(4)
        h1.metric("Songs Heard Live", f"{hl['total_songs']:,}")
        h2.metric("Different Songs", f"{hl['unique_songs']:,}")
        h3.metric("Hours of Live Music", f"~{hl['est_hours']:,}",
                  help="Estimate: songs heard × about 4 minutes each.")
        if "farthest_miles" in hl:
            h4.metric("Farthest Show", f"{hl['farthest_miles']:,} mi",
                      help=f"{hl['farthest_show']}. Distance is from your home base: {hl['home_base']}.")

        g1, g2, g3, g4 = st.columns(4)
        if "busiest_month" in hl:
            g1.metric("Busiest Month", hl['busiest_month'], f"{hl['busiest_month_count']} shows", delta_color="off")
            g2.metric("Favorite Night Out", hl['favorite_weekday'])
        g3.metric("Longest Streak", f"{hl['longest_month_streak']} mo",
                  help="Most consecutive months with at least one concert.")
        if "longest_break_days" in hl:
            g4.metric("Longest Break", f"{hl['longest_break_days']:,} days", help=hl['longest_break_range'])

        if hl["on_this_day"]:
            st.info("📅 **On this day:** " + "  |  ".join(hl["on_this_day"]))

        earned = sum(b["earned"] for b in hl["badges"])
        with st.expander(f"🏅 Badges ({earned}/{len(hl['badges'])} earned)"):
            cols = st.columns(4)
            for i, b in enumerate(hl["badges"]):
                with cols[i % 4].container(border=True):
                    st.markdown(f"### {b['icon'] if b['earned'] else '🔒'} {b['name']}")
                    st.caption(b["desc"])
                    st.write("✅ Earned!" if b["earned"] else f"Progress: {b['progress']}")

    st.divider()

    # 2. Charts row
    c1, c2 = st.columns(2)

    with c1:
        st.subheader("Concerts Attended per Year")
        yearly_counts = df_concerts.groupby('year').size().reset_index(name='concerts')
        fig_year = px.bar(yearly_counts, x='year', y='concerts', text='concerts',
                          color_discrete_sequence=[SPOTIFY_GREEN])
        fig_year.update_layout(xaxis_title="Year", yaxis_title="Number of Concerts",
                               height=420, margin=dict(l=10, r=10, t=10, b=10))
        st.plotly_chart(fig_year, use_container_width=True)

    with c2:
        st.subheader("🎤 Repeat Artists")

        artist_counts = df_att['artist'].value_counts().reset_index()
        artist_counts.columns = ['artist', 'count']
        multi_artists = (artist_counts[artist_counts['count'] >= 2]
                         .sort_values(['count', 'artist'], ascending=[False, True]))

        if multi_artists.empty:
            st.info("No repeat artists yet. See someone twice and they'll show up here.")
        else:
            st.caption(f"{len(multi_artists)} artists you've seen more than once. Scroll for the full list.")
            with st.container(height=380):
                fig_artists = px.bar(multi_artists, x='count', y='artist', orientation='h',
                                     text='count', color_discrete_sequence=[SPOTIFY_GREEN])
                fig_artists.update_layout(
                    yaxis=dict(autorange="reversed", automargin=True),
                    xaxis=dict(title="Times seen", dtick=1),
                    yaxis_title="", showlegend=False,
                    height=max(340, len(multi_artists) * 30),
                    margin=dict(l=0, r=30, t=10, b=10),
                )
                fig_artists.update_traces(textposition='outside', textangle=0, cliponaxis=False,
                                          hovertemplate='%{y}: seen %{x} times<extra></extra>')
                st.plotly_chart(fig_artists, use_container_width=True)

    st.divider()

    # 3. Geographic footprint map
    st.subheader("Geographic Footprint")
    st.caption("💡 Hover over or click any green pin to view venue stats!")
    map_mode = st.radio("Map mode", ["Interactive", "Simple (better on phones)"],
                        horizontal=True, label_visibility="collapsed",
                        help="If the map flickers or fights with scrolling on your phone, "
                             "use Simple: a still map plus a venue table.")
    simple_map = map_mode.startswith("Simple")

    map_data = df_concerts.dropna(subset=['lat', 'long']).copy()

    venue_summary = (map_data.groupby('venue', as_index=False)
                     .agg(City=('city', 'first'), State=('state', 'first'),
                          **{'Concerts Attended': ('city', 'size')}))
    top_performers = venue_top_performers(df_att)
    venue_summary['Most Seen Here'] = venue_summary['venue'].map(top_performers)
    coords_df = map_data[['venue', 'lat', 'long']].drop_duplicates(subset=['venue'])
    venue_summary = venue_summary.merge(coords_df, on='venue', how='left')

    map_fn = getattr(px, "scatter_map", getattr(px, "scatter_mapbox", None))

    map_kwargs = {
        "data_frame": venue_summary,
        "lat": "lat",
        "lon": "long",
        "size": "Concerts Attended",
        "size_max": 22,
        "color_discrete_sequence": [SPOTIFY_GREEN],
        "hover_name": "venue",
        "hover_data": {"lat": False, "long": False, "City": True, "State": True,
                       "Concerts Attended": True, "Most Seen Here": True},
        "zoom": 10,
        "center": {"lat": 40.7500, "lon": -73.9800},
        "height": 520,
    }
    if hasattr(px, "scatter_map"):
        map_kwargs["map_style"] = "carto-darkmatter"
    else:
        map_kwargs["mapbox_style"] = "carto-darkmatter"

    fig_map = map_fn(**map_kwargs)
    fig_map.update_traces(marker=dict(opacity=0.9))
    fig_map.update_layout(
        margin={"r": 0, "t": 0, "l": 0, "b": 0},
        hoverlabel=dict(bgcolor="#191414", font_size=13, font_family="sans-serif",
                        font_color="#FFFFFF"),
    )
    fig_map.update_layout(uirevision="footprint")  # keep the zoom/position steady when the page reruns
    if simple_map:
        # A still image of the map: no touch handling, so no flicker and the page scrolls normally.
        st.plotly_chart(fig_map, use_container_width=True,
                        config={"staticPlot": True, "displayModeBar": False})
        venue_table = (venue_summary[['venue', 'City', 'State', 'Concerts Attended', 'Most Seen Here']]
                       .rename(columns={'venue': 'Venue'})
                       .sort_values('Concerts Attended', ascending=False))
        venue_table['Most Seen Here'] = venue_table['Most Seen Here'].str.replace('<br>', ', ', regex=False)
        st.dataframe(venue_table, use_container_width=True, hide_index=True, height=300)
    else:
        st.plotly_chart(fig_map, use_container_width=True, config={"displaylogo": False})

    if venues_needing_coords is not None and not venues_needing_coords.empty:
        with st.expander(f"📍 {len(venues_needing_coords)} venue(s) need exact map coordinates"):
            st.write("These venues have no saved coordinates, so setlist.fm's city-level "
                     "location is used and they may stack on top of each other.")
            st.dataframe(venues_needing_coords, use_container_width=True, hide_index=True)
            st.markdown("**To fix one:** open `venue_coordinates.csv` in your GitHub repo, click the pencil to "
                        "edit, and add a line for each venue. Get the numbers by right-clicking the spot in "
                        "Google Maps (the first number is lat, the second is long). Copy these lines and "
                        "fill in the two numbers:")
            def _csv(v):
                v = str(v)
                return f'"{v}"' if "," in v else v
            st.code("\n".join(f"{_csv(r.venue)},{_csv(r.city)},LAT,LONG"
                               for r in venues_needing_coords.itertuples()),
                    language="text")

    st.divider()

    # 4. Song analytics
    if not df_songs.empty:
        st.subheader("🎵 Song Analytics")
        s_col1, s_col2 = st.columns(2)

        with s_col1:
            st.markdown("### Most Heard Tracks Live")
            top_tracks = (df_songs.groupby(['song', 'artist', 'track_artist']).size()
                          .reset_index(name='Times Heard'))
            repeat_tracks = (top_tracks[top_tracks['Times Heard'] >= 2]
                             .sort_values(['Times Heard', 'track_artist'], ascending=[False, True]))

            if repeat_tracks.empty:
                st.info("You haven't heard any song live more than once yet.")
            else:
                st.caption(f"{len(repeat_tracks)} songs you've heard at least twice. Scroll for the full list.")
                with st.container(height=450):
                    fig_top_songs = px.bar(repeat_tracks, x='Times Heard', y='track_artist',
                                           orientation='h', text='Times Heard',
                                           color_discrete_sequence=[SPOTIFY_GREEN])
                    fig_top_songs.update_layout(
                        yaxis=dict(autorange="reversed", automargin=True),
                        xaxis=dict(title="Times heard live", dtick=1),
                        yaxis_title="", showlegend=False,
                        height=max(420, len(repeat_tracks) * 30),
                        margin=dict(l=0, r=30, t=10, b=10),
                    )
                    fig_top_songs.update_traces(textposition='outside', textangle=0, cliponaxis=False,
                                                hovertemplate='%{y}: heard %{x} times<extra></extra>')
                    st.plotly_chart(fig_top_songs, use_container_width=True)

        with s_col2:
            st.markdown("### 💎 Rarest Songs You've Heard")
            st.caption("Every song you've heard live, ranked by how few times the artist has played it "
                       "across their 200 most recent shows on setlist.fm (their whole history if they have "
                       "fewer). Your own concerts are included in the count.")

            career = career_plan(df_att)
            rare_snap = load_snapshot("rare_songs")
            if rare_snap and "Times Played" not in rare_snap["table"].columns:
                rare_snap = None  # an older snapshot from the previous method
            if not api_key_for_sync:
                if not rare_snap:
                    st.warning("Add a Setlist.fm API key to find rare songs.")
            elif not career:
                if not rare_snap:
                    st.info("This needs the live setlist.fm sync (the saved CSV has no artist IDs).")
            else:
                size_snap = load_snapshot("artist_popularity")
                sizes = (dict(zip(size_snap["table"]["Artist"], size_snap["table"]["Shows Tracked"]))
                         if size_snap else {})
                est_calls = sum(pages_needed({"total": int(sizes.get(a_, 200)), "per_page": 20})
                                for a_, _ in career)
                st.caption(f"{len(career)} artists, about {est_calls:,} setlist.fm lookups "
                           f"(~{max(1, round(est_calls * 0.7 / 60))} min the first time). Results are "
                           "remembered for a week, so if it stops early, click again to continue.")

                if st.button("🔍 Find my rarest songs", use_container_width=True):
                    histories, hit_limit = {}, False
                    progress = st.progress(0.0, text="Starting...")
                    for i, (artist, mbid) in enumerate(career):
                        progress.progress(i / len(career), text=f"Checking {artist}: {i + 1} of {len(career)}")
                        try:
                            first_page = get_artist_setlist_page(mbid, 1, api_key_for_sync)
                            artist_pages = [first_page] + [
                                get_artist_setlist_page(mbid, pg, api_key_for_sync)
                                for pg in range(2, pages_needed(first_page) + 1)]
                        except SetlistFmError:
                            hit_limit = True
                            break
                        histories[mbid] = summarize_history(artist_pages)
                    progress.empty()
                    table, stats = career_rare_songs(df_att, histories)
                    st.session_state["rare_result"] = {"table": table, "stats": stats, "hit_limit": hit_limit,
                                                       "checked": datetime.now().strftime("%Y-%m-%d")}

            res = st.session_state.get("rare_result")
            if res is not None and "Times Played" not in res["table"].columns:
                res = None
            if res is None and rare_snap and not rare_snap["table"].empty:
                res = {"table": rare_snap["table"], "stats": rare_snap.get("stats") or {},
                       "hit_limit": False, "snapshot": rare_snap}
            if res:
                table, stats = res["table"], res["stats"]
                full_table = table  # what gets saved as a snapshot (covers are filtered when shown)
                last_checked(res, "Find my rarest songs")
                table = floor_by_times_heard(table, df_att)
                if not st.toggle("Include cover songs", value=False, key="rare_covers",
                                 help="Covers are often one-off tributes, so they're hidden by default."):
                    table = drop_covers(table, df_att)
                if res["hit_limit"]:
                    st.warning("setlist.fm's request limit was hit, so this list is partial. Click the button "
                               "again later; everything already checked is remembered for a week.")
                if table.empty:
                    st.info("No songs could be scored yet.")
                else:
                    max_played = st.slider("Show songs played at most this many times", 1, 50, 10)
                    shown = table[table["Times Played"] <= max_played]
                    top = table.iloc[0]
                    st.metric("Rarest song you've heard", top["Song"],
                              f"{top['Artist']} · played in {top['Played In']}", delta_color="off")
                    st.success(f"{len(shown)} songs played {max_played} times or fewer, across "
                               f"{stats.get('scored_shows', 0)} concerts.")
                    dated_table(shown[["Song", "Artist", "Heard On", "Played In"]].head(300),
                                 use_container_width=True, hide_index=True, height=300)
                    notes = []
                    if stats.get("skipped_small"):
                        notes.append(f"{stats['skipped_small']} by artists with fewer than 20 shows logged")
                    if stats.get("skipped_old"):
                        notes.append(f"{stats['skipped_old']} older than that artist's last 200 shows")
                    if stats.get("skipped_short"):
                        notes.append(f"{stats['skipped_short']} with fewer than 3 songs logged")
                    if stats.get("unchecked"):
                        notes.append(f"{stats['unchecked']} not checked yet")
                    if notes:
                        st.caption("Concerts left out: " + "; ".join(notes) + ".")
                    if not res.get("snapshot") and not res["hit_limit"]:
                        st.download_button(
                            "💾 Save as snapshot", file_name="rare_songs.json", mime="application/json",
                            data=snapshot_bytes("rare_songs", full_table, stats=stats),
                            help="Put this file in the snapshots folder on GitHub so these results "
                                 "show instantly next time.")

        st.divider()

    # 4b. Covers
    st.subheader("🎸 Covers")
    df_covers = extract_covers(df_att)
    if df_covers.empty:
        st.caption("No covers found. Cover info comes from the live setlist.fm sync, so it won't "
                   "appear if the saved CSV is being used.")
    else:
        cv1, cv2, cv3, cv4 = st.columns(4)
        cv1.metric("Covers Heard Live", len(df_covers))
        cv2.metric("Different Covers", len(df_covers[['Song', 'Original Artist']].drop_duplicates()))
        most_covered = df_covers['Original Artist'].value_counts()
        cv3.metric("Most-Covered Artist", most_covered.index[0], f"{most_covered.iloc[0]} times",
                   delta_color="off")
        top_coverer = df_covers['Performed By'].value_counts()
        cv4.metric("Covers The Most", top_coverer.index[0], f"{top_coverer.iloc[0]} covers",
                   delta_color="off")
        dated_table(df_covers.drop(columns='eventDate_dt'), use_container_width=True,
                     hide_index=True, height=300)

    st.divider()

    # 4c. Big names & hidden gems
    st.subheader("🌟 Big Names & Hidden Gems")
    st.caption("How famous are the acts you've seen? setlist.fm doesn't publish crowd sizes, so this counts "
               "how many of each artist's concerts are logged on setlist.fm. Big touring acts have "
               "thousands; small bands have a handful.")

    pop_plan = artists_to_scan(df_att)
    pop_snap = load_snapshot("artist_popularity")
    if not api_key_for_sync:
        if not pop_snap:
            st.warning("Add a Setlist.fm API key to rank your artists.")
    elif not pop_plan:
        if not pop_snap:
            st.info("This needs the live setlist.fm sync (the saved CSV has no artist IDs).")
    else:
        st.caption(f"{len(pop_plan)} artists to check, about {max(1, round(len(pop_plan) * 0.9 / 60))} "
                   "min the first time. Results are remembered for a week.")

        if st.button("📊 Rank my artists by popularity", use_container_width=True):
            pop_counts, pop_hit_limit = {}, False
            pop_progress = st.progress(0.0, text="Starting...")
            for i, (artist, mbid) in enumerate(pop_plan):
                pop_progress.progress(i / len(pop_plan), text=f"Checking {artist}: {i + 1} of {len(pop_plan)}")
                try:
                    pop_counts[mbid] = get_artist_show_count(mbid, api_key_for_sync)
                except SetlistFmError:
                    pop_hit_limit = True
                    break
            pop_progress.empty()
            st.session_state["pop_result"] = {
                "table": rank_artists_by_popularity(df_att, pop_counts),
                "hit_limit": pop_hit_limit,
                "checked": datetime.now().strftime("%Y-%m-%d"),
            }

    pop = st.session_state.get("pop_result")
    if pop is None and pop_snap and not pop_snap["table"].empty:
        pop = {"table": pop_snap["table"], "hit_limit": False, "snapshot": pop_snap}
    if pop:
        pop_table = pop["table"]
        last_checked(pop, "Rank my artists by popularity")
        if pop["hit_limit"]:
            st.warning("setlist.fm's request limit was hit, so this list is partial. Click the button "
                       "again in a bit; everything already checked is remembered.")
        if pop_table.empty:
            st.info("No artists could be ranked yet.")
        else:
            k = min(10, max(1, len(pop_table) // 2))
            biggest, smallest = pop_table.iloc[0], pop_table.iloc[-1]
            m1, m2 = st.columns(2)
            m1.metric("Biggest act you've seen", biggest["Artist"],
                      f"{int(biggest['Shows Tracked']):,} shows logged", delta_color="off")
            m2.metric("Smallest act you've seen", smallest["Artist"],
                      f"{int(smallest['Shows Tracked']):,} shows logged", delta_color="off")

            pc1, pc2 = st.columns(2)
            pop_cfg = {"Shows Tracked": st.column_config.NumberColumn("Shows Logged", format="%d")}
            with pc1:
                st.markdown("**Biggest acts**")
                dated_table(pop_table.head(k), column_config=pop_cfg, use_container_width=True,
                             hide_index=True)
            with pc2:
                st.markdown("**Hidden gems**")
                gems = pop_table.tail(k).sort_values(["Shows Tracked", "Artist"])
                dated_table(gems, column_config=pop_cfg, use_container_width=True, hide_index=True)
            if not pop.get("snapshot") and not pop["hit_limit"]:
                st.download_button(
                    "💾 Save as snapshot", file_name="artist_popularity.json", mime="application/json",
                    data=snapshot_bytes("artist_popularity", pop_table),
                    help="Put this file in the snapshots folder on GitHub so these results "
                         "show instantly next time.")

    st.divider()

    # 4d. Saw them before they were big
    st.subheader("🌱 Saw Them Before They Were Big")
    st.caption("Acts you caught as an opener or lower on a festival bill. At shows with several acts, "
               "the act that played the most songs counts as the headliner.")
    sightings = find_early_sightings(df_att)
    if sightings.empty:
        st.info("No opening acts found yet.")
    else:
        e1, e2 = st.columns(2)
        e1.metric("Openers you've caught", len(sightings))
        e2.metric("Later saw them headline", int(sightings["headline_dt"].notna().sum()))
        for r in sightings[sightings["headline_dt"].notna()].sort_values("eventDate_dt").itertuples():
            st.markdown(f"- **{r.artist}** opened for {r.opened_for} ({r.eventDate_dt:%b %Y}) → you later "
                        f"saw them headline **{r.headline_venue}** ({r.headline_dt:%b %Y})")

        p_plan = position_plan(sightings)
        early_snap = load_snapshot("early_fans")
        if early_snap and "Shows Before" not in early_snap["table"].columns:
            early_snap = None  # an older snapshot from the previous method
        if api_key_for_sync and p_plan:
            st.caption("Measure each act's glow-up: how many shows they'd logged on setlist.fm before the night "
                       f"you saw them, and how many since. {len(p_plan)} acts, a few lookups each "
                       f"(~{max(1, round(len(p_plan) * 4 * 0.7 / 60))} min the first time).")
            if st.button("📈 Measure their growth", use_container_width=True):
                positions, early_hit = {}, False
                today = datetime.now().date()
                early_progress = st.progress(0.0, text="Starting...")
                for i, (artist, mbid, when) in enumerate(p_plan):
                    early_progress.progress(i / len(p_plan), text=f"Checking {artist}: {i + 1} of {len(p_plan)}")
                    try:
                        pos = show_position(lambda pg, m=mbid: get_artist_setlist_page(m, pg, api_key_for_sync),
                                            when.date(), today)
                    except SetlistFmError:
                        early_hit = True
                        break
                    if pos:
                        positions[position_key(mbid, when)] = pos
                early_progress.empty()
                st.session_state["early_result"] = {"positions": positions, "hit_limit": early_hit,
                                                    "checked": datetime.now().strftime("%Y-%m-%d")}

        early_res = st.session_state.get("early_result")
        if early_res is not None and "positions" not in early_res:
            early_res = None
        early_from_snap = False
        if early_res:
            early_table = early_fan_table(sightings, early_res["positions"])
            last_checked(early_res, "Measure their growth")
            if early_res["hit_limit"]:
                st.warning("setlist.fm's request limit was hit, so this is only partly measured. Click the "
                           "button again later; everything already checked is remembered.")
        elif early_snap and not early_snap["table"].empty:
            early_table, early_from_snap = rank_early_table(early_snap["table"]), True
            last_checked({"snapshot": early_snap}, "Measure their growth")
        else:
            early_table = early_fan_table(sightings)

        glow_labels = early_table["Glow-up"].fillna("").astype(str)
        grown = early_table[glow_labels.str.startswith("×") | glow_labels.str.startswith("Their first")]
        if not grown.empty:
            best = grown.iloc[0]
            since_n = int(best["Shows Since"])
            if str(best["Glow-up"]).startswith("Their first"):
                detail = (f"You were at their first logged show, opening for {best['Opened For']} "
                          f"({best['Date']}). {since_n:,} shows since.")
            else:
                detail = (f"{int(best['Shows Before']):,} shows before you saw them open for {best['Opened For']} "
                          f"({best['Date']}), {since_n:,} since ({best['Glow-up']})")
            st.metric("Biggest glow-up", best["Artist"], detail, delta_color="off")
        dated_table(
            early_table, use_container_width=True, hide_index=True, height=350,
            column_config={
                "Shows Before": st.column_config.NumberColumn(
                    "Shows Before", format="%d", help="Their shows logged on setlist.fm before the night you saw them."),
                "Shows Since": st.column_config.NumberColumn(
                    "Shows Since", format="%d", help="Their shows logged since then (not counting announced "
                    "future dates)."),
                "Glow-up": st.column_config.TextColumn(
                    "Glow-up", help="Shows since divided by shows before. Acts with fewer than 20 shows "
                    "logged aren't ranked."),
            })
        if early_res and not early_res["hit_limit"] and not early_from_snap:
            st.download_button(
                "💾 Save as snapshot", file_name="early_fans.json", mime="application/json",
                data=snapshot_bytes("early_fans", early_table),
                help="Put this file in the snapshots folder on GitHub so these results show instantly next time.")

    st.divider()

    # 4e. Relive a night
    st.subheader("🎟️ Relive a Night")
    st.caption("Pick any concert you went to and turn that night's setlist into a Spotify playlist, "
               "in the order it was played.")
    nights = night_options(df_att)
    if not nights:
        st.info("Setlists for your concerts come from the setlist.fm sync, and none were found.")
    else:
        night_labels = [n["label"] for n in nights]
        night_pick = st.selectbox("Concert", night_labels, key="relive_pick")
        night = nights[night_labels.index(night_pick)]
        relive_openers = st.checkbox("Include opening acts", value=True, key="relive_openers")
        night_tracks = night_tracklist(df_att, night["day"], night["venue"], relive_openers)
        st.dataframe(night_tracks.drop(columns="Original"), hide_index=True, use_container_width=True,
                     height=min(400, 38 + 35 * len(night_tracks)))

        if not is_spotify_connected():
            st.info("Connect Spotify in the sidebar to save this night as a playlist.")
            st.link_button("🎵 Connect Spotify", get_authorize_url())
        elif st.button(f"✨ Create playlist ({len(night_tracks)} songs)", use_container_width=True,
                       key="relive_go"):
            with st.spinner("Searching Spotify and building your playlist..."):
                try:
                    relive_token = get_active_token()
                    if not relive_token:
                        st.error("Couldn't get a Spotify login. Reconnect in the sidebar.")
                    else:
                        relive_name = night_playlist_name(night["headliner"], night["venue"], night["day"])
                        playlist, relive_report = create_playlist(
                            spotipy.Spotify(auth=relive_token),
                            [{"artist": r.Artist, "song": r.Song, "original": r.Original}
                             for r in night_tracks.itertuples()],
                            relive_name, description="The setlist from a night I was there. Made with Setlistr.")
                        st.session_state["relive_report"] = relive_report
                        if playlist:
                            st.balloons()
                            matched = int((relive_report["Status"] == "✅ Matched").sum())
                            st.success(f"🎉 Created '{relive_name}' with {matched} of {len(relive_report)} songs!")
                            st.markdown(f"### 👉 [Open it in Spotify]({playlist['external_urls']['spotify']})")
                        else:
                            st.error("Couldn't match any of these songs on Spotify. See the report below.")
                except Exception as e:
                    st.error(f"Failed to create playlist: {e}")

        relive_rep = st.session_state.get("relive_report")
        if relive_rep is not None and not relive_rep.empty:
            ok = int((relive_rep["Status"] == "✅ Matched").sum())
            with st.expander(f"📋 Track matching report ({ok}/{len(relive_rep)} matched)"):
                st.dataframe(relive_rep, use_container_width=True, hide_index=True)

    st.divider()

    # 5. Full attendance history log
    st.subheader("Full Attendance History Log")
    st.caption("Individual setlists logged for each performer:")

    df_att_sorted = df_att.sort_values('eventDate_dt', ascending=False)

    display_cols = ['Date', 'artist', 'venue', 'city', 'state', 'tour', 'song_count']
    column_configs = {
        "Date": "Date",
        "artist": st.column_config.TextColumn("Performer"),
        "venue": st.column_config.TextColumn("Venue"),
        "city": st.column_config.TextColumn("City"),
        "state": st.column_config.TextColumn("State"),
        "tour": st.column_config.TextColumn("Tour"),
        "song_count": st.column_config.NumberColumn("Songs"),
    }
    if 'url' in df_att_sorted.columns:
        display_cols.append('url')
        column_configs["url"] = st.column_config.LinkColumn("Setlist Link", display_text="View Setlist 🔗")

    dated_table(df_att_sorted[display_cols], column_config=column_configs,
                 use_container_width=True, hide_index=True)

    st.divider()

    # 6. Venue inspector
    st.markdown("### 🔍 Venue Inspector")
    venue_list = sorted(venue_summary['venue'].unique())
    default_idx = venue_list.index("Madison Square Garden") if "Madison Square Garden" in venue_list else 0

    selected_venue = st.selectbox("Select a venue to view concert history:", venue_list, index=default_idx)

    if selected_venue:
        v_shows = df_concerts[df_concerts['venue'] == selected_venue]

        v_col1, v_col2, v_col3 = st.columns(3)
        v_col1.metric("Concerts at Venue", len(v_shows))
        v_col2.metric("Unique Performers Seen", df_att[df_att['venue'] == selected_venue]['artist'].nunique())
        v_col3.metric("Most Seen Artist Here",
                      df_att[df_att['venue'] == selected_venue]['artist'].mode()[0] if not v_shows.empty else "N/A")

        dated_table(
            v_shows[['Date', 'artist', 'tour', 'song_count']],
            column_config={"Date": "Date", "artist": "Artist(s) Performed",
                           "tour": "Tour", "song_count": "Total Songs"},
            use_container_width=True, hide_index=True,
        )

except FileNotFoundError:
    st.warning("`attended_shows.csv` not found in project directory.")
