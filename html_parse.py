"""Lenient HTML parsing for real-world pages (HTML5, not XML)."""

from __future__ import annotations

import html.parser
import re
from typing import Any

VOID_ELEMENTS = frozenset(
    {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }
)

SKIP_TAGS = frozenset({"script", "noscript", "template"})


class HTMLTreeBuilder(html.parser.HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.document: dict[str, Any] = {"type": "#document", "children": []}
        self._stack: list[dict[str, Any]] = [self.document]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]):
        tag = tag.lower()
        if tag in SKIP_TAGS:
            node: dict[str, Any] = {
                "type": tag,
                "skip": True,
                "attributes": {name: value if value is not None else "" for name, value in attrs},
                "children": [],
            }
            self._stack[-1]["children"].append(node)
            self._stack.append(node)
            return

        node: dict[str, Any] = {
            "type": tag,
            "attributes": {name: value if value is not None else "" for name, value in attrs},
            "children": [],
        }
        self._stack[-1]["children"].append(node)
        if tag not in VOID_ELEMENTS:
            self._stack.append(node)

    def handle_endtag(self, tag: str):
        tag = tag.lower()
        if len(self._stack) <= 1:
            return
        if self._stack[-1].get("skip") and self._stack[-1]["type"] == tag:
            self._stack.pop()
            return
        for index in range(len(self._stack) - 1, 0, -1):
            if self._stack[index].get("skip"):
                if self._stack[index]["type"] == tag:
                    self._stack.pop(index)
                return
            if self._stack[index]["type"] == tag:
                self._stack = self._stack[:index]
                return

    def handle_data(self, data: str):
        if not data:
            return
        parent = self._stack[-1]
        if parent.get("skip"):
            if parent["type"] == "script":
                parent.setdefault("text", "")
                parent["text"] += data
            return
        parent["children"].append({"type": "#text", "text": data})

    def handle_comment(self, data: str):
        return


def parse_html(html_source: str) -> dict[str, Any]:
    parser = HTMLTreeBuilder()
    parser.feed(html_source)
    parser.close()
    return parser.document


def find_first(node: dict[str, Any] | None, predicate) -> dict[str, Any] | None:
    if node is None:
        return None
    if predicate(node):
        return node
    for child in node.get("children", []):
        found = find_first(child, predicate)
        if found is not None:
            return found
    return None


def find_by_id(node: dict[str, Any], element_id: str) -> dict[str, Any] | None:
    return find_first(
        node,
        lambda n: n.get("type") not in {"#text", "#document"}
        and n.get("attributes", {}).get("id") == element_id,
    )


def extract_google_content(document: dict[str, Any]) -> dict[str, Any] | None:
    body = find_first(document, lambda n: n.get("type") == "body")
    if body is None:
        return None

    search_form = find_first(
        body,
        lambda n: n.get("type") == "form"
        and "/search" in n.get("attributes", {}).get("action", ""),
    )
    if search_form is not None:
        return {
            "type": "div",
            "attributes": {"class": "google-home"},
            "children": [search_form],
        }
    return None


def extract_page_content(document: dict[str, Any], source_url: str = "") -> dict[str, Any]:
    """Return the main readable subtree for known sites and generic pages."""
    if source_url and "google.com" in source_url:
        google_content = extract_google_content(document)
        if google_content is not None:
            return google_content

    body = find_first(document, lambda n: n.get("type") == "body")
    root = body or document

    content = find_by_id(root, "mw-content-text")
    if content is not None:
        return content

    for candidate_id in ("content", "main-content", "article"):
        content = find_by_id(root, candidate_id)
        if content is not None:
            return content

    for tag in ("main", "article"):
        content = find_first(root, lambda n, t=tag: n.get("type") == t)
        if content is not None:
            return content

    return root


def extract_title(document: dict[str, Any]) -> str:
    heading = find_by_id(document, "firstHeading")
    if heading is not None:
        return flatten_text(heading).strip()
    title_node = find_first(document, lambda n: n.get("type") == "title")
    if title_node is not None:
        return flatten_text(title_node).strip()
    for tag in ("h1",):
        heading = find_first(document, lambda n, t=tag: n.get("type") == t)
        if heading is not None:
            return flatten_text(heading).strip()
    return ""


def flatten_text(node: dict[str, Any]) -> str:
    if node.get("type") == "#text":
        return node.get("text", "")
    parts: list[str] = []
    for child in node.get("children", []):
        ctype = child.get("type")
        if ctype == "#text":
            parts.append(child.get("text", ""))
        elif ctype == "br":
            parts.append("\n")
        elif ctype in {"script", "style", "noscript"}:
            continue
        else:
            parts.append(flatten_text(child))
    return "".join(parts)


def inline_html(node: dict[str, Any]) -> str:
    """Convert a subtree to a small HTML fragment for QLabel rich text."""
    node_type = node.get("type")
    if node_type == "#text":
        return html.escape(node.get("text", ""))

    if node_type in SKIP_TAGS:
        return ""

    children = "".join(inline_html(child) for child in node.get("children", []))
    attrs = node.get("attributes", {})

    if node_type == "br":
        return "<br/>"
    if node_type == "img":
        src = html.escape(attrs.get("src", ""), quote=True)
        alt = html.escape(attrs.get("alt", ""), quote=True)
        return f'<img src="{src}" alt="{alt}"/>'
    if node_type == "a":
        href = html.escape(attrs.get("href", ""), quote=True)
        return f'<a href="{href}">{children}</a>'
    if node_type in {"b", "strong"}:
        return f"<b>{children}</b>"
    if node_type in {"i", "em"}:
        return f"<i>{children}</i>"
    if node_type == "sup":
        return f"<sup>{children}</sup>"
    if node_type == "sub":
        return f"<sub>{children}</sub>"
    if node_type == "span":
        return children
    if node_type == "abbr":
        title = html.escape(attrs.get("title", ""), quote=True)
        return f'<span title="{title}">{children}</span>'

    return children


def iter_nodes(node: dict[str, Any]):
    yield node
    for child in node.get("children", []):
        yield from iter_nodes(child)
