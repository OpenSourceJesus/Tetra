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


def test_tui_render() -> None:
    from json2tui import render_bundle_to_string

    for bundle_name in ("DOM.json", "Lenna.json"):
        bundle_path = Path(bundle_name)
        bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
        output = render_bundle_to_string(bundle, bundle_path)
        assert output.strip(), bundle_name
        if bundle_name == "DOM.json":
            assert "hello world" in output.lower()
        if bundle_name == "Lenna.json":
            assert "lenna" in output.lower()
            assert "references" not in output.lower()
            assert "978-0-201-18075-6" not in output
            assert "stanford bunny" not in output.lower()


def test_sixel_encode() -> None:
    from PIL import Image

    from sixel import encode_sixel, get_text_sixel

    image = Image.new("P", (12, 12))
    image.putpalette([0, 0, 0, 255, 255, 255] + [0] * 750)
    pixels = image.load()
    for y in range(12):
        for x in range(12):
            pixels[x, y] = (x + y) % 2
    from sixel import PROFILES

    encoded = encode_sixel(image, profile=PROFILES["konsole"])
    assert encoded.startswith("\x1bPq")
    assert encoded.endswith("\x1b\\")
    assert '"1;1;12;12' in encoded
    assert "#0;2;0;0;0" in encoded
    assert "#1;2;100;100;100" in encoded
    assert ";2;1;" not in encoded
    assert encoded.count("$") >= 1
    assert encoded.count("-") >= 1

    text_sixel, width, height = get_text_sixel("Hello tiny terminal text", use_cache=False)
    assert width > 0 and height > 0
    assert width < 400
    assert text_sixel.startswith("\x1bPq")


def test_sixel_cache() -> None:
    from sixel import encode_sixel, get_sixel_preview, prepare_preview_image
    from tui_store import sixel_cache_path

    image = Path("Lenna_assets/f1a7f59bee7ac204.png")
    if not image.exists():
        return
    preview = prepare_preview_image(image)
    first = encode_sixel(preview)
    cache_path = sixel_cache_path(image, 160, 16)
    cache_path.write_text(first, encoding="utf-8")
    second, w2, h2 = get_sixel_preview(image, use_cache=True)
    assert second == first
    assert len(first) > 100


def test_tui_store() -> None:
    from tui_store import cache_bundle_path, load_db, record_search, record_visit

    bundle = cache_bundle_path("https://example.com/test-page")
    record_visit("https://example.com/test-page", bundle, viewer="tui")
    record_search("example query", "https://www.google.com/search?q=example")
    db = load_db()
    assert db["history"]
    assert db["searches"]


def main() -> int:
    tests = {
        "example": test_example_bundle,
        "lenna": test_lenna_bundle,
        "google": test_google_bundle,
        "google-search": test_google_search_bundle,
        "render": test_render_bundles,
        "tui": test_tui_render,
        "sixel": test_sixel_encode,
        "sixel-cache": test_sixel_cache,
        "tui-store": test_tui_store,
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
