from services.spotify_match import is_artist_match, is_reasonable_match


def test_artist_match_ignores_punctuation_and_case():
    assert is_artist_match("P!nk", [{"name": "Pnk"}])
    assert is_artist_match("taylor swift", [{"name": "Taylor Swift"}])


def test_artist_match_rejects_other_artist():
    assert not is_artist_match("Taylor Swift", [{"name": "Kanye West"}])


def test_reasonable_match_substring():
    assert is_reasonable_match("Love Story", "Love Story (Taylor's Version)")


def test_reasonable_match_word_overlap():
    assert is_reasonable_match("Dancing in the Dark", "Dancing In The Dark - Remastered")


def test_reasonable_match_rejects_unrelated():
    assert not is_reasonable_match("Anti-Hero", "Shake It Off")


def test_non_latin_names_only_match_themselves():
    assert not is_artist_match("シートベルツ", [{"name": "Taylor Swift"}])
    assert is_artist_match("シートベルツ", [{"name": "シートベルツ"}])
    assert not is_reasonable_match("夜に駆ける", "Shake It Off")
    assert is_reasonable_match("夜に駆ける", "夜に駆ける")


def test_accents_are_ignored():
    assert is_artist_match("Beyoncé", [{"name": "Beyonce"}])
    assert is_artist_match("Sigur Ros", [{"name": "Sigur Rós"}])


def test_empty_names_never_match():
    assert not is_artist_match("!!!", [{"name": "Taylor Swift"}])
    assert not is_artist_match("Taylor Swift", [{"name": ""}])
    assert not is_reasonable_match("", "Shake It Off")
