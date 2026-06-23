#!/usr/bin/env python3
"""End-to-end localhost tests for HTML fetch, JS translation, and runtime wiring."""

from __future__ import annotations

import socket
import subprocess
import sys
import time
import types
import urllib.error
import urllib.request
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent.parent
SERVER_SCRIPT = SCRIPT_DIR / "testserver" / "server.py"

CASES = (
    {
        "page": "basic.html",
        "title": "Basic JS Test",
        "functions": ("greet",),
        "button_hooks": ("greet",),
        "script_markers": ("def greet", "QMessageBox.information", "hello from localhost"),
    },
    {
        "page": "multi.html",
        "title": "Multi handler test",
        "functions": ("hello", "goodbye"),
        "button_hooks": ("hello", "goodbye"),
        "script_markers": ("def hello", "def goodbye", "QMessageBox.information"),
    },
)


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait_for_server(port: int, timeout: float = 10.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/pages/basic.html", timeout=1):
                return
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            time.sleep(0.05)
    raise RuntimeError(f"test server did not start on port {port}")


class LocalTestServer:
    def __init__(self, port: int | None = None):
        self.port = port or free_port()
        self.process: subprocess.Popen | None = None

    def __enter__(self) -> int:
        self.process = subprocess.Popen(
            [sys.executable, str(SERVER_SCRIPT), "--port", str(self.port), "--quiet"],
            cwd=str(SCRIPT_DIR),
        )
        wait_for_server(self.port)
        return self.port

    def __exit__(self, exc_type, exc, tb) -> None:
        if self.process is None:
            return
        self.process.terminate()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5)


def find_buttons(node: dict) -> list[dict]:
    buttons: list[dict] = []
    if node.get("type") == "button":
        buttons.append(node)
    for child in node.get("children", []):
        buttons.extend(find_buttons(child))
    return buttons


def hook_name(onclick: str) -> str:
    return onclick.split("(")[0].strip()


def assert_bundle(case: dict, bundle: dict) -> None:
    assert bundle.get("title") == case["title"], bundle.get("title")
    assert bundle.get("dom"), "missing DOM tree"

    scripts = bundle.get("scripts", "")
    assert scripts.strip(), "compiled scripts are empty"
    for marker in case["script_markers"]:
        assert marker in scripts, f"missing script marker: {marker}"

    namespace: dict = {}
    exec(scripts, namespace)
    for func_name in case["functions"]:
        assert func_name in namespace, f"missing function: {func_name}"
        assert isinstance(namespace[func_name], types.FunctionType), func_name

    buttons = find_buttons(bundle["dom"])
    assert len(buttons) == len(case["button_hooks"]), buttons
    wired = {hook_name(btn.get("attributes", {}).get("onclick", "")) for btn in buttons}
    assert wired == set(case["button_hooks"]), wired


def run_tests() -> None:
    sys.path.insert(0, str(SCRIPT_DIR))
    from www2json import ingest

    with LocalTestServer() as port:
        for case in CASES:
            url = f"http://127.0.0.1:{port}/pages/{case['page']}"
            bundle = ingest(url)
            assert_bundle(case, bundle)
            print(f"    ok  {case['page']}")


def main() -> int:
    print("==> localhost JS pipeline")
    try:
        run_tests()
    except Exception as exc:
        print(f"    FAIL  {exc}", file=sys.stderr)
        return 1
    print("    all localhost JS tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
