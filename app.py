"""Setlistr entry point: page config, shared sidebar login, and navigation."""
import streamlit as st

from services.auth import render_spotify_sidebar

st.set_page_config(page_title="Setlistr", page_icon="🎵", layout="wide")

render_spotify_sidebar()

pg = st.navigation([
    st.Page("pages/1_Builder.py", title="Setlistr Builder", icon="🎵", default=True),
    st.Page("pages/2_Passport.py", title="Concert Passport", icon="🎫"),
    st.Page("pages/3_Compare.py", title="Compare with a Friend", icon="🤝"),
    st.Page("pages/4_Wrapped.py", title="Concert Wrapped", icon="🎁"),
])
pg.run()
