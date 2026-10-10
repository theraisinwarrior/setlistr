"""Concert Passport: personal attendance dashboard."""
import pandas as pd
import plotly.express as px
import streamlit as st

from data.attendance import process_attendance
from data.store import clear_sync_cache, load_csv_attendance, sync_attended_shows
from services.auth import get_setlist_api_key
from services.setlistfm import SetlistFmError, get_global_artist_stats

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
if username.strip() and api_key_for_sync:
    try:
        with st.spinner(f"Syncing attended shows for {username.strip()} from setlist.fm "
                        "(the first load can take a bit if you have a lot of shows)..."):
            raw_attendance = sync_attended_shows(username.strip(), api_key_for_sync)
        if raw_attendance.empty:
            st.info(f"No attended shows found for '{username.strip()}'. "
                    "Mark shows as attended on setlist.fm and refresh.")
            st.stop()
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
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Concerts", len(df_concerts))
    col2.metric("Unique Artists", df_att['artist'].nunique())
    col3.metric("Venues Visited", df_concerts['venue'].nunique())
    col4.metric("Cities Visited", df_concerts['city'].nunique())

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
        st.subheader("Artists Seen > 1 Time")
        st.caption("📜 Scroll to explore every artist seen multiple times:")

        artist_counts = df_att['artist'].value_counts().reset_index()
        artist_counts.columns = ['artist', 'count']
        multi_artists = artist_counts[artist_counts['count'] >= 2].copy()

        multi_artists['rank_dense'] = multi_artists['count'].rank(method='min', ascending=False).astype(int)
        rank_counts = multi_artists['rank_dense'].value_counts()

        def format_rank_artist(row):
            r = row['rank_dense']
            prefix = f"T-{r}." if rank_counts[r] > 1 else f"{r}."
            return f"{prefix} {row['artist']}"

        multi_artists['ranked_label'] = multi_artists.apply(format_rank_artist, axis=1)

        with st.container(height=380):
            fig_artists = px.bar(multi_artists, x='count', y='ranked_label', orientation='h',
                                 text='count', color_discrete_sequence=[SPOTIFY_GREEN])
            fig_artists.update_layout(
                yaxis=dict(autorange="reversed", automargin=True),
                xaxis_title="Times Seen", yaxis_title="",
                height=max(360, len(multi_artists) * 28),
                margin=dict(l=0, r=10, t=10, b=10),
            )
            fig_artists.update_traces(textposition='inside', texttemplate='%{text}',
                                      insidetextanchor='end')
            st.plotly_chart(fig_artists, use_container_width=True)

    st.divider()

    # 3. Geographic footprint map
    st.subheader("Geographic Footprint")
    st.caption("💡 Hover over or click any green pin to view venue stats!")

    map_data = df_concerts.dropna(subset=['lat', 'long']).copy()

    def agg_venue(g):
        top_3 = ", ".join(g['artist'].value_counts().head(3).index)
        return pd.Series({
            'City': g['city'].iloc[0],
            'State': g['state'].iloc[0],
            'Concerts Attended': len(g),
            'Top Performers': top_3,
        })

    venue_summary = map_data.groupby('venue').apply(agg_venue).reset_index()
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
                       "Concerts Attended": True, "Top Performers": True},
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

    st.divider()

    # 4. Song analytics
    if not df_songs.empty:
        st.subheader("🎵 Song Analytics")
        s_col1, s_col2 = st.columns(2)

        with s_col1:
            st.markdown("### Most Heard Tracks Live")
            top_tracks = (df_songs.groupby(['song', 'artist', 'track_artist']).size()
                          .reset_index(name='Times Heard')
                          .sort_values('Times Heard', ascending=False))
            fig_top_songs = px.bar(top_tracks.head(15), x='Times Heard', y='track_artist',
                                   orientation='h', text='Times Heard',
                                   color_discrete_sequence=[SPOTIFY_GREEN])
            fig_top_songs.update_layout(yaxis=dict(autorange="reversed"),
                                        xaxis_title="Times Heard Live", yaxis_title="", height=450)
            st.plotly_chart(fig_top_songs, use_container_width=True)

        with s_col2:
            st.markdown("### Deep Cuts Index (Global Career Rarity <25%)")
            st.caption("Tracks played in **less than 25%** of the artist's total career concerts worldwide on Setlist.fm:")

            artist_list = sorted(df_att['artist'].value_counts().index.tolist())
            selected_deep_artist = st.selectbox("Select artist to analyze global career rarity:", artist_list)

            if selected_deep_artist:
                user_artist_songs = df_songs[df_songs['artist'] == selected_deep_artist]['song'].unique().tolist()

                api_key = st.secrets.get("SETLIST_API_KEY", "")
                total_career_shows, global_stats = get_global_artist_stats(selected_deep_artist, api_key)

                deep_cut_rows = []

                if global_stats and total_career_shows:
                    unknown_count = 0
                    for s_name in user_artist_songs:
                        s_info = global_stats.get(s_name.lower())
                        if not s_info:
                            # FIX vs v1: songs missing from the scrape were silently treated
                            # as 2% "rare" tracks. They are now excluded and counted instead.
                            unknown_count += 1
                            continue
                        if s_info['global_pct'] < 25.0:
                            deep_cut_rows.append({
                                "Track Title": s_name,
                                "Artist": selected_deep_artist,
                                "Global Play Count": s_info['global_count'],
                                "Total Career Shows": total_career_shows,
                                "Global Play Frequency": f"{s_info['global_pct']:.1f}%",
                            })

                    deep_cuts_table = pd.DataFrame(deep_cut_rows)

                    if not deep_cuts_table.empty:
                        deep_cuts_table = deep_cuts_table.sort_values("Global Play Count")
                        st.success(f"Found {len(deep_cuts_table)} rare tracks (<25% global frequency) across {total_career_shows} total career concerts by **{selected_deep_artist}**!")
                        st.dataframe(
                            deep_cuts_table,
                            column_config={"Global Play Frequency": "Global Play Frequency (%)"},
                            use_container_width=True, hide_index=True, height=300,
                        )
                    else:
                        st.info(f"All tracks with known stats for **{selected_deep_artist}** are staple tour songs played in >25% of their global concerts!")

                    if unknown_count:
                        st.caption(f"ℹ️ {unknown_count} track(s) weren't found in Setlist.fm's stats and were left out.")
                else:
                    local_artist_shows = df_att[df_att['artist'] == selected_deep_artist]['eventDate_dt'].nunique()
                    local_counts = df_songs[df_songs['artist'] == selected_deep_artist]['song'].value_counts()

                    for s_name, count in local_counts.items():
                        l_pct = (count / local_artist_shows) * 100.0
                        if l_pct < 25.0:
                            deep_cut_rows.append({
                                "Track Title": s_name,
                                "Artist": selected_deep_artist,
                                "Times Heard": count,
                                "Attended Shows": local_artist_shows,
                                "Personal Frequency": f"{l_pct:.1f}%",
                            })

                    fallback_table = pd.DataFrame(deep_cut_rows)
                    if not fallback_table.empty:
                        st.dataframe(fallback_table, use_container_width=True,
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
