"""Credential loading and Spotify auth (owner vs. friend session handling)."""
import hmac

import streamlit as st
from spotipy.oauth2 import SpotifyOAuth

try:  # keeps tokens in memory instead of a shared .cache file on the server
    from spotipy.cache_handler import MemoryCacheHandler
except ImportError:  # very old spotipy
    MemoryCacheHandler = None

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
    kwargs = {"cache_handler": MemoryCacheHandler()} if MemoryCacheHandler else {}
    return SpotifyOAuth(
        client_id=st.secrets.get("SPOTIPY_CLIENT_ID", ""),
        client_secret=st.secrets.get("SPOTIPY_CLIENT_SECRET", ""),
        redirect_uri=REDIRECT_URI,
        scope=SCOPE,
        **kwargs,
    )


def get_authorize_url() -> str:
    return get_oauth().get_authorize_url()


def _is_owner_request() -> bool:
    """True only when the page was opened with ?me=<OWNER_KEY> matching the secret.

    Without this check, every visitor would be auto-connected to the owner's Spotify
    account and could create playlists in it. If OWNER_KEY isn't set, owner
    auto-connect is disabled.
    """
    key = st.secrets.get("OWNER_KEY", "")
    given = st.query_params.get("me", "")
    return bool(key) and bool(given) and hmac.compare_digest(str(key), str(given))


def render_spotify_sidebar() -> None:
    """Friends log in with their own Spotify; the owner auto-connects via a private link."""
    sp_oauth = get_oauth()
    refresh_token = get_refresh_token()

    st.sidebar.header("1. Spotify Account")

    # 1. Returning from Spotify's login page
    if "code" in st.query_params:
        try:
            token_info = sp_oauth.get_access_token(st.query_params["code"])
            st.session_state["spotify_token"] = token_info["access_token"]
            st.session_state["spotify_refresh"] = token_info.get("refresh_token")
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
            for k in ("spotify_token", "spotify_refresh"):
                st.session_state.pop(k, None)
            st.session_state["user_mode"] = None
            st.session_state["owner_opt_out"] = True  # don't instantly re-connect the owner
            st.rerun()

    # 3. Not connected
    else:
        if (refresh_token and _is_owner_request()
                and not st.session_state.get("owner_opt_out")):
            try:
                token_info = sp_oauth.refresh_access_token(refresh_token)
                st.session_state["spotify_token"] = token_info["access_token"]
                st.session_state["user_mode"] = "owner"
                st.rerun()
            except Exception:
                pass

        st.sidebar.info("Connect your Spotify account to save playlists directly to your library.")
        st.sidebar.link_button("🎵 Connect Your Spotify Account", sp_oauth.get_authorize_url(),
                               use_container_width=True)

    st.sidebar.divider()


def is_spotify_connected() -> bool:
    return "spotify_token" in st.session_state


def get_active_token():
    """Return a usable access token for the current session, or None.

    Owner sessions refresh with the owner's stored token; friend sessions refresh with
    their own refresh token (so a tab left open for over an hour keeps working). A
    friend's session can never use the owner's token.
    """
    mode = st.session_state.get("user_mode")

    if mode == "owner":
        owner_refresh = get_refresh_token()
        if owner_refresh:
            try:
                info = get_oauth().refresh_access_token(owner_refresh)
                st.session_state["spotify_token"] = info["access_token"]
                return info["access_token"]
            except Exception:
                pass

    elif mode == "friend":
        friend_refresh = st.session_state.get("spotify_refresh")
        if friend_refresh:
            try:
                info = get_oauth().refresh_access_token(friend_refresh)
                st.session_state["spotify_token"] = info["access_token"]
                if info.get("refresh_token"):
                    st.session_state["spotify_refresh"] = info["refresh_token"]
                return info["access_token"]
            except Exception:
                pass

    return st.session_state.get("spotify_token")
