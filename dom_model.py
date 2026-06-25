"""Mutable DOM tree for translated page scripts."""

from __future__ import annotations

import copy
import re
from typing import Any, Callable

from html_parse import find_first, iter_nodes, parse_html

VOID_ELEMENTS = frozenset(
    {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
)


class DomModel:
    """Live document.body tree that translated scripts can mutate."""

    def __init__(self, body: dict[str, Any]):
        self.body = copy.deepcopy(body)
        self.title = ""
        self._by_id: dict[str, dict[str, Any]] = {}
        self._listeners: dict[str, list[Callable]] = {}
        self._reindex()

    def _reindex(self) -> None:
        self._by_id.clear()
        for node in iter_nodes(self.body):
            node_id = node.get("attributes", {}).get("id")
            if node_id:
                self._by_id[node_id] = node

    def _register(self, node: dict[str, Any]) -> None:
        node_id = node.get("attributes", {}).get("id")
        if node_id:
            self._by_id[node_id] = node
        for child in node.get("children", []):
            self._register(child)

    def display_dom(self) -> dict[str, Any]:
        return copy.deepcopy(self.body)

    def get_element_by_id(self, element_id: str) -> dict[str, Any] | None:
        return self._by_id.get(element_id)

    def query_selector(self, selector: str) -> dict[str, Any] | None:
        selector = selector.strip()
        if selector.startswith("#"):
            return self.get_element_by_id(selector[1:])
        if selector.startswith("."):
            class_name = selector[1:]
            return find_first(
                self.body,
                lambda node, name=class_name: class_name
                in node.get("attributes", {}).get("class", "").split(),
            )
        return find_first(self.body, lambda node, tag=selector: node.get("type") == tag)

    def create_element(self, tag: str) -> dict[str, Any]:
        return {"type": tag.lower(), "attributes": {}, "children": []}

    def append_child(self, parent: dict[str, Any], child: dict[str, Any]) -> None:
        parent.setdefault("children", []).append(child)
        self._register(child)

    def remove_child(self, parent: dict[str, Any], child: dict[str, Any]) -> None:
        children = parent.get("children", [])
        if child in children:
            children.remove(child)

    def set_attribute(self, node: dict[str, Any], name: str, value: Any) -> None:
        node.setdefault("attributes", {})[name] = str(value)
        if name == "id":
            self._reindex()

    def get_attribute(self, node: dict[str, Any], name: str) -> str:
        return node.get("attributes", {}).get(name, "")

    def set_text_content(self, node: dict[str, Any], text: str) -> None:
        node["text"] = str(text)
        node.pop("html", None)
        node["children"] = []

    def get_text_content(self, node: dict[str, Any]) -> str:
        if node.get("text"):
            return str(node["text"])
        parts: list[str] = []
        for child in node.get("children", []):
            if child.get("type") == "#text":
                parts.append(child.get("text", ""))
            else:
                parts.append(self.get_text_content(child))
        return "".join(parts)

    def set_inner_html(self, node: dict[str, Any], html: str) -> None:
        html = str(html)
        node.pop("text", None)
        if "<" not in html:
            node["text"] = html
            node["children"] = []
            return
        wrapped = f"<div id='__fragment_root__'>{html}</div>"
        parsed = parse_html(wrapped)
        fragment_root = find_first(parsed, lambda n: n.get("attributes", {}).get("id") == "__fragment_root__")
        if fragment_root is None:
            node["text"] = html
            node["children"] = []
            return
        node["children"] = copy.deepcopy(fragment_root.get("children", []))
        node["html"] = html
        self._reindex()

    def get_inner_html(self, node: dict[str, Any]) -> str:
        if "html" in node:
            return str(node["html"])
        if node.get("text"):
            return str(node["text"])
        parts: list[str] = []
        for child in node.get("children", []):
            if child.get("type") == "#text":
                parts.append(child.get("text", ""))
            else:
                tag = child.get("type", "div")
                attrs = child.get("attributes", {})
                attr_text = "".join(f' {name}="{value}"' for name, value in attrs.items())
                inner = self.get_inner_html(child)
                if tag in VOID_ELEMENTS:
                    parts.append(f"<{tag}{attr_text}>")
                else:
                    parts.append(f"<{tag}{attr_text}>{inner}</{tag}>")
        return "".join(parts)

    def add_event_listener(self, event: str, handler: Callable) -> None:
        self._listeners.setdefault(event, []).append(handler)

    def dispatch_event(self, event: str) -> None:
        for handler in list(self._listeners.get(event, [])):
            handler()

    def click_element(self, node: dict[str, Any]) -> None:
        onclick = node.get("attributes", {}).get("onclick", "")
        if onclick:
            self._pending_click = onclick
        for handler in list(self._listeners.get("click", [])):
            handler()
