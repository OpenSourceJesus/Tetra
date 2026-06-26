#!/usr/bin/env python3
"""Online Qt browser: fetch HTML, translate JS with Js2Py, render interactively.

Combines the JSON ingest pipeline (www2json) with the Qt viewer (json2qt).
Includes an optional embedded mock webmail server for multi-step XMLHttpRequest tests.
"""

from __future__ import annotations

import argparse
import socket
import sys
import threading
import time
import urllib.request
from http.server import HTTPServer
from pathlib import Path

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import QApplication, QLabel, QLineEdit, QMessageBox, QPushButton, QVBoxLayout, QWidget

from dom_model import DomModel
from html_parse import extract_page_content, flatten_text_nodes, iter_nodes
from js2py_runtime import build_runtime, extract_handlers
from js_objects import Js, call_value
from json2qt import (
    HEADING_STYLES,
    SafeOfflineBrowser,
    add_bookmark,
    cache_bundle_path,
    record_history,
)
from navigation import default_home_url, enable_mock_search, normalize_url, prepare_fetch_url
from script_runtime import _script_chunks, is_translated_script
from store import default_bundle_path
from testserver.server import TestPageHandler, reset_uploads
from testserver.mock_email import reset_sessions
from www2json import ingest, ingest_to_file

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_PORT = 8765


def mock_mail_url(port: int = DEFAULT_PORT) -> str:
    return f"http://127.0.0.1:{port}/pages/mail.html"


def wait_for_server(port: int, path: str = "/pages/mail.html", timeout: float = 10.0) -> None:
    deadline = time.time() + timeout
    url = f"http://127.0.0.1:{port}{path}"
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1):
                return
        except Exception:
            time.sleep(0.05)
    raise RuntimeError(f"mock server did not start on port {port}")


class MockServerThread:
    """Background thread running the localhost test webserver."""

    def __init__(self, port: int = DEFAULT_PORT, bind: str = "127.0.0.1"):
        self.port = port
        self.bind = bind
        self._server: HTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> int:
        reset_uploads()
        reset_sessions()
        self._server = HTTPServer((self.bind, self.port), TestPageHandler)
        self._server.verbose = False

        def serve() -> None:
            assert self._server is not None
            self._server.serve_forever()

        self._thread = threading.Thread(target=serve, daemon=True)
        self._thread.start()
        wait_for_server(self.port)
        return self.port

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None


def _node_hidden(attributes: dict) -> bool:
    display = ""
    for decl in attributes.get("style", "").split(";"):
        name, sep, value = decl.partition(":")
        if sep and name.strip().lower() == "display":
            display = value.strip().lower()
    return display == "none"


class OnlineBrowser(SafeOfflineBrowser):
    """Qt browser that keeps a live DOM and refreshes the view after script/XHR updates."""

    def __init__(self, render_bundle: dict | None = None, bundle_path: Path | None = None):
        self._live_dom: DomModel | None = None
        self._var_scope = None
        self._title_label: QLabel | None = None
        super().__init__(render_bundle, bundle_path)

    def _script_namespace(self) -> dict:
        return {
            "QMessageBox": QMessageBox,
            "page_url": self.source,
            "xhr_complete": self._schedule_refresh,
        }

    def _schedule_refresh(self) -> None:
        QTimer.singleShot(0, self.refresh_from_dom)

    def _wrap_handler(self, handler):
        def wrapped(*_args, **_kwargs):
            self._sync_form_fields_to_dom()
            handler()
            self.refresh_from_dom()

        wrapped.__name__ = getattr(handler, "__name__", "handler")
        return wrapped

    def _parse_onclick_args(self, args_part: str) -> list:
        args_part = args_part.strip()
        if not args_part:
            return []
        values: list = []
        for piece in args_part.split(","):
            piece = piece.strip()
            if not piece:
                continue
            if piece.isdigit():
                values.append(int(piece))
            elif (piece.startswith("'") and piece.endswith("'")) or (
                piece.startswith('"') and piece.endswith('"')
            ):
                values.append(piece[1:-1])
            else:
                values.append(piece)
        return values

    def _invoke_script(self, name: str, args: list | None = None) -> None:
        self._sync_form_fields_to_dom()
        if self._var_scope is None:
            return
        target = self._var_scope.get(name)
        js_args = [Js(arg) if isinstance(arg, int) else Js(arg) for arg in (args or [])]
        call_value(target, js_args)
        self.refresh_from_dom()

    def _connect_onclick(self, widget: QPushButton, onclick: str) -> None:
        onclick = onclick.strip().rstrip(";")
        if not onclick:
            return
        if "(" not in onclick:
            hook_name = onclick
            wrapped = self.runtime.functions.get(hook_name)
            if wrapped:
                widget.clicked.connect(wrapped)
            return

        hook_name = onclick.split("(")[0].strip()
        args_part = onclick[onclick.index("(") + 1 : onclick.rindex(")")]
        args = self._parse_onclick_args(args_part)

        if ";" in onclick:
            widget.clicked.connect(lambda: self._run_onclick_script(onclick))
            return

        widget.clicked.connect(lambda: self._invoke_script(hook_name, args))

    def _run_onclick_script(self, script: str) -> None:
        self._sync_form_fields_to_dom()
        for statement in script.split(";"):
            statement = statement.strip()
            if not statement:
                continue
            if "(" in statement:
                name = statement.split("(")[0].strip()
                args_part = statement[statement.index("(") + 1 : statement.rindex(")")]
                self._invoke_script(name, self._parse_onclick_args(args_part))
            else:
                self._invoke_script(statement, [])

    def _sync_form_fields_to_dom(self) -> None:
        if self._live_dom is None:
            return
        for name, field in self.form_fields.items():
            if not isinstance(field, QLineEdit):
                continue
            for node in iter_nodes(self._live_dom.body):
                if node.get("type") not in {"input", "textarea"}:
                    continue
                attrs = node.get("attributes", {})
                if attrs.get("name") == name or attrs.get("id") == name:
                    attrs["value"] = field.text()

    def clear_view(self) -> None:
        while self.base_layout.count():
            item = self.base_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self.form_fields.clear()
        self._file_previews.clear()
        self.active_form = None
        self.primary_form = None
        self._title_label = None

    def refresh_from_dom(self) -> None:
        if self._live_dom is None:
            return

        self.clear_view()
        if self._live_dom.title:
            self.page_title = self._live_dom.title

        if self.page_title:
            self._title_label = QLabel(self.page_title)
            self._title_label.setStyleSheet(HEADING_STYLES["h1"])
            self._title_label.setWordWrap(True)
            self.base_layout.addWidget(self._title_label)

        display_doc = {
            "type": "#document",
            "children": [{"type": "html", "children": [self._live_dom.display_dom()]}],
        }
        content_root = flatten_text_nodes(extract_page_content(display_doc, self.source))
        if content_root:
            self.generate_interface(content_root, self.base_layout)

        window_title = self.page_title or "Browser"
        self.setWindowTitle(f"{window_title} — {self.source}")
        self.status_label.setText("Ready")
        QApplication.processEvents()

    def load_bundle(self, render_bundle: dict, bundle_path: Path):
        self.clear_content()
        self.bundle_path = bundle_path
        self.source = render_bundle.get("source", str(bundle_path))
        self.page_title = render_bundle.get("title", "")
        self.url_bar.setText(self.source)

        document_dom = render_bundle.get("document_dom") or render_bundle.get("dom") or {}
        scripts = render_bundle.get("scripts", "")
        self._live_dom = DomModel(document_dom)
        namespace = self._script_namespace()
        handlers: dict = {}
        if is_translated_script(scripts):
            runtime = build_runtime(namespace, dom_model=self._live_dom)
            for chunk in _script_chunks(scripts):
                try:
                    exec(chunk, runtime)
                except Exception:
                    pass
            self._var_scope = runtime["var"]
            handlers = extract_handlers(runtime)
            try:
                self._live_dom.dispatch_event("DOMContentLoaded")
            except Exception:
                pass
        else:
            self._var_scope = None
            self._live_dom.dispatch_event("DOMContentLoaded")

        self.runtime.functions.update({name: self._wrap_handler(fn) for name, fn in handlers.items()})
        if self._live_dom.title:
            self.page_title = self._live_dom.title

        self.refresh_from_dom()
        self._page_loaded = True
        self._update_nav_buttons()

        from navigation import is_youtube_watch, youtube_video_id_from_url

        if is_youtube_watch(self.source):
            self.play_youtube_video()

    def generate_interface(self, node: dict, active_layout: QVBoxLayout, in_form: bool = False):
        attributes = node.get("attributes", {})
        hidden = _node_hidden(attributes)

        if hidden and node.get("type") in {"section", "div", "main"}:
            container = QWidget()
            container.setVisible(False)
            child_layout = QVBoxLayout(container)
            for child_node in node.get("children", []):
                self.generate_interface(child_node, child_layout, in_form=in_form)
            active_layout.addWidget(container)
            return

        node_type = node.get("type")

        if node_type == "button":
            onclick = attributes.get("onclick", "")
            hook_name = onclick.split("(")[0].strip() if onclick else ""
            label = node.get("text") or attributes.get("value") or hook_name or "Button"
            button = QPushButton(label)
            if onclick:
                self._connect_onclick(button, onclick)
            elif attributes.get("data-action") == "play-vlc":
                from navigation import youtube_video_id_from_url

                video_id = attributes.get("data-video-id") or youtube_video_id_from_url(self.source) or ""
                button.clicked.connect(lambda _checked=False, vid=video_id: self.play_youtube_video(vid))
            active_layout.addWidget(button)
            if hidden:
                button.setVisible(False)
            return

        if node_type == "pre":
            block = QLabel(node.get("text", ""))
            block.setWordWrap(True)
            block.setTextInteractionFlags(Qt.TextSelectableByMouse)
            if hidden:
                block.setVisible(False)
            active_layout.addWidget(block)
            return

        super().generate_interface(node, active_layout, in_form=in_form)


def dump_page(target: str, output_path: Path | None = None) -> dict:
    """Fetch a URL or file and write a DOM.json bundle."""
    output = output_path or default_bundle_path()
    return ingest_to_file(prepare_fetch_url(target), output)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fetch pages online, translate JavaScript, and render in Qt.",
    )
    parser.add_argument("url", nargs="?", help="URL or path to open (default: mock mail demo)")
    parser.add_argument(
        "--dump",
        metavar="OUTPUT.json",
        help="Only ingest the page to a JSON bundle and exit",
    )
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Mock server port")
    parser.add_argument("--no-serve", action="store_true", help="Do not start the embedded mock server")
    parser.add_argument("--bookmark", action="store_true", help="Bookmark the opened page")
    parser.add_argument(
        "--mock-search",
        action="store_true",
        help="Use localhost mock search as the default home page",
    )
    args = parser.parse_args()

    server: MockServerThread | None = None
    if not args.no_serve and not args.dump:
        server = MockServerThread(port=args.port)
        try:
            server.start()
        except OSError as exc:
            print(f"Could not start mock server on port {args.port}: {exc}", file=sys.stderr)
            return 1
        enable_mock_search(args.port)

    if args.dump:
        target = args.url or mock_mail_url(args.port)
        bundle = dump_page(target, Path(args.dump))
        print(f"Saved bundle to {Path(args.dump).resolve()} ({bundle.get('title', '')})")
        return 0

    if args.mock_search:
        home = default_home_url()
    elif args.url:
        home = normalize_url(args.url) if not args.url.startswith(("/", "http://", "https://", "file://")) else args.url
        if home.startswith("/"):
            home = f"http://127.0.0.1:{args.port}{home}"
    else:
        home = mock_mail_url(args.port)

    app = QApplication(sys.argv)
    browser = OnlineBrowser()
    try:
        browser.navigate_to(home)
    except ValueError as exc:
        QMessageBox.critical(None, "Navigation", str(exc))
        return 1

    if args.bookmark:
        add_bookmark(browser.bundle_path, browser.source)

    browser.show()
    code = app.exec_()

    if server is not None:
        server.stop()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
