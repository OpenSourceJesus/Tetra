"""Localhost mock search engine for frontend/backend integration tests."""

from __future__ import annotations

import html
import json
import re
import urllib.parse
from typing import Any

RESULT_PAGES: dict[str, dict[str, str]] = {
    "python-docs": {
        "title": "Python documentation",
        "summary": "Official Python language reference, tutorials, and library docs.",
        "body": (
            "Python is a programming language that lets you work quickly and "
            "integrate systems more effectively."
        ),
    },
    "python-wiki": {
        "title": "Python (programming language) - Wikipedia",
        "summary": "Overview of Python's history, design, and ecosystem.",
        "body": (
            "Python is a high-level, general-purpose programming language. "
            "Its design philosophy emphasizes code readability."
        ),
    },
    "cats-wiki": {
        "title": "Cat - Wikipedia",
        "summary": "Domestic cats, behavior, breeds, and history.",
        "body": "The cat is a domestic species of small carnivorous mammal.",
    },
    "cats-care": {
        "title": "Cat care basics",
        "summary": "Feeding, grooming, enrichment, and veterinary care for cats.",
        "body": "Healthy cats need fresh water, balanced food, and regular play.",
    },
    "offline-browser": {
        "title": "Offline Browser project",
        "summary": "HTML ingest, Js2Py translation, and Qt rendering pipeline.",
        "body": (
            "This mock result exercises search ingestion, script translation, "
            "and link navigation in the offline browser."
        ),
    },
    "localhost-fixture": {
        "title": "Localhost test fixture",
        "summary": "Static page served by the Python test webserver.",
        "body": "Use this page to verify bundle caching and history navigation.",
    },
}

SEARCH_INDEX: list[dict[str, str]] = [
    {
        "id": "python-docs",
        "title": "Python documentation",
        "snippet": "Download, install, and learn Python from the official docs.",
        "keywords": "python docs tutorial language reference",
    },
    {
        "id": "python-wiki",
        "title": "Python (programming language) - Wikipedia",
        "snippet": "History, syntax, and applications of the Python language.",
        "keywords": "python wikipedia programming history",
    },
    {
        "id": "cats-wiki",
        "title": "Cat - Wikipedia",
        "snippet": "Learn about domestic cats, breeds, and behavior.",
        "keywords": "cats wiki feline pets animals",
    },
    {
        "id": "cats-care",
        "title": "Cat care basics",
        "snippet": "Practical guide to caring for indoor and outdoor cats.",
        "keywords": "cats care feeding grooming pets",
    },
    {
        "id": "offline-browser",
        "title": "Offline Browser project",
        "snippet": "Js2Py translation, DOM runtime, and Qt viewer.",
        "keywords": "browser offline js2py qt python mock search",
    },
    {
        "id": "localhost-fixture",
        "title": "Localhost test fixture",
        "snippet": "Example content served from the local Python webserver.",
        "keywords": "localhost fixture testserver pages",
    },
]


def _esc(text: str) -> str:
    return html.escape(text, quote=True)


def search_results(query: str) -> list[dict[str, str]]:
    query = query.strip()
    if not query:
        return list(SEARCH_INDEX)

    tokens = [token for token in re.split(r"\s+", query.lower()) if token]
    scored: list[tuple[int, dict[str, str]]] = []
    for entry in SEARCH_INDEX:
        haystack = " ".join(
            (entry["title"], entry["snippet"], entry["keywords"], entry["id"])
        ).lower()
        score = sum(1 for token in tokens if token in haystack)
        if score:
            scored.append((score, entry))
    scored.sort(key=lambda item: (-item[0], item[1]["title"].lower()))
    if scored:
        return [entry for _, entry in scored]
    return [
        {
            "id": "offline-browser",
            "title": f'No exact matches for "{query}"',
            "snippet": "Try python, cats, localhost, or browser.",
            "keywords": query,
        }
    ]


def result_href(result_id: str) -> str:
    return f"/result/{urllib.parse.quote(result_id, safe='')}"


def render_home() -> bytes:
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Mock Search</title>
  <script>
    function focusSearch() {{
      var input = document.getElementById('q');
      if (input) input.focus();
    }}
    document.addEventListener('DOMContentLoaded', focusSearch);
  </script>
</head>
<body>
  <main>
    <h1>Mock Search</h1>
    <p>Local Python search engine for offline browser testing.</p>
    <form action="/search" method="get">
      <input id="q" type="search" name="q" placeholder="Search the mock index">
      <button type="submit">Search</button>
    </form>
    <p><a href="/pages/basic.html">Open localhost JS test page</a></p>
  </main>
</body>
</html>
"""
    return page.encode("utf-8")


def render_results(query: str) -> bytes:
    query_text = query.strip()
    results = search_results(query_text)
    blocks: list[str] = []
    for entry in results:
        href = result_href(entry["id"])
        blocks.append(
            f"""<div class="g">
  <h3><a href="{_esc(href)}">{_esc(entry["title"])}</a></h3>
  <p>{_esc(entry["snippet"])}</p>
</div>"""
        )

    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Mock Search: {_esc(query_text or "all")}</title>
  <script>
    document.addEventListener('DOMContentLoaded', function () {{
      var stats = document.getElementById('stats');
      if (stats) {{
        stats.textContent = 'Translated JS loaded ' + {len(results)!r} + ' results.';
      }}
    }});
  </script>
</head>
<body>
  <header>
    <h1>Mock Search</h1>
    <form action="/search" method="get">
      <input type="search" name="q" value="{_esc(query_text)}">
      <button type="submit">Search</button>
    </form>
  </header>
  <p id="stats"></p>
  <section class="results">
    {''.join(blocks)}
  </section>
</body>
</html>
"""
    return page.encode("utf-8")


def render_result_page(result_id: str) -> bytes | None:
    page = RESULT_PAGES.get(result_id)
    if page is None:
        return None

    body = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{_esc(page["title"])}</title>
</head>
<body>
  <article>
    <h1>{_esc(page["title"])}</h1>
    <p>{_esc(page["summary"])}</p>
    <p>{_esc(page["body"])}</p>
    <p><a href="/search?q={_esc('python')}">Back to mock search results</a></p>
    <p><a href="/">Mock Search home</a></p>
  </article>
</body>
</html>
"""
    return body.encode("utf-8")


def render_api_search(query: str) -> bytes:
    query_text = query.strip()
    payload = {
        "query": query_text,
        "results": [
            {
                "id": entry["id"],
                "title": entry["title"],
                "snippet": entry["snippet"],
                "url": result_href(entry["id"]),
            }
            for entry in search_results(query_text)
        ],
    }
    return json.dumps(payload).encode("utf-8")


def handle_mock_search(path: str, query: str) -> tuple[int, str, bytes] | None:
    """Return (status, content_type, body) for mock-search routes, or None."""
    clean = path.rstrip("/") or "/"
    if clean == "/api/search":
        params = urllib.parse.parse_qs(query)
        q = urllib.parse.unquote_plus(params.get("q", [""])[0])
        return 200, "application/json; charset=utf-8", render_api_search(q)
    if clean == "/":
        return 200, "text/html; charset=utf-8", render_home()
    if clean == "/search":
        params = urllib.parse.parse_qs(query)
        q = urllib.parse.unquote_plus(params.get("q", [""])[0])
        return 200, "text/html; charset=utf-8", render_results(q)
    if clean.startswith("/result/"):
        result_id = urllib.parse.unquote(clean[len("/result/") :])
        body = render_result_page(result_id)
        if body is None:
            return 404, "text/plain; charset=utf-8", b"Result not found"
        return 200, "text/html; charset=utf-8", body
    return None
