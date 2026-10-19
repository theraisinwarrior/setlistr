from analytics.setlist_stats import build_song_table


def _show(date, songs):
    return {"eventDate": date, "url": f"https://example.com/{date}",
            "sets": {"set": [{"song": [{"name": s} for s in songs]}]}}


def test_repeated_song_counts_once_per_show():
    shows = [_show("02-10-2026", ["A", "B", "A"]), _show("01-10-2026", ["A"])]
    df = build_song_table(shows, hide_tape=True, hide_covers=False, min_freq=0,
                          max_days_since_played=0, max_playlist_songs=0)
    row = df.set_index("Song Title").loc["A"]
    assert row["Plays"] == 2
    assert row["Frequency"] == "100.0%"
