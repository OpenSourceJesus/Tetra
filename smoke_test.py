#!/usr/bin/env python3
"""Smoke tests for the offline browser pipeline."""

from __future__ import annotations

import json
import sys
import types
from collections import Counter
from pathlib import Path

from PyQt5.QtWidgets import QApplication

from json2qt import JS2PY_RUNTIME, SafeOfflineBrowser


def find_first(node: dict, node_type: str) -> dict | None:
    if node.get("type") == node_type:
        return node
    for child in node.get("children", []):
        found = find_first(child, node_type)
        if found is not None:
            return found
    return None


def test_example_bundle() -> None:
    bundle = json.loads(Path("DOM.json").read_text(encoding="utf-8"))
    assert bundle["dom"]["type"] == "button", bundle["dom"]
    assert bundle["dom"]["text"] == "hello world"
    assert "def foo" in bundle["scripts"]
    assert "QMessageBox" in bundle["scripts"]


def test_lenna_bundle() -> None:
    bundle = json.loads(Path("Lenna.json").read_text(encoding="utf-8"))
    assert bundle.get("title") == "Lenna", bundle.get("title")

    counts: Counter[str] = Counter()

    def walk(node: dict) -> None:
        counts[node.get("type", "?")] += 1
        for child in node.get("children", []):
            walk(child)

    walk(bundle["dom"])
    assert counts["p"] >= 10, counts["p"]
    assert counts["h2"] >= 5, counts["h2"]
    assert counts["img"] >= 1, counts["img"]

    image = find_first(bundle["dom"], "img")
    assert image is not None, "missing image node"
    src = image.get("attributes", {}).get("src", "")
    if src.startswith(("http://", "https://", "//")):
        cached_assets = list(Path("Lenna_assets").glob("*"))
        assert cached_assets, "image URL retained but no cached assets directory"
    else:
        assert Path(src).exists(), src


def test_render_bundles() -> None:
    app = QApplication.instance() or QApplication(sys.argv)

    for bundle_name in ("DOM.json", "Lenna.json"):
        bundle_path = Path(bundle_name)
        bundle = json.loads(bundle_path.read_text(encoding="utf-8"))

        runtime = JS2PY_RUNTIME()
        runtime.register_runtime_scripts(bundle.get("scripts", ""))
        if bundle_name == "DOM.json":
            assert "foo" in runtime.functions

        window = SafeOfflineBrowser(bundle, bundle_path)
        assert window.base_layout.count() > 0, bundle_name

    del app


def test_google_bundle() -> None:
    from www2json import ingest

    bundle = ingest("https://www.google.com/?gbv=1")
    dom = bundle["dom"]
    assert dom is not None
    dom_text = json.dumps(dom)
    assert "form" in dom_text
    assert '"name": "q"' in dom_text or '"name":"q"' in dom_text.replace(" ", "")


def test_google_search_bundle() -> None:
    from www2json import ingest

    bundle = ingest("https://www.google.com/search?q=python+programming&gbv=1")
    assert bundle.get("title") == "Google Search"
    dom = bundle["dom"]
    assert dom is not None

    counts: Counter[str] = Counter()

    def walk(node: dict) -> None:
        counts[node.get("type", "?")] += 1
        for child in node.get("children", []):
            walk(child)

    walk(dom)
    assert counts["h3"] >= 3, counts
    assert counts["p"] >= 3, counts


def main() -> int:
    tests = {
        "example": test_example_bundle,
        "lenna": test_lenna_bundle,
        "google": test_google_bundle,
        "google-search": test_google_search_bundle,
        "render": test_render_bundles,
    }

    selected = sys.argv[1:] or tests.keys()
    for name in selected:
        if name not in tests:
            print(f"Unknown test: {name}", file=sys.stderr)
            return 1
        print(f"==> smoke_test: {name}")
        tests[name]()
        print("    ok")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
