"""services/github_store.py with GitHub faked out."""
import base64

import pytest

import services.github_store as gs


class _Resp:
    def __init__(self, status, data=None):
        self.status_code, self._data, self.ok = status, data or {}, status < 400

    def json(self):
        return self._data


def test_read_missing_file_is_empty(monkeypatch):
    monkeypatch.setattr(gs.requests, "get", lambda *a, **k: _Resp(404))
    assert gs.read_file("me/repo", "watchlist.csv", "t") == ("", None)


def test_read_and_write(monkeypatch):
    content = base64.b64encode(b"artist\nBig Thief\n").decode()
    monkeypatch.setattr(gs.requests, "get", lambda *a, **k: _Resp(200, {"content": content, "sha": "s1"}))
    assert gs.read_file("me/repo", "watchlist.csv", "t") == ("artist\nBig Thief\n", "s1")
    sent = {}
    monkeypatch.setattr(gs.requests, "put",
                        lambda url, json, **k: sent.update(json) or _Resp(200, {"content": {"sha": "s2"}}))
    assert gs.write_file("me/repo", "watchlist.csv", "t", "artist\n", "s1", "msg") == "s2"
    assert sent["sha"] == "s1" and base64.b64decode(sent["content"]) == b"artist\n"


def test_bad_token_gives_a_readable_error(monkeypatch):
    monkeypatch.setattr(gs.requests, "put", lambda *a, **k: _Resp(401))
    with pytest.raises(gs.GitHubStoreError, match="GITHUB_TOKEN"):
        gs.write_file("me/repo", "watchlist.csv", "t", "x", None, "msg")
