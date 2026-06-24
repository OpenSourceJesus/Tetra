"""Search result fetching and synthetic DOM construction."""

from __future__ import annotations

import base64
import html
import re
import urllib.parse
import urllib.request

from html_parse import flatten_text, iter_nodes, parse_html
from navigation import BROWSER_UA, search_query_from_url, youtube_search_query_from_url

RESULT_LINK_STYLE = "color: #1a0dab; font-size: 18px; text-decoration: none;"
SNIPPET_STYLE = "color: #4d5156; margin: 2px 0 16px 0;"
CHANNEL_STYLE = "color: #606060; margin: 0 0 4px 0;"
YOUTUBE_WATCH_PREFIX = "https://www.youtube.com/watch?v="


def decode_bing_redirect(url: str) -> str:
    match = re.search(r"[?&]u=([^&]+)", url)
    if not match:
        return url
    encoded = match.group(1)
    if encoded.startswith("a1"):
        encoded = encoded[2:]
    padding = "=" * (-len(encoded) % 4)
    try:
        return base64.b64decode(encoded + padding).decode("utf-8", errors="replace")
    except Exception:
        return url


def fetch_bing_results(query: str, limit: int = 10) -> list[dict[str, str]]:
    if not query.strip():
        return []

    search_url = "https://www.bing.com/search?" + urllib.parse.urlencode({"q": query})
    request = urllib.request.Request(search_url, headers={"User-Agent": BROWSER_UA})
    with urllib.request.urlopen(request, timeout=30) as response:
        html = response.read().decode("utf-8", errors="replace")

    document = parse_html(html)
    results: list[dict[str, str]] = []

    for node in iter_nodes(document):
        if node.get("type") != "li":
            continue
        if "b_algo" not in node.get("attributes", {}).get("class", ""):
            continue

        title = ""
        href = ""
        snippet = ""
        for child in node.get("children", []):
            if child.get("type") == "h2":
                anchor = next(
                    (item for item in child.get("children", []) if item.get("type") == "a"),
                    None,
                )
                if anchor is not None:
                    title = flatten_text(anchor).strip()
                    href = decode_bing_redirect(anchor.get("attributes", {}).get("href", ""))
            if child.get("type") == "div" and "b_caption" in child.get("attributes", {}).get("class", ""):
                snippet = flatten_text(child).strip()

        if title and href:
            results.append({"title": title, "url": href, "snippet": snippet})
        if len(results) >= limit:
            break

    return results


def google_html_has_results(html: str) -> bool:
    lowered = html.lower()
    if "enablejs" in lowered[:4000]:
        return False
    return bool(re.search(r"<h3\b", html)) or 'class="g"' in html


def build_search_results_dom(query: str, results: list[dict[str, str]]) -> dict:
    children: list[dict] = [
        {
            "type": "p",
            "attributes": {},
            "children": [],
            "text": f"Results for: {query}",
            "html": f"Results for: <b>{html.escape(query)}</b>",
        }
    ]

    if not results:
        children.append(
            {
                "type": "p",
                "attributes": {},
                "children": [],
                "text": "No results found.",
                "html": "No results found.",
            }
        )
        return {"type": "div", "attributes": {"class": "search-results"}, "children": children}

    for result in results:
        title = result["title"]
        url = result["url"]
        snippet = result.get("snippet", "")
        children.append(
            {
                "type": "h3",
                "attributes": {},
                "children": [],
                "text": title,
                "html": f'<a href="{url}" style="{RESULT_LINK_STYLE}">{title}</a>',
            }
        )
        if snippet:
            children.append(
                {
                    "type": "p",
                    "attributes": {},
                    "children": [],
                    "text": snippet,
                    "html": f'<span style="{SNIPPET_STYLE}">{snippet}</span>',
                }
            )
        children.append(
            {
                "type": "p",
                "attributes": {},
                "children": [],
                "text": url,
                "html": f'<a href="{url}" style="color:#006621;font-size:12px;">{url}</a>',
            }
        )

    return {"type": "div", "attributes": {"class": "search-results"}, "children": children}


def build_google_search_dom(source_url: str, html: str) -> dict | None:
    if google_html_has_results(html):
        return None
    query = search_query_from_url(source_url)
    results = fetch_bing_results(query)
    return build_search_results_dom(query, results)


def extract_json_after(marker: str, text: str) -> str | None:
    index = text.find(marker)
    if index == -1:
        return None
    start = text.find("{", index)
    if start == -1:
        return None

    depth = 0
    in_string = False
    escaped = False
    for offset, char in enumerate(text[start:], start=start):
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : offset + 1]
    return None


def parse_youtube_search_videos(html: str, limit: int = 15) -> list[dict[str, str]]:
    import json

    raw = extract_json_after("var ytInitialData = ", html)
    if not raw:
        return []

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []

    videos: list[dict[str, str]] = []
    seen: set[str] = set()

    def walk(node) -> None:
        if len(videos) >= limit:
            return
        if isinstance(node, dict):
            renderer = node.get("videoRenderer")
            if renderer:
                video_id = renderer.get("videoId", "")
                if video_id and video_id not in seen:
                    title = _youtube_text(renderer.get("title"))
                    if title:
                        seen.add(video_id)
                        thumbs = renderer.get("thumbnail", {}).get("thumbnails") or []
                        videos.append(
                            {
                                "title": title,
                                "video_id": video_id,
                                "channel": _youtube_text(renderer.get("ownerText")),
                                "snippet": _youtube_text(renderer.get("descriptionSnippet")),
                                "thumbnail": thumbs[-1].get("url", "") if thumbs else "",
                                "url": f"{YOUTUBE_WATCH_PREFIX}{video_id}",
                            }
                        )
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(data)
    return videos


def _youtube_text(field) -> str:
    if not isinstance(field, dict):
        return ""
    runs = field.get("runs") or []
    if not runs:
        return field.get("simpleText", "")
    return "".join(part.get("text", "") for part in runs).strip()


def fetch_bing_youtube_results(query: str, limit: int = 10) -> list[dict[str, str]]:
    results = fetch_bing_results(f"site:youtube.com {query}", limit=limit * 3)
    videos: list[dict[str, str]] = []
    seen: set[str] = set()
    for result in results:
        url = result["url"]
        if "youtube.com/watch" not in url:
            continue
        parsed = urllib.parse.urlparse(url)
        video_id = urllib.parse.parse_qs(parsed.query).get("v", [""])[0]
        if not video_id or video_id in seen:
            continue
        seen.add(video_id)
        videos.append(
            {
                "title": result["title"],
                "video_id": video_id,
                "channel": "",
                "snippet": result.get("snippet", ""),
                "thumbnail": f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
                "url": f"{YOUTUBE_WATCH_PREFIX}{video_id}",
            }
        )
        if len(videos) >= limit:
            break
    return videos


def build_youtube_search_form(query: str = "") -> dict:
    return {
        "type": "form",
        "attributes": {"action": "/results", "method": "get"},
        "children": [
            {
                "type": "input",
                "attributes": {
                    "type": "search",
                    "name": "search_query",
                    "value": query,
                    "title": "Search YouTube",
                },
                "children": [],
            }
        ],
    }


def build_youtube_video_result(video: dict[str, str]) -> dict:
    title = video["title"]
    url = video["url"]
    channel = video.get("channel", "")
    snippet = video.get("snippet", "")
    children: list[dict] = []

    thumbnail = video.get("thumbnail", "")
    if thumbnail:
        children.append(
            {
                "type": "img",
                "attributes": {"src": thumbnail, "alt": title},
                "children": [],
            }
        )

    children.append(
        {
            "type": "h3",
            "attributes": {},
            "children": [],
            "text": title,
            "html": f'<a href="{html.escape(url)}" style="{RESULT_LINK_STYLE}">{html.escape(title)}</a>',
        }
    )
    if channel:
        children.append(
            {
                "type": "p",
                "attributes": {},
                "children": [],
                "text": channel,
                "html": f'<span style="{CHANNEL_STYLE}">{html.escape(channel)}</span>',
            }
        )
    if snippet:
        children.append(
            {
                "type": "p",
                "attributes": {},
                "children": [],
                "text": snippet,
                "html": f'<span style="{SNIPPET_STYLE}">{html.escape(snippet)}</span>',
            }
        )
    children.append(
        {
            "type": "p",
            "attributes": {},
            "children": [],
            "text": url,
            "html": f'<a href="{html.escape(url)}" style="color:#006621;font-size:12px;">{html.escape(url)}</a>',
        }
    )
    return {"type": "div", "attributes": {"class": "youtube-result"}, "children": children}


def build_youtube_search_results_dom(query: str, videos: list[dict[str, str]]) -> dict:
    children: list[dict] = [
        {
            "type": "p",
            "attributes": {},
            "children": [],
            "text": f"YouTube results for: {query}",
            "html": f'YouTube results for: <b>{html.escape(query)}</b>',
        },
        build_youtube_search_form(query),
    ]

    if not videos:
        children.append(
            {
                "type": "p",
                "attributes": {},
                "children": [],
                "text": "No videos found.",
                "html": "No videos found.",
            }
        )
        return {
            "type": "div",
            "attributes": {"class": "youtube-search-results"},
            "children": children,
        }

    for video in videos:
        children.append(build_youtube_video_result(video))

    return {
        "type": "div",
        "attributes": {"class": "youtube-search-results"},
        "children": children,
    }


def build_youtube_search_dom(source_url: str, html: str) -> dict:
    query = youtube_search_query_from_url(source_url)
    videos = parse_youtube_search_videos(html)
    if not videos:
        videos = fetch_bing_youtube_results(query)
    return build_youtube_search_results_dom(query, videos)
