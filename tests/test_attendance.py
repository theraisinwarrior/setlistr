import json

from data.attendance import process_attendance, setlists_to_dataframe

FAKE = [
    {
        "eventDate": "15-03-2024",
        "artist": {"name": "Artist A"},
        "venue": {"name": "Madison Square Garden",
                  "city": {"name": "New York", "stateCode": "NY",
                           "coords": {"lat": 40.75, "long": -73.99},
                           "country": {"code": "US"}}},
        "tour": {"name": "Big Tour"},
        "url": "https://www.setlist.fm/a",
        "sets": {"set": [{"song": [{"name": "Song 1"}, {"name": "Intro", "tape": True}]},
                         {"encore": 1, "song": [{"name": "Song 2"}]}]},
    },
    {   # same night and venue, a different act, with no tour and no coordinates
        "eventDate": "15-03-2024",
        "artist": {"name": "Artist B"},
        "venue": {"name": "Madison Square Garden",
                  "city": {"name": "New York", "stateCode": "NY",
                           "coords": {"lat": 40.75, "long": -73.99},
                           "country": {"code": "US"}}},
        "url": "https://www.setlist.fm/b",
        "sets": {"set": [{"song": [{"name": "Opener Song"}]}]},
    },
    {   # sparse record: no coords, no tour, no sets
        "eventDate": "01-07-2023",
        "artist": {"name": "Artist C"},
        "venue": {"name": "Small Club", "city": {"name": "Berlin", "country": {"code": "DE"}}},
        "url": "https://www.setlist.fm/c",
    },
]


def test_conversion_columns_and_values():
    df = setlists_to_dataframe(FAKE)
    assert len(df) == 3
    first = df.iloc[0]
    assert first["eventDate"] == "2024-03-15"
    assert first["state"] == "NY"
    assert first["song_count"] == 2  # tape playback excluded
    assert json.loads(first["songs"]) == ["Song 1", "Song 2"]
    assert df.iloc[2]["state"] == "DE"  # falls back to country code


def test_process_merges_same_night_and_keeps_sparse_shows():
    df_att, df_concerts, df_songs = process_attendance(setlists_to_dataframe(FAKE))
    assert len(df_att) == 3
    assert len(df_concerts) == 2  # A + B merge into one concert; C kept despite no coords
    merged = df_concerts[df_concerts["venue"] == "Madison Square Garden"].iloc[0]
    assert merged["artist"] == "Artist A, Artist B"
    assert set(df_songs["song"]) == {"Song 1", "Song 2", "Opener Song"}


def test_empty_input():
    df = setlists_to_dataframe([])
    assert df.empty
    df_att, df_concerts, df_songs = process_attendance(df)
    assert df_concerts.empty and df_songs.empty


def test_venue_overrides_replace_city_level_coords():
    import pandas as pd
    from data.attendance import apply_venue_overrides

    df = setlists_to_dataframe(FAKE)
    overrides = pd.DataFrame([
        {"venue": "madison square  garden", "city": "New York", "lat": 40.7505, "long": -73.9934},
    ])
    out, missing = apply_venue_overrides(df, overrides)
    msg = out[out["venue"] == "Madison Square Garden"]
    assert (msg["lat"] == 40.7505).all() and (msg["long"] == -73.9934).all()
    assert list(missing["venue"]) == ["Small Club"]  # no override, so flagged
    assert apply_venue_overrides(df.iloc[0:0], overrides)[1].empty
