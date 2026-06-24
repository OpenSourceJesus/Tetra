"""Persistent /tmp storage for the terminal browser."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from store import (
    SESSION_FILE,
    cache_bundle_path,
    ensure_dirs,
    sixel_cache_path,
)

__all__ = [
    "SESSION_FILE",
    "cache_bundle_path",
    "ensure_dirs",
    "load_db",
    "record_search",
    "record_visit",
    "save_db",
    "sixel_cache_path",
]


def load_db() -> dict[str, Any]:
    ensure_dirs()
    if not SESSION_FILE.exists():
        return {"history": [], "searches": [], "visits": []}
    try:
        return json.loads(SESSION_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"history": [], "searches": [], "visits": []}


def save_db(db: dict[str, Any]) -> None:
    ensure_dirs()
    SESSION_FILE.write_text(json.dumps(db, indent=2), encoding="utf-8")


def record_visit(source: str, bundle_path: Path, viewer: str = "tui") -> None:
    db = load_db()
    now = time.time()
    entry = {
        "source": source,
        "json": str(bundle_path),
        "viewer": viewer,
        "time": now,
        "iso": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(now)),
    }
    history = [item for item in db.get("history", []) if item.get("source") != source]
    history.insert(0, entry)
    db["history"] = history[:100]

    visits = db.get("visits", [])
    visits.append(entry)
    db["visits"] = visits[-500:]
    save_db(db)


def record_search(query: str, result_url: str) -> None:
    db = load_db()
    now = time.time()
    entry = {
        "query": query,
        "url": result_url,
        "time": now,
        "iso": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(now)),
    }
    searches = [item for item in db.get("searches", []) if item.get("query") != query]
    searches.insert(0, entry)
    db["searches"] = searches[:200]
    save_db(db)
