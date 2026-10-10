"""Credential loading and Spotify auth (owner vs. friend session handling)."""
import streamlit as st
from spotipy.oauth2 import SpotifyOAuth

REDIRECT_URI = "https://setlistr.streamlit.app/"
SCOPE = "playlist-modify-public playlist-modify-private"


def get_setlist_api_key() -> str:
    """Setlist.fm key from secrets, falling back to a sidebar input."""
    key = st.secrets.get("SETLIST_API_KEY", "")
    if not key:
        key = st.sidebar.text_input("Setlist.fm API Key", type="password")
    return key


def get_refresh_token() -> str:
    return st.secrets.get("SPOTIFY_REFRESH_TOKEN", "")


def get_oauth() -> SpotifyOAuth:
    return SpotifyOAuth(
        client_id=st.secrets.get("SPOTIPY_CLIENT_ID", ""),
        client_secret=st.secrets.get("SPOTIPY_CLIENT_SECRET", ""),
        redirect_uri=REDIRECT_URI,
        scope=SCOPE,
    )


def render_spotify_sidebar() -> None:
    """Hybrid login: owner auto-connects via refresh token, friends use OAuth."""
    sp_oauth = get_oauth()
    refresh_token = get_refresh_token()

    st.sidebar.header("1. Spotify Account")

    # 1. Returning from manual OAuth redirect
    if "code" in st.query_params:
        try:
            token_info = sp_oauth.get_access_token(st.query_params["code"])
            st.session_state["spotify_token"] = token_info["access_token"]
            st.session_state["user_mode"] = "friend"
            st.query_params.clear()
            st.rerun()
        except Exception as e:
            st.sidebar.error(f"Spotify Login Error: {e}")

    # 2. Already connected
    if "spotify_token" in st.session_state:
        if st.session_state.get("user_mode") == "owner":
            st.sidebar.success("✅ Auto-Connected (Your Account)")
        else:
            st.sidebar.success("✅ Connected to Spotify!")

        if st.sidebar.button("Log Out / Switch Account"):
            del st.session_state["spotify_token"]
            st.session_state["user_mode"] = None
            st.rerun()

    # 3. Not connected: auto-connect owner, otherwise offer login
    else:
        if refresh_token:
            try:
                token_info = sp_oauth.refresh_access_token(refresh_token)
                st.session_state["spotify_token"] = token_info["access_token"]
                st.session_state["user_mode"] = "owner"
                st.rerun()
            except Exception:
                pass

        st.sidebar.info("Connect your Spotify account to save playlists directly to your library.")
        st.sidebar.link_button(
            "🎵 Connect Your Spotify Account",
            sp_oauth.get_authorize_url(),
            use_container_width=True,
        )

    st.sidebar.divider()


def is_spotify_connected() -> bool:
    return "spotify_token" in st.session_state or bool(get_refresh_token())


def get_active_token():
    """Return a usable access token for the current session, or None.

    FIX vs v1: the owner's refresh token is only used when the session is in
    "owner" mode, so a friend who logged in via OAuth can no longer have
    playlists created in the owner's account.
    """
    if st.session_state.get("user_mode") == "owner":
        refresh_token = get_refresh_token()
        if refresh_token:
            try:
                info = get_oauth().refresh_access_token(refresh_token)
                st.session_state["spotify_token"] = info["access_token"]
                return info["access_token"]
            except Exception:
                pass
    return st.session_state.get("spotify_token")
