"""Persistent /tmp storage for the terminal browser."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

TMP_ROOT = Path("/tmp/offline-browser")
CACHE_DIR = TMP_ROOT / "cache"
SIXEL_DIR = TMP_ROOT / "sixel"
ASSETS_DIR = TMP_ROOT / "assets"
DB_FILE = TMP_ROOT / "session.json"


def ensure_dirs() -> None:
    for path in (TMP_ROOT, CACHE_DIR, SIXEL_DIR, ASSETS_DIR):
        path.mkdir(parents=True, exist_ok=True)


def load_db() -> dict[str, Any]:
    ensure_dirs()
    if not DB_FILE.exists():
        return {"history": [], "searches": [], "visits": []}
    try:
        return json.loads(DB_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"history": [], "searches": [], "visits": []}


def save_db(db: dict[str, Any]) -> None:
    ensure_dirs()
    DB_FILE.write_text(json.dumps(db, indent=2), encoding="utf-8")


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


def cache_bundle_path(url: str) -> Path:
    ensure_dirs()
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:20]
    return CACHE_DIR / f"{digest}.json"


def cache_assets_dir(bundle_path: Path) -> Path:
    ensure_dirs()
    return ASSETS_DIR / bundle_path.stem


def sixel_cache_path(image_path: Path, max_width: int, colors: int, profile: str = "konsole") -> Path:
    ensure_dirs()
    digest = hashlib.sha256(
        f"v4:{profile}:{image_path.resolve()}:{image_path.stat().st_mtime}:{max_width}:{colors}".encode()
    ).hexdigest()[:24]
    return SIXEL_DIR / f"{digest}.sixel"
