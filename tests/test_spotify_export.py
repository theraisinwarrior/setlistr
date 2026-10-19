from services import spotify_export


class FakeSpotify:
    def __init__(self):
        self.added = []

    def current_user_playlist_create(self, name, public, description):
        return {"id": "pl1"}

    def playlist_add_items(self, playlist_id, items):
        self.added.extend(items)


def test_same_track_is_added_once(monkeypatch):
    uris = {"Song": "spotify:track:1", "Song (Reprise)": "spotify:track:1", "Other": "spotify:track:2"}
    monkeypatch.setattr(spotify_export, "search_spotify_track",
                        lambda sp, artist, song, orig: (uris[song], song, "Exact Field Match"))
    sp = FakeSpotify()
    tracks = [{"artist": "X", "song": s} for s in ("Song", "Song (Reprise)", "Other")]
    playlist, report = spotify_export.create_playlist(sp, tracks, "Test")
    assert sp.added == ["spotify:track:1", "spotify:track:2"]
    assert list(report["Status"]) == ["✅ Matched", "🔁 Duplicate", "✅ Matched"]
