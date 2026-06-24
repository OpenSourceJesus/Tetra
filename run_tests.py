#!/usr/bin/env python3
"""Single automatic test entry point — no manual setup required."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LENNA_URL = "https://en.wikipedia.org/wiki/Lenna"
LENNA_HTML = ROOT / "lenna.html"


def prepare_bundles() -> None:
    from store import bundle_path, ensure_dirs
    from testserver.test_js_pipeline import LocalTestServer
    from www2json import ingest_to_file

    ensure_dirs()
    ingest_to_file(str(ROOT / "example.html"), bundle_path("DOM.json"))

    lenna_target = bundle_path("Lenna.json")
    if LENNA_HTML.exists():
        ingest_to_file(str(LENNA_HTML), lenna_target)
        return

    try:
        ingest_to_file(LENNA_URL, lenna_target)
        return
    except Exception as exc:
        print(f"==> Lenna URL fetch failed ({exc}); using offline article fixture")

    with LocalTestServer() as port:
        url = f"http://127.0.0.1:{port}/pages/article-fixture.html"
        ingest_to_file(url, lenna_target)


def test_js2qt_pipe() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "js2qt.py")],
        input="function demo(){alert('ok');}",
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError(result.stderr.strip() or "js2qt failed")
    if "QMessageBox.information" not in result.stdout:
        raise AssertionError("js2qt did not translate alert()")


def run_smoke_tests() -> int:
    env = os.environ.copy()
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    return subprocess.run(
        [sys.executable, str(ROOT / "smoke_test.py"), "all"],
        cwd=str(ROOT),
        env=env,
        check=False,
    ).returncode


def run_localhost_pipeline() -> int:
    return subprocess.run(
        [sys.executable, str(ROOT / "testserver" / "test_js_pipeline.py")],
        cwd=str(ROOT),
        check=False,
    ).returncode


def main() -> int:
    sys.path.insert(0, str(ROOT))

    print("==> prepare bundles")
    prepare_bundles()
    print("    ok")

    print("==> js2qt pipe")
    test_js2qt_pipe()
    print("    ok")

    if run_smoke_tests() != 0:
        return 1
    if run_localhost_pipeline() != 0:
        return 1

    print("All tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
