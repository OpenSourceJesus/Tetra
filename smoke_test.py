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
from store import BUNDLES_DIR, bundle_assets_dir, bundle_path


def find_first(node: dict, node_type: str) -> dict | None:
    if node.get("type") == node_type:
        return node
    for child in node.get("children", []):
        found = find_first(child, node_type)
        if found is not None:
            return found
    return None


def test_example_bundle() -> None:
    bundle = json.loads(bundle_path("DOM.json").read_text(encoding="utf-8"))
    assert bundle["dom"]["type"] == "button", bundle["dom"]
    assert bundle["dom"]["text"] == "hello world"
    assert "PyJsHoisted_foo_" in bundle["scripts"]
    assert "var.get('alert')" in bundle["scripts"]


def test_lenna_bundle() -> None:
    bundle = json.loads(bundle_path("Lenna.json").read_text(encoding="utf-8"))
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
        cached_assets = list(bundle_assets_dir(bundle_path("Lenna.json")).glob("*"))
        assert cached_assets, "image URL retained but no cached assets directory"
    else:
        assert (BUNDLES_DIR / src).exists(), src


def test_render_bundles() -> None:
    app = QApplication.instance() or QApplication(sys.argv)

    for bundle_name in ("DOM.json", "Lenna.json"):
        path = bundle_path(bundle_name)
        bundle = json.loads(path.read_text(encoding="utf-8"))

        runtime = JS2PY_RUNTIME()
        runtime.register_runtime_scripts(bundle.get("scripts", ""))
        if bundle_name == "DOM.json":
            assert "foo" in runtime.functions

        window = SafeOfflineBrowser(bundle, path)
        if bundle_name == "DOM.json":
            assert "foo" in window.runtime.functions
        assert window.base_layout.count() > 0, bundle_name

    del app


def test_google_bundle() -> None:
    from www2json import ingest
    from script_runtime import is_translated_script

    bundle = ingest("https://www.google.com/?gbv=1")
    dom = bundle["dom"]
    assert dom is not None
    dom_text = json.dumps(dom)
    assert "form" in dom_text or "input" in dom_text
    assert '"name": "q"' in dom_text or '"name":"q"' in dom_text.replace(" ", "")

    scripts = bundle.get("scripts", "")
    assert not scripts or is_translated_script(scripts)
    assert "window." not in scripts


def test_google_search_bundle() -> None:
    from www2json import ingest

    bundle = ingest("https://www.google.com/search?q=python+programming&gbv=1")
    assert bundle.get("title")
    dom = bundle["dom"]
    assert dom is not None

    dom_text = json.dumps(dom)
    assert dom_text.strip() not in ("", "null", "{}")


def test_youtube_search_bundle() -> None:
    from www2json import ingest

    bundle = ingest("https://www.youtube.com/results?search_query=cats")
    assert bundle.get("title")
    dom = bundle["dom"]
    assert dom is not None

    dom_text = json.dumps(dom)
    assert "search_query" in dom_text or "cats" in dom_text.lower()


def test_youtube_watch_bundle() -> None:
    from www2json import ingest

    bundle = ingest("https://www.youtube.com/watch?v=jNQXAC9IVRw")
    dom_text = json.dumps(bundle["dom"])
    assert "jNQXAC9IVRw" in dom_text or "jNQXAC9IVRw" in bundle.get("source", "")
    assert bundle.get("title")


def test_mp4_playability() -> None:
    from video import (
        MP4PlayabilityError,
        has_mp4_header,
        has_mp4_index,
        has_mp4_media_data,
        verify_playable_mp4,
    )

    assert not has_mp4_header(b"not a video")
    assert not has_mp4_index(b"xxxxxxxxx")
    assert not has_mp4_media_data(b"yyyyyyyyy")

    from store import VIDEOS_DIR

    sample = VIDEOS_DIR / "jNQXAC9IVRw.mp4"
    if not sample.exists():
        from video import download_youtube_video

        sample = download_youtube_video("jNQXAC9IVRw")

    data = sample.read_bytes()
    assert has_mp4_header(data)
    assert has_mp4_index(data)
    assert has_mp4_media_data(data)
    verify_playable_mp4(sample)

    try:
        verify_playable_mp4(sample.with_name("missing-file.mp4"))
        raise AssertionError("expected missing file to fail")
    except MP4PlayabilityError:
        pass


def test_xhr_search_runtime() -> None:
    from testserver.test_js_pipeline import LocalTestServer, assert_xhr_search

    with LocalTestServer() as port:
        assert_xhr_search(port)


def test_dom_mutation_runtime() -> None:
    from js2py_translator import translate_script
    from script_runtime import apply_scripts_to_dom

    dom = {
        "type": "body",
        "attributes": {},
        "children": [{"type": "div", "attributes": {"id": "app"}, "children": []}],
    }
    js = """
    document.addEventListener('DOMContentLoaded', function () {
      var el = document.createElement('div');
      el.textContent = 'Hello from translated JS';
      document.getElementById('app').appendChild(el);
    });
    """
    mutated, _, _ = apply_scripts_to_dom(dom, translate_script(js))
    assert "Hello from translated JS" in json.dumps(mutated)


def test_translate_script() -> None:
    from js2py_translator import translate_handlers, translate_script

    bootstrap = "window.foo = 1; document.title = 'x';"
    translated_bootstrap = translate_script(bootstrap)
    assert translated_bootstrap
    assert "var.get('window')" in translated_bootstrap
    assert translate_handlers(bootstrap) == ""

    translated = translate_script('function greet(){alert("hi");}')
    assert "PyJsHoisted_greet_" in translated
    assert "var.get('alert')" in translated


def test_launch_vlc_command() -> None:
    from unittest.mock import patch

    from video import launch_vlc

    with patch("video.find_vlc_executable", return_value="/usr/bin/vlc"), patch(
        "video.subprocess.Popen"
    ) as popen, patch("video.verify_playable_mp4"):
        launch_vlc("/tmp/offline-browser/videos/test.mp4")
        args = popen.call_args[0][0]
        assert args[0] == "/usr/bin/vlc"
        assert args[1] == "--no-one-instance"
        assert args[2].endswith("test.mp4")

        popen.reset_mock()
        launch_vlc("https://example.com/videoplayback?foo=1", title="My Video")
        args = popen.call_args[0][0]
        assert args[1] == "--no-one-instance"
        assert args[2] == "--meta-title=My Video"
        assert args[3] == "--video-title=My Video"
        assert args[4].startswith("https://")

        popen.reset_mock()
        launch_vlc("https://example.com/videoplayback?foo=1")
        args = popen.call_args[0][0]
        assert args[2] == "--no-video-title-show"


def test_youtube_stream_url() -> None:
    from navigation import youtube_watch_url
    from video import extract_youtube_stream

    stream = extract_youtube_stream(youtube_watch_url("jNQXAC9IVRw"))
    assert stream["url"].startswith("https://")
    assert stream.get("title")


def test_youtube_video_cache() -> None:
    from store import video_cache_path
    from video import download_youtube_video, verify_playable_mp4

    first = download_youtube_video("jNQXAC9IVRw")
    assert first == video_cache_path("jNQXAC9IVRw")
    verify_playable_mp4(first)
    second = download_youtube_video("jNQXAC9IVRw")
    assert second == first


def test_tui_render() -> None:
    from json2tui import render_bundle_to_string

    for bundle_name in ("DOM.json", "Lenna.json"):
        path = bundle_path(bundle_name)
        bundle = json.loads(path.read_text(encoding="utf-8"))
        output = render_bundle_to_string(bundle, path)
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

    from sixel import PROFILES, encode_sixel, get_text_sixel

    image = Image.new("P", (12, 12))
    image.putpalette([0, 0, 0, 255, 255, 255] + [0] * 750)
    pixels = image.load()
    for y in range(12):
        for x in range(12):
            pixels[x, y] = (x + y) % 2

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
    from store import sixel_cache_path
    from testserver.test_js_pipeline import SAMPLE_PNG, ensure_sample_asset

    ensure_sample_asset()
    assert SAMPLE_PNG.exists(), SAMPLE_PNG
    preview = prepare_preview_image(SAMPLE_PNG)
    first = encode_sixel(preview)
    cache_path = sixel_cache_path(SAMPLE_PNG, 160, 16)
    cache_path.write_text(first, encoding="utf-8")
    second, _, _ = get_sixel_preview(SAMPLE_PNG, use_cache=True)
    assert second == first
    assert len(first) > 100


def test_tui_store() -> None:
    from store import cache_bundle_path
    from tui_store import load_db, record_search, record_visit

    bundle = cache_bundle_path("https://example.com/test-page")
    record_visit("https://example.com/test-page", bundle, viewer="tui")
    record_search("example query", "https://www.google.com/search?q=example")
    db = load_db()
    assert db["history"]
    assert db["searches"]


def test_localhost_js_pipeline() -> None:
    from testserver.test_js_pipeline import run_tests

    run_tests()


ALL_TESTS = (
    "example",
    "lenna",
    "google",
    "google-search",
    "youtube-search",
    "youtube-watch",
    "dom-mutation",
    "xhr-search",
    "translate-script",
    "launch-vlc",
    "youtube-stream",
    "mp4-playability",
    "youtube-video-cache",
    "render",
    "tui",
    "sixel",
    "sixel-cache",
    "tui-store",
)


def main() -> int:
    tests = {
        "example": test_example_bundle,
        "lenna": test_lenna_bundle,
        "google": test_google_bundle,
        "google-search": test_google_search_bundle,
        "youtube-search": test_youtube_search_bundle,
        "youtube-watch": test_youtube_watch_bundle,
        "dom-mutation": test_dom_mutation_runtime,
        "xhr-search": test_xhr_search_runtime,
        "translate-script": test_translate_script,
        "launch-vlc": test_launch_vlc_command,
        "youtube-stream": test_youtube_stream_url,
        "mp4-playability": test_mp4_playability,
        "youtube-video-cache": test_youtube_video_cache,
        "render": test_render_bundles,
        "tui": test_tui_render,
        "sixel": test_sixel_encode,
        "sixel-cache": test_sixel_cache,
        "tui-store": test_tui_store,
    }

    requested = sys.argv[1:]
    if not requested or requested == ["all"]:
        selected = ALL_TESTS
    else:
        selected = requested

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
