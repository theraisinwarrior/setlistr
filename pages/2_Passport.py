"""Concert Passport: personal attendance dashboard."""
from datetime import datetime

import pandas as pd
import plotly.express as px
import streamlit as st

from data.attendance import apply_venue_overrides, extract_covers, process_attendance
from analytics.deep_cuts import global_rare_songs, scan_plan, song_frequency
from analytics.passport_stats import compute_highlights, venue_top_performers
from data.store import (clear_sync_cache, get_artist_year_setlists, load_csv_attendance,
                        load_venue_overrides, sync_attended_shows)
from services.auth import get_setlist_api_key
from services.setlistfm import SetlistFmError

SPOTIFY_GREEN = "#1DB954"

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
    st.plotly_chart(fig_map, use_container_width=True)

    if venues_needing_coords is not None and not venues_needing_coords.empty:
        with st.expander(f"📍 {len(venues_needing_coords)} venue(s) need exact map coordinates"):
            st.write("These venues have no saved coordinates, so setlist.fm's city-level "
                     "location is used and they may stack on top of each other. To fix one, add a row "
                     "(`venue,city,lat,long`) to `venue_coordinates.csv` in your GitHub repo.")
            st.dataframe(venues_needing_coords, use_container_width=True, hide_index=True)

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
            st.caption("Every song you've heard live, ranked by how rarely that artist played it in the "
                       "year you saw them (judged from up to 20 of their shows that year).")

            scope = st.selectbox("Concerts to scan", ["Last 2 years", "Last 5 years", "All time"])
            this_year = datetime.now().year
            min_year = {"Last 2 years": this_year - 1, "Last 5 years": this_year - 4,
                        "All time": None}[scope]
            scope_att = df_att if min_year is None else df_att[df_att['year'] >= min_year]
            plan = scan_plan(scope_att)

            if not api_key_for_sync:
                st.warning("Add a Setlist.fm API key to find rare songs.")
            elif not plan:
                st.info("Nothing to scan in that range. This needs the live setlist.fm sync.")
            else:
                st.caption(f"{len(plan)} artist-years to check, about "
                           f"{max(1, round(len(plan) * 0.9 / 60))} min the first time. "
                           "Results are remembered for a week, so repeat scans are fast.")

                if st.button("🔍 Find my rarest songs", use_container_width=True):
                    samples, hit_limit = {}, False
                    progress = st.progress(0.0, text="Starting...")
                    for i, (artist, mbid, year) in enumerate(plan):
                        progress.progress(i / len(plan), text=f"Checking {artist} ({year}): {i + 1} of {len(plan)}")
                        try:
                            setlists = get_artist_year_setlists(mbid, year, api_key_for_sync)
                        except SetlistFmError:
                            hit_limit = True
                            break
                        samples[(mbid, year)] = song_frequency(setlists)
                    progress.empty()
                    table, stats = global_rare_songs(scope_att, samples)
                    st.session_state["rare_result"] = {"table": table, "stats": stats,
                                                       "hit_limit": hit_limit}

                res = st.session_state.get("rare_result")
                if res:
                    table, stats = res["table"], res["stats"]
                    if res["hit_limit"]:
                        st.warning("setlist.fm's request limit was hit, so this list is partial. "
                                   "Click the button again in a bit; everything already checked is remembered.")
                    if table.empty:
                        st.info("No songs could be scored. setlist.fm may not have enough setlists for these artists.")
                    else:
                        max_pct = st.slider("Show songs played in at most this % of that year's shows",
                                            5, 50, 15, step=5)
                        shown = table[table['pct'] <= max_pct]
                        top = table.iloc[0]
                        st.metric("Rarest song you've heard", top['Song'],
                                  f"{top['Artist']} ({top['Played In']})", delta_color="off")
                        st.success(f"{len(shown)} rare songs found across {stats['scored_shows']} concerts.")
                        st.dataframe(shown[['Song', 'Artist', 'Heard On', 'Played In', 'Frequency']].head(300),
                                     use_container_width=True, hide_index=True, height=300)
                        if stats['skipped_shows']:
                            st.caption(f"{stats['skipped_shows']} concert(s) were skipped: setlist.fm had "
                                       "fewer than 8 setlists for that artist that year, or they couldn't be checked.")

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
        st.dataframe(df_covers.drop(columns='eventDate_dt'), use_container_width=True,
                     hide_index=True, height=300)

    st.divider()

    # 5. Full attendance history log
    st.subheader("Full Attendance History Log")
    st.caption("Individual setlists logged for each performer:")

    df_att_sorted = df_att.sort_values('eventDate_dt', ascending=False)

    display_cols = ['Date', 'artist', 'venue', 'city', 'state', 'tour', 'song_count']
    column_configs = {
        "Date": st.column_config.TextColumn("Date"),
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

    st.dataframe(df_att_sorted[display_cols], column_config=column_configs,
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

        st.dataframe(
            v_shows[['Date', 'artist', 'tour', 'song_count']],
            column_config={"Date": "Date", "artist": "Artist(s) Performed",
                           "tour": "Tour", "song_count": "Total Songs"},
            use_container_width=True, hide_index=True,
        )

except FileNotFoundError:
    st.warning("`attended_shows.csv` not found in project directory.")
