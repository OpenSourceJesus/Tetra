"""Search result fetching and synthetic DOM construction."""

from __future__ import annotations

import base64
import html
import re
import urllib.parse
import urllib.request

from html_parse import flatten_text, iter_nodes, parse_html
from navigation import BROWSER_UA, search_query_from_url

RESULT_LINK_STYLE = "color: #1a0dab; font-size: 18px; text-decoration: none;"
SNIPPET_STYLE = "color: #4d5156; margin: 2px 0 16px 0;"


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
