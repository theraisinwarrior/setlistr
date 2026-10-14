"""Saved results for the slow scans (rarest songs, artist popularity).

A live scan can take a few minutes, so the app can show a saved copy instantly. After a
live scan, the page offers a "Save as snapshot" download; put that file in the
`snapshots/` folder of the repo and it becomes what the page shows by default.
Clicking the scan button still runs a fresh live scan. Pure Python, no Streamlit.
"""
import json
import os
from datetime import datetime

import pandas as pd

SNAPSHOT_DIR = "snapshots"
FILES = {"rare_songs": "rare_songs.json", "artist_popularity": "artist_popularity.json"}


def snapshot_bytes(kind: str, table: pd.DataFrame, now=None, **extra) -> bytes:
    """Serialize a result table (plus small extras like stats) to JSON bytes for download."""
    payload = {
        "kind": kind,
        "created": (now or datetime.now()).strftime("%Y-%m-%d"),
        "rows": json.loads(table.to_json(orient="records")),
        **extra,
    }
    return json.dumps(payload, indent=1).encode("utf-8")


def parse_snapshot(raw: bytes, kind: str, columns=None):
    """Turn snapshot bytes back into {'table': DataFrame, 'created': str, ...}. None if invalid."""
    try:
        payload = json.loads(raw)
    except (ValueError, TypeError):
        return None
    if not isinstance(payload, dict) or payload.get("kind") != kind:
        return None
    table = pd.DataFrame(payload.get("rows") or [], columns=columns)
    out = {k: v for k, v in payload.items() if k not in ("rows", "kind")}
    out["table"] = table
    return out


def load_snapshot(kind: str, columns=None, folder: str = SNAPSHOT_DIR):
    """Read snapshots/<kind>.json if it exists. Returns None when missing or unreadable."""
    path = os.path.join(folder, FILES[kind])
    try:
        with open(path, "rb") as f:
            return parse_snapshot(f.read(), kind, columns)
    except OSError:
        return None


def friendly_date(created: str) -> str:
    try:
        return datetime.strptime(created, "%Y-%m-%d").strftime("%b %d, %Y")
    except (TypeError, ValueError):
        return str(created or "an earlier date")
