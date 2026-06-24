#!/usr/bin/env python3
"""Offline PyQt5 renderer for DOM.json bundles."""

import json
import sys
import types
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from navigation import google_search_url, normalize_url, prepare_fetch_url, youtube_search_url
from store import (
    BOOKMARKS_FILE,
    HISTORY_FILE,
    cache_bundle_path,
    default_bundle_path,
)
from www2json import ingest_to_file

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_HOME = "https://www.google.com/?gbv=1"

STRUCTURAL_TAGS = frozenset(
    {
        "html",
        "head",
        "body",
        "div",
        "style",
        "css-rule",
        "css-property",
        "tbody",
        "thead",
        "tfoot",
        "colgroup",
        "col",
        "table",
        "tr",
        "td",
        "th",
    }
)

HEADING_STYLES = {
    "h1": "font-size: 24px; font-weight: bold; margin: 12px 0 8px 0;",
    "h2": "font-size: 20px; font-weight: bold; margin: 14px 0 6px 0;",
    "h3": "font-size: 17px; font-weight: bold; margin: 12px 0 4px 0;",
    "h4": "font-size: 15px; font-weight: bold; margin: 10px 0 4px 0;",
    "h5": "font-size: 14px; font-weight: bold; margin: 8px 0 2px 0;",
    "h6": "font-size: 13px; font-weight: bold; margin: 8px 0 2px 0;",
}


class JS2PY_RUNTIME:
    def __init__(self):
        self.functions: dict = {}

    def register_runtime_scripts(self, python_src: str):
        if not python_src or not python_src.strip():
            return
        from www2json import is_runnable_script

        if not is_runnable_script(python_src):
            return

        namespace: dict = {}
        try:
            exec(python_src, namespace)
            self.functions.update(
                {k: v for k, v in namespace.items() if isinstance(v, types.FunctionType)}
            )
        except Exception as exc:
            print(f"Runtime execution compilation error: {exc}", file=sys.stderr)


def load_json_list(path: Path) -> list:
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []


def save_json_list(path: Path, items: list):
    path.write_text(json.dumps(items, indent=2), encoding="utf-8")


def record_history(bundle_path: Path, source: str):
    history = load_json_list(HISTORY_FILE)
    entry = {"json": str(bundle_path.resolve()), "source": source}
    history = [item for item in history if item.get("json") != entry["json"]]
    history.insert(0, entry)
    save_json_list(HISTORY_FILE, history[:50])


def add_bookmark(bundle_path: Path, source: str):
    bookmarks = load_json_list(BOOKMARKS_FILE)
    entry = {"json": str(bundle_path.resolve()), "source": source}
    if entry not in bookmarks:
        bookmarks.append(entry)
        save_json_list(BOOKMARKS_FILE, bookmarks)


def resolve_asset_path(bundle_path: Path, src: str) -> Path:
    candidate = Path(src)
    if candidate.is_absolute():
        return candidate
    return (bundle_path.parent / candidate).resolve()


class SafeOfflineBrowser(QMainWindow):
    def __init__(self, render_bundle: dict | None = None, bundle_path: Path | None = None):
        super().__init__()
        self.bundle_path = bundle_path or default_bundle_path()
        self.source = render_bundle.get("source", str(self.bundle_path)) if render_bundle else DEFAULT_HOME
        self.page_title = render_bundle.get("title", "") if render_bundle else ""
        self.runtime = JS2PY_RUNTIME()
        self.form_fields: dict[str, QLineEdit | Path] = {}
        self._file_previews: dict[str, QLabel] = {}
        self.active_form: dict | None = None
        self.primary_form: dict | None = None
        self._back_stack: list[tuple[str, Path]] = []
        self._forward_stack: list[tuple[str, Path]] = []
        self._page_loaded = False

        root = QWidget()
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.addWidget(self.build_toolbar())

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.content = QWidget()
        self.base_layout = QVBoxLayout(self.content)
        self.base_layout.setAlignment(Qt.AlignTop)
        self.scroll.setWidget(self.content)
        root_layout.addWidget(self.scroll)

        self.setCentralWidget(root)
        self.resize(920, 760)

        if render_bundle is not None:
            self.load_bundle(render_bundle, self.bundle_path)
        else:
            self.navigate_to(DEFAULT_HOME)

    def build_toolbar(self) -> QWidget:
        bar = QWidget()
        layout = QHBoxLayout(bar)

        nav_button_size = 25
        self.back_button = QPushButton("<")
        self.back_button.setFixedSize(nav_button_size, nav_button_size)
        self.back_button.clicked.connect(self.go_back)
        layout.addWidget(self.back_button)

        self.forward_button = QPushButton(">")
        self.forward_button.setFixedSize(nav_button_size, nav_button_size)
        self.forward_button.clicked.connect(self.go_forward)
        layout.addWidget(self.forward_button)

        home_button = QPushButton("Home")
        home_button.clicked.connect(lambda: self.navigate_to(DEFAULT_HOME))
        layout.addWidget(home_button)

        self.url_bar = QLineEdit()
        self.url_bar.setPlaceholderText("Search or enter URL")
        self.url_bar.returnPressed.connect(self.on_url_submit)
        layout.addWidget(self.url_bar, stretch=1)

        go_button = QPushButton("Go")
        go_button.clicked.connect(self.on_url_submit)
        layout.addWidget(go_button)

        self.status_label = QLabel("")
        layout.addWidget(self.status_label)
        self._update_nav_buttons()
        return bar

    def _update_nav_buttons(self):
        self.back_button.setEnabled(bool(self._back_stack))
        self.forward_button.setEnabled(bool(self._forward_stack))

    def _current_entry(self) -> tuple[str, Path]:
        return self.source, self.bundle_path

    def go_back(self):
        if not self._back_stack:
            return
        self._forward_stack.append(self._current_entry())
        source, bundle_path = self._back_stack.pop()
        self._load_entry(source, bundle_path)
        self._update_nav_buttons()

    def go_forward(self):
        if not self._forward_stack:
            return
        self._back_stack.append(self._current_entry())
        source, bundle_path = self._forward_stack.pop()
        self._load_entry(source, bundle_path)
        self._update_nav_buttons()

    def on_url_submit(self):
        text = self.url_bar.text().strip()
        if not text:
            return
        try:
            self.navigate_to(normalize_url(text))
        except ValueError as exc:
            QMessageBox.warning(self, "Navigation", str(exc))

    def clear_content(self):
        while self.base_layout.count():
            item = self.base_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self.form_fields.clear()
        self._file_previews.clear()
        self.active_form = None
        self.primary_form = None
        self.runtime = JS2PY_RUNTIME()

    def load_bundle(self, render_bundle: dict, bundle_path: Path):
        self.clear_content()
        self.bundle_path = bundle_path
        self.source = render_bundle.get("source", str(bundle_path))
        self.page_title = render_bundle.get("title", "")
        self.url_bar.setText(self.source)
        self.runtime.register_runtime_scripts(render_bundle.get("scripts", ""))

        if self.page_title and "google-home" not in json.dumps(render_bundle.get("dom", {})):
            title_label = QLabel(self.page_title)
            title_label.setStyleSheet(HEADING_STYLES["h1"])
            title_label.setWordWrap(True)
            self.base_layout.addWidget(title_label)

        if render_bundle.get("dom"):
            self.generate_interface(render_bundle["dom"], self.base_layout)

        window_title = self.page_title or "Offline Browser"
        self.setWindowTitle(f"{window_title} — {self.source}")
        self.status_label.setText("Ready")
        self._page_loaded = True
        self._update_nav_buttons()

    def _load_entry(self, source: str, bundle_path: Path):
        self.status_label.setText("Loading...")
        QApplication.processEvents()
        try:
            render_bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            self.navigate_to(source, push_history=False)
            return
        except json.JSONDecodeError as exc:
            self.status_label.setText("Error")
            QMessageBox.critical(
                self,
                "Navigation error",
                f"Cached page is invalid:\n{bundle_path}\n\n{exc}",
            )
            return
        self.load_bundle(render_bundle, bundle_path)

    def navigate_to(self, target: str, push_history: bool = True):
        target = prepare_fetch_url(target)
        if push_history and self._page_loaded:
            self._back_stack.append(self._current_entry())
            self._forward_stack.clear()

        self.status_label.setText("Loading...")
        QApplication.processEvents()

        bundle_path = cache_bundle_path(target)
        try:
            render_bundle = ingest_to_file(target, bundle_path)
        except Exception as exc:
            self.status_label.setText("Error")
            if push_history and self._back_stack:
                self._back_stack.pop()
            self._update_nav_buttons()
            QMessageBox.critical(self, "Navigation error", f"Failed to load:\n{target}\n\n{exc}")
            return

        record_history(bundle_path, target)
        self.load_bundle(render_bundle, bundle_path)

    def make_text_label(self, node: dict, default_style: str = "") -> QLabel:
        label = QLabel()
        label.setWordWrap(True)
        label.setTextInteractionFlags(
            Qt.TextSelectableByMouse | Qt.LinksAccessibleByMouse
        )
        label.setOpenExternalLinks(False)
        label.linkActivated.connect(self.on_link_clicked)
        rich = node.get("html") or node.get("text", "")
        label.setText(rich)
        if default_style:
            label.setStyleSheet(default_style)
        return label

    def on_link_clicked(self, link: str):
        if link.startswith(("http://", "https://", "//")):
            if link.startswith("//"):
                link = "https:" + link
            self.navigate_to(link)
            return
        absolute = urllib.parse.urljoin(self.source, link)
        self.navigate_to(absolute)

    def build_search_url(self, query: str, input_name: str) -> str:
        parsed = urllib.parse.urlparse(self.source)
        host = parsed.netloc.lower()
        if "youtube.com" in host or input_name == "search_query":
            return youtube_search_url(query)
        if input_name == "q" or "google.com" in host:
            return google_search_url(query)
        return normalize_url(query)

    def submit_standalone_search(self, field: QLineEdit, input_name: str):
        query = field.text().strip()
        if not query:
            return
        self.navigate_to(self.build_search_url(query, input_name))

    def submit_form(
        self,
        submit_name: str | None = None,
        submit_value: str | None = None,
        form: dict | None = None,
    ):
        form = form or self.active_form or self.primary_form
        if form is None:
            return

        action = form.get("attributes", {}).get("action", "")
        method = form.get("attributes", {}).get("method", "get").lower()
        action_url = urllib.parse.urljoin(self.source, action or self.source)

        params: dict[str, str] = {}
        for name, field in self.form_fields.items():
            if isinstance(field, QLineEdit):
                params[name] = field.text()

        if submit_name:
            params[submit_name] = submit_value if submit_value is not None else submit_name

        if "multipart/form-data" in form.get("attributes", {}).get("enctype", "").lower():
            self._submit_multipart_form(action_url, submit_name, submit_value)
            return

        if method == "post":
            query = urllib.parse.urlencode(params)
            target = action_url
        else:
            target = action_url + ("&" if "?" in action_url else "?") + urllib.parse.urlencode(params)

        self.navigate_to(target)

    def _submit_multipart_form(
        self,
        action_url: str,
        submit_name: str | None = None,
        submit_value: str | None = None,
    ):
        boundary = f"----OfflineBrowser{uuid.uuid4().hex}"
        chunks: list[bytes] = []

        for name, field in self.form_fields.items():
            if isinstance(field, Path):
                chunks.extend(
                    [
                        f"--{boundary}\r\n".encode(),
                        (
                            f'Content-Disposition: form-data; name="{name}"; '
                            f'filename="{field.name}"\r\n'
                        ).encode(),
                        b"Content-Type: application/octet-stream\r\n\r\n",
                        field.read_bytes(),
                        b"\r\n",
                    ]
                )
            else:
                chunks.extend(
                    [
                        f"--{boundary}\r\n".encode(),
                        f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
                        field.text().encode("utf-8"),
                        b"\r\n",
                    ]
                )

        if submit_name:
            value = submit_value if submit_value is not None else submit_name
            chunks.extend(
                [
                    f"--{boundary}\r\n".encode(),
                    f'Content-Disposition: form-data; name="{submit_name}"\r\n\r\n'.encode(),
                    value.encode("utf-8"),
                    b"\r\n",
                ]
            )

        chunks.append(f"--{boundary}--\r\n".encode())
        body = b"".join(chunks)
        request = urllib.request.Request(
            action_url,
            data=body,
            method="POST",
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                final_url = response.geturl()
        except Exception as exc:
            QMessageBox.critical(self, "Upload error", str(exc))
            return
        self.navigate_to(final_url)

    def generate_interface(self, node: dict, active_layout: QVBoxLayout, in_form: bool = False):
        node_type = node.get("type")
        attributes = node.get("attributes", {})

        if node_type == "form":
            previous_form = self.active_form
            self.primary_form = node
            self.active_form = node
            for child_node in node.get("children", []):
                self.generate_interface(child_node, active_layout, in_form=True)
            self.active_form = previous_form
            return

        if node_type == "input":
            input_type = attributes.get("type", "text").lower()
            name = attributes.get("name", "")
            if input_type == "hidden":
                return
            if input_type in {"submit", "button"}:
                form_ref = self.active_form or self.primary_form
                button = QPushButton(attributes.get("value") or name or "Submit")
                button.clicked.connect(
                    lambda _checked=False, submit=name, value=attributes.get("value", ""), form=form_ref:
                    self.submit_form(submit, value, form=form)
                )
                active_layout.addWidget(button)
                return
            if input_type in {"text", "search", ""}:
                field = QLineEdit(attributes.get("value", ""))
                field.setPlaceholderText(attributes.get("title") or attributes.get("aria-label", "Search"))
                if name:
                    self.form_fields[name] = field
                if in_form and (self.active_form or self.primary_form):
                    form_ref = self.active_form or self.primary_form
                    field.returnPressed.connect(
                        lambda form=form_ref: self.submit_form(form=form)
                    )
                else:
                    field.returnPressed.connect(
                        lambda fname=name, f=field: self.submit_standalone_search(f, fname)
                    )
                active_layout.addWidget(field)
                return
            if input_type == "file":
                row = QWidget()
                row_layout = QHBoxLayout(row)
                choose = QPushButton(attributes.get("value") or "Choose file...")
                preview = QLabel()
                preview.setAlignment(Qt.AlignLeft)

                def pick_file(field_name=name, preview_label=preview):
                    path, _ = QFileDialog.getOpenFileName(
                        self,
                        "Choose image",
                        "",
                        "Images (*.png *.jpg *.jpeg *.gif *.webp)",
                    )
                    if not path:
                        return
                    file_path = Path(path)
                    self.form_fields[field_name] = file_path
                    preview_label.setText(file_path.name)
                    pixmap = QPixmap(str(file_path))
                    if not pixmap.isNull():
                        preview_label.setPixmap(
                            pixmap.scaledToWidth(160, Qt.SmoothTransformation)
                        )

                choose.clicked.connect(pick_file)
                row_layout.addWidget(choose)
                row_layout.addWidget(preview, stretch=1)
                active_layout.addWidget(row)
                if name:
                    self._file_previews[name] = preview
                return
            return

        if node_type == "textarea":
            name = attributes.get("name", "")
            field = QLineEdit(attributes.get("value", ""))
            if name:
                self.form_fields[name] = field
            if in_form and (self.active_form or self.primary_form):
                form_ref = self.active_form or self.primary_form
                field.returnPressed.connect(
                    lambda form=form_ref: self.submit_form(form=form)
                )
            else:
                field.returnPressed.connect(
                    lambda fname=name, f=field: self.submit_standalone_search(f, fname)
                )
            active_layout.addWidget(field)
            return

        if node_type in STRUCTURAL_TAGS:
            for child_node in node.get("children", []):
                self.generate_interface(child_node, active_layout, in_form=in_form)
            return

        if node_type == "br":
            active_layout.addWidget(QLabel(""))
            return

        if node_type == "hr":
            line = QLabel()
            line.setFixedHeight(1)
            line.setStyleSheet("background-color: #ccc; margin: 8px 0;")
            active_layout.addWidget(line)
            return

        if node_type == "img":
            src = attributes.get("src", "")
            image_path = resolve_asset_path(self.bundle_path, src)
            image_label = QLabel()
            if image_path.exists():
                pixmap = QPixmap(str(image_path))
                if not pixmap.isNull():
                    max_width = 640
                    if pixmap.width() > max_width:
                        pixmap = pixmap.scaledToWidth(max_width, Qt.SmoothTransformation)
                    image_label.setPixmap(pixmap)
                else:
                    image_label.setText(f"[image: {attributes.get('alt', src)}]")
            else:
                image_label.setText(f"[missing image: {src}]")
            image_label.setAlignment(Qt.AlignLeft)
            active_layout.addWidget(image_label)
            return

        if node_type == "figure":
            figure_layout = QVBoxLayout()
            figure_widget = QWidget()
            figure_widget.setLayout(figure_layout)
            for child_node in node.get("children", []):
                self.generate_interface(child_node, figure_layout, in_form=in_form)
            active_layout.addWidget(figure_widget)
            return

        if node_type in {"ul", "ol"}:
            for index, child_node in enumerate(node.get("children", []), start=1):
                if child_node.get("type") != "li":
                    self.generate_interface(child_node, active_layout, in_form=in_form)
                    continue
                prefix = f"{index}. " if node_type == "ol" else "• "
                item_label = self.make_text_label(child_node)
                item_label.setText(
                    prefix + (child_node.get("html") or child_node.get("text", ""))
                )
                item_label.setContentsMargins(18, 0, 0, 0)
                active_layout.addWidget(item_label)
                for nested in child_node.get("children", []):
                    nested_layout = QVBoxLayout()
                    nested_layout.setContentsMargins(24, 0, 0, 0)
                    nested_widget = QWidget()
                    nested_widget.setLayout(nested_layout)
                    self.generate_interface(nested, nested_layout, in_form=in_form)
                    active_layout.addWidget(nested_widget)
            return

        if node_type == "table":
            self.render_table(node, active_layout)
            return

        allocated_widget = None

        if node_type == "button":
            allocated_widget = QPushButton(node.get("text", ""))
            onclick = attributes.get("onclick", "")
            hook_name = onclick.split("(")[0].strip()
            callback_target = self.runtime.functions.get(hook_name)
            if callback_target:
                allocated_widget.clicked.connect(callback_target)

        elif node_type in HEADING_STYLES:
            allocated_widget = self.make_text_label(node, HEADING_STYLES[node_type])

        elif node_type in {"p", "span", "figcaption", "blockquote", "cite", "dt", "dd"}:
            style = "margin: 4px 0;" if node_type == "p" else ""
            if node_type == "blockquote":
                style = "margin: 8px 0; padding-left: 12px; border-left: 3px solid #ccc;"
            allocated_widget = self.make_text_label(node, style)

        if node_type == "a":
            if node.get("children"):
                for child_node in node.get("children", []):
                    self.generate_interface(child_node, active_layout, in_form=in_form)
                return
            if node.get("text") or node.get("html"):
                allocated_widget = self.make_text_label(node, "color: #0645ad;")
                active_layout.addWidget(allocated_widget)
            return

        if allocated_widget is not None:
            active_layout.addWidget(allocated_widget)

        if node_type == "a":
            return

        block_children = [
            child
            for child in node.get("children", [])
            if child.get("type") not in {"#text", "css-rule", "css-property"}
        ]
        if block_children and node_type not in {"ul", "ol", "table", "figure", "img", "form"}:
            for child_node in block_children:
                self.generate_interface(child_node, active_layout, in_form=in_form)

    def render_table(self, node: dict, active_layout: QVBoxLayout):
        rows = self.collect_table_rows(node)
        if not rows:
            return

        column_count = max(len(row) for row in rows)
        table = QTableWidget(len(rows), column_count)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setWordWrap(True)
        table.horizontalHeader().setStretchLastSection(True)
        table.verticalHeader().setVisible(False)

        for row_index, row in enumerate(rows):
            for col_index, cell in enumerate(row):
                text = cell.get("html") or cell.get("text", "")
                table.setItem(
                    row_index,
                    col_index,
                    QTableWidgetItem(text.replace("<br/>", "\n")),
                )

        table.resizeRowsToContents()
        active_layout.addWidget(table)

    def collect_table_rows(self, node: dict) -> list[list[dict]]:
        rows: list[list[dict]] = []

        def walk_table(table_node: dict):
            for child in table_node.get("children", []):
                ctype = child.get("type")
                if ctype == "tr":
                    row_cells = []
                    for cell in child.get("children", []):
                        if cell.get("type") in {"td", "th"}:
                            row_cells.append(cell)
                    if row_cells:
                        rows.append(row_cells)
                elif ctype in {"tbody", "thead", "tfoot"}:
                    walk_table(child)

        walk_table(node)
        return rows


def main():
    args = sys.argv[1:]
    bookmark = False
    start_online = False
    if "--bookmark" in args:
        bookmark = True
        args.remove("--bookmark")
    if "--online" in args:
        start_online = True
        args.remove("--online")

    app = QApplication(sys.argv)

    if start_online or not args:
        browser = SafeOfflineBrowser()
    else:
        bundle_path = Path(args[0])
        render_bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
        source = render_bundle.get("source", str(bundle_path))
        record_history(bundle_path, source)
        if bookmark:
            add_bookmark(bundle_path, source)
        browser = SafeOfflineBrowser(render_bundle, bundle_path)

    browser.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
