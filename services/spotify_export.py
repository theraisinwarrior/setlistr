"""Create a Spotify playlist from a list of (artist, song) tracks. No Streamlit imports."""
import pandas as pd

from services.spotify_match import search_spotify_track


def create_playlist(sp, tracks, name: str, description: str = ""):
    """Match each track on Spotify and build a playlist in the given order.

    tracks: list of dicts with keys artist, song and optionally original (cover's original artist).
    Returns (playlist dict or None if nothing matched, match report DataFrame).
    """
    uris, report = [], []
    for t in tracks:
        original = t.get("original") or "Official Release"
        uri, details, method = search_spotify_track(sp, t["artist"], t["song"], original)
        if uri:
            uris.append(uri)
        report.append({
            "Setlist.fm Song": t["song"],
            "Artist": t["artist"],
            "Status": "✅ Matched" if uri else "❌ Missed",
            "Matched Spotify Track": details,
            "Match Method": method,
        })
    report_df = pd.DataFrame(report)
    if not uris:
        return None, report_df

    playlist = sp.current_user_playlist_create(name=name[:100], public=True, description=description[:300])
    for i in range(0, len(uris), 100):
        sp.playlist_add_items(playlist_id=playlist["id"], items=uris[i:i + 100])
    return playlist, report_df
