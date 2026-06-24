"""Central paths for generated browser data (all under /tmp)."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

TMP_ROOT = Path("/tmp/offline-browser")
CACHE_DIR = TMP_ROOT / "cache"
BUNDLES_DIR = TMP_ROOT / "bundles"
ASSETS_DIR = TMP_ROOT / "assets"
SIXEL_DIR = TMP_ROOT / "sixel"
VIDEOS_DIR = TMP_ROOT / "videos"
TEST_UPLOADS_DIR = TMP_ROOT / "testserver" / "uploads"
HISTORY_FILE = TMP_ROOT / "history.json"
BOOKMARKS_FILE = TMP_ROOT / "bookmarks.json"
SESSION_FILE = TMP_ROOT / "session.json"


def ensure_dirs() -> None:
    for path in (
        TMP_ROOT,
        CACHE_DIR,
        BUNDLES_DIR,
        ASSETS_DIR,
        SIXEL_DIR,
        VIDEOS_DIR,
        TEST_UPLOADS_DIR,
    ):
        path.mkdir(parents=True, exist_ok=True)


def default_bundle_path() -> Path:
    ensure_dirs()
    return BUNDLES_DIR / "DOM.json"


def bundle_path(name: str) -> Path:
    ensure_dirs()
    return BUNDLES_DIR / name


def cache_bundle_path(url: str) -> Path:
    ensure_dirs()
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:20]
    return CACHE_DIR / f"{digest}.json"


def bundle_assets_dir(bundle_path: Path) -> Path:
    ensure_dirs()
    return bundle_path.parent / f"{bundle_path.stem}_assets"


def sixel_cache_path(image_path: Path, max_width: int, colors: int, profile: str = "konsole") -> Path:
    ensure_dirs()
    digest = hashlib.sha256(
        f"v4:{profile}:{image_path.resolve()}:{image_path.stat().st_mtime}:{max_width}:{colors}".encode()
    ).hexdigest()[:24]
    return SIXEL_DIR / f"{digest}.sixel"


def video_cache_path(video_id: str, ext: str = "mp4") -> Path:
    ensure_dirs()
    safe_id = re.sub(r"[^A-Za-z0-9_-]", "", video_id)
    return VIDEOS_DIR / f"{safe_id}.{ext}"
