"""Stream or cache YouTube videos and launch VLC as soon as playback is possible."""

from __future__ import annotations

import shutil
import subprocess
import threading
from pathlib import Path
from typing import Any

from navigation import youtube_watch_url
from store import VIDEOS_DIR, ensure_dirs, video_cache_path

MIN_VIDEO_BYTES = 32_768
MP4_FTYP = b"ftyp"
MP4_MOOV = b"moov"
MP4_MDAT = b"mdat"

VLC_CANDIDATES = ("vlc", "cvlc", "nvlc", "/usr/bin/vlc", "/usr/local/bin/vlc")

# Prefer a single progressive HTTP MP4 (header + index + frames in one stream).
STREAM_FORMAT = (
    "best*[ext=mp4][acodec!=none][vcodec!=none][protocol^=http]/"
    "best[ext=mp4][protocol^=http]/"
    "best[ext=mp4]/best"
)

_cache_jobs: set[str] = set()
_cache_lock = threading.Lock()


class VideoDownloadError(RuntimeError):
    pass


class MP4PlayabilityError(ValueError):
    pass


def has_mp4_header(data: bytes) -> bool:
    """Return True when the file begins with an ISO-BMFF ftyp box (MP4 header)."""
    if len(data) < 12:
        return False
    if data[4:8] != MP4_FTYP:
        return False
    major_brand = data[8:12]
    return major_brand.isalnum()


def has_mp4_index(data: bytes) -> bool:
    """Return True when the MP4 contains a moov atom (stream index/metadata)."""
    return MP4_MOOV in data


def has_mp4_media_data(data: bytes) -> bool:
    """Return True when the MP4 contains an mdat atom (actual frame bytes)."""
    return MP4_MDAT in data


def verify_playable_mp4(path: Path) -> None:
    """Ensure a cached MP4 has header, index, and media data for VLC playback."""
    if not path.exists():
        raise MP4PlayabilityError(f"missing file: {path}")

    size = path.stat().st_size
    if size < MIN_VIDEO_BYTES:
        raise MP4PlayabilityError(f"file too small for playback ({size} bytes)")

    data = path.read_bytes()
    if not has_mp4_header(data):
        raise MP4PlayabilityError("missing MP4 ftyp header")
    if not has_mp4_index(data):
        raise MP4PlayabilityError("missing moov index atom")
    if not has_mp4_media_data(data):
        raise MP4PlayabilityError("missing mdat media atom (no encoded frames)")

    if shutil.which("ffprobe"):
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=codec_type,codec_name",
                "-of",
                "csv=p=0",
                str(path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0 or "video" not in result.stdout:
            raise MP4PlayabilityError("ffprobe found no video stream")


def find_vlc_executable() -> str | None:
    for candidate in VLC_CANDIDATES:
        path = shutil.which(candidate)
        if path:
            return path
    return None


def _is_stream_url(target: str | Path) -> bool:
    if isinstance(target, Path):
        return False
    return target.startswith(("http://", "https://"))


def launch_vlc(target: str | Path) -> subprocess.Popen:
    """Open VLC on a local file or stream URL."""
    vlc = find_vlc_executable()
    if vlc is None:
        raise VideoDownloadError(
            "VLC was not found on PATH. Install VLC or set VLC_EXECUTABLE."
        )

    if _is_stream_url(target):
        media = target
    else:
        path = Path(target)
        verify_playable_mp4(path)
        media = str(path.resolve())

    return subprocess.Popen(
        [vlc, media],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _yt_dlp():
    try:
        import yt_dlp
    except ImportError as exc:
        raise VideoDownloadError("yt-dlp is not installed; run: pip install yt-dlp") from exc
    return yt_dlp


def extract_youtube_stream(watch_url: str) -> dict[str, str]:
    """Return a direct HTTP URL VLC can stream without waiting for a full download."""
    yt_dlp = _yt_dlp()
    options: dict[str, Any] = {
        "format": STREAM_FORMAT,
        "quiet": True,
        "no_warnings": True,
    }
    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(watch_url, download=False)

    stream_url = info.get("url")
    if not stream_url:
        raise VideoDownloadError("no progressive stream URL available for this video")

    return {
        "url": stream_url,
        "title": info.get("title") or "",
        "ext": info.get("ext") or "mp4",
    }


def _download_options(output_path: Path) -> dict[str, Any]:
    return {
        "format": (
            "bestvideo[ext=mp4][vcodec^=avc1]+bestaudio[ext=m4a]/"
            "bestvideo[ext=mp4]+bestaudio[ext=m4a]/"
            "best[ext=mp4]/best"
        ),
        "merge_output_format": "mp4",
        "outtmpl": str(output_path.with_suffix(".%(ext)s")),
        "postprocessor_args": {"ffmpeg": ["-movflags", "+faststart"]},
        "quiet": True,
        "no_warnings": True,
        "retries": 3,
    }


def download_youtube_video(video_id: str, page_url: str | None = None) -> Path:
    """Download a complete cached copy for offline replay."""
    yt_dlp = _yt_dlp()
    ensure_dirs()
    output_path = video_cache_path(video_id, "mp4")
    watch_url = page_url or youtube_watch_url(video_id)

    if output_path.exists():
        try:
            verify_playable_mp4(output_path)
            return output_path
        except MP4PlayabilityError:
            output_path.unlink(missing_ok=True)

    with yt_dlp.YoutubeDL(_download_options(output_path)) as ydl:
        info = ydl.extract_info(watch_url, download=True)

    downloaded = output_path
    if not downloaded.exists():
        requested = info.get("requested_downloads") or []
        if requested:
            downloaded = Path(requested[-1]["filepath"])
        elif info.get("filepath"):
            downloaded = Path(info["filepath"])
        elif info.get("_filename"):
            downloaded = Path(info["_filename"])

    if not downloaded.exists():
        matches = sorted(VIDEOS_DIR.glob(f"{video_id}.*"))
        if matches:
            downloaded = matches[0]

    if not downloaded.exists():
        raise VideoDownloadError(f"download finished but file is missing for {video_id}")

    if downloaded != output_path:
        if output_path.exists():
            output_path.unlink()
        downloaded.rename(output_path)

    verify_playable_mp4(output_path)
    return output_path


def cache_youtube_video_background(video_id: str, page_url: str | None = None) -> None:
    """Cache the full video in the background while VLC streams it."""
    with _cache_lock:
        if video_id in _cache_jobs:
            return
        _cache_jobs.add(video_id)

    def worker() -> None:
        try:
            download_youtube_video(video_id, page_url)
        except Exception:
            pass
        finally:
            with _cache_lock:
                _cache_jobs.discard(video_id)

    threading.Thread(target=worker, daemon=True).start()


def open_youtube_in_vlc(video_id: str, page_url: str | None = None) -> tuple[subprocess.Popen, str]:
    """Open VLC immediately from cache or stream; cache in the background when streaming."""
    ensure_dirs()
    output_path = video_cache_path(video_id, "mp4")
    watch_url = page_url or youtube_watch_url(video_id)

    if output_path.exists():
        try:
            verify_playable_mp4(output_path)
            return launch_vlc(output_path), "cache"
        except MP4PlayabilityError:
            output_path.unlink(missing_ok=True)

    stream = extract_youtube_stream(watch_url)
    process = launch_vlc(stream["url"])
    cache_youtube_video_background(video_id, page_url)
    return process, "stream"


def ensure_youtube_video(video_id: str, page_url: str | None = None) -> Path:
    output_path = video_cache_path(video_id, "mp4")
    if output_path.exists():
        try:
            verify_playable_mp4(output_path)
            return output_path
        except MP4PlayabilityError:
            output_path.unlink(missing_ok=True)
    return download_youtube_video(video_id, page_url=page_url)
