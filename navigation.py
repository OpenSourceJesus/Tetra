"""URL normalization for the offline browser."""

from __future__ import annotations

import re
import urllib.parse

BROWSER_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

URL_PATTERN = re.compile(
    r"^(https?://|www\.)[^\s]+$",
    re.IGNORECASE,
)


def is_url(text: str) -> bool:
    text = text.strip()
    if not text:
        return False
    if text.startswith(("http://", "https://", "file://")):
        return True
    if URL_PATTERN.match(text):
        return True
    if "." in text and " " not in text and not text.startswith("."):
        return True
    return False


def normalize_url(text: str) -> str:
    text = text.strip()
    if not text:
        raise ValueError("empty URL")
    if is_url(text):
        if text.startswith("www."):
            return "https://" + text
        if "://" not in text:
            return "https://" + text
        return text
    query = urllib.parse.quote_plus(text)
    return f"https://www.google.com/search?q={query}&gbv=1"


def google_search_url(query: str) -> str:
    return f"https://www.google.com/search?q={urllib.parse.quote_plus(query)}&gbv=1"


def youtube_search_url(query: str) -> str:
    return "https://www.youtube.com/results?" + urllib.parse.urlencode({"search_query": query})


def is_google_home(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    host = parsed.netloc.lower().removeprefix("www.")
    if host not in {"google.com", "google.co.uk", "google.ca"}:
        return False
    return parsed.path in {"", "/"} and "q=" not in parsed.query


def is_google_search(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    host = parsed.netloc.lower().removeprefix("www.")
    return host.endswith("google.com") and parsed.path == "/search" and "q=" in parsed.query


def search_query_from_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    return urllib.parse.unquote_plus(urllib.parse.parse_qs(parsed.query).get("q", [""])[0])


def is_youtube_search(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    host = parsed.netloc.lower()
    if "youtube.com" not in host:
        return False
    return parsed.path == "/results" and "search_query" in parsed.query


def youtube_search_query_from_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    return urllib.parse.unquote_plus(
        urllib.parse.parse_qs(parsed.query).get("search_query", [""])[0]
    )


def is_youtube_watch(url: str) -> bool:
    return youtube_video_id_from_url(url) is not None


def youtube_video_id_from_url(url: str) -> str | None:
    parsed = urllib.parse.urlparse(url)
    host = parsed.netloc.lower()
    if "youtube.com" not in host and host not in {"youtu.be", "www.youtu.be"}:
        return None
    if parsed.path == "/watch":
        video_id = urllib.parse.parse_qs(parsed.query).get("v", [""])[0]
        return video_id or None
    if host.endswith("youtu.be") and parsed.path.strip("/"):
        return parsed.path.strip("/").split("/")[0] or None
    return None


def youtube_watch_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


def prepare_fetch_url(url: str) -> str:
    """Adjust known sites for HTML-friendly variants."""
    if is_google_home(url):
        parsed = urllib.parse.urlparse(url)
        params = urllib.parse.parse_qs(parsed.query)
        params["gbv"] = ["1"]
        query = urllib.parse.urlencode(params, doseq=True)
        return urllib.parse.urlunparse(parsed._replace(query=query))
    if is_google_search(url):
        parsed = urllib.parse.urlparse(url)
        params = urllib.parse.parse_qs(parsed.query)
        params["gbv"] = ["1"]
        query = urllib.parse.urlencode(params, doseq=True)
        return urllib.parse.urlunparse(parsed._replace(query=query))
    return url
