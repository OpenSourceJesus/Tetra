#!/usr/bin/env python3
"""Terminal renderer for DOM.json bundles (Linux and other ANSI terminals)."""

from __future__ import annotations

import json
import re
import subprocess
import sys
import types
import urllib.parse
from dataclasses import dataclass
from html import unescape
from pathlib import Path

from rich.console import Console
from rich.prompt import Prompt

from navigation import (
    is_youtube_watch,
    normalize_url,
    prepare_fetch_url,
    search_query_from_url,
    youtube_video_id_from_url,
)
from sixel import (
    TITLE_FONT_SIZE,
    TextSegment,
    get_mixed_text_sixel,
    get_sixel_preview,
    get_text_sixel,
    heading_font_size,
    TEXT_FONT_SIZE,
)
from store import cache_bundle_path, default_bundle_path
from tui_store import record_search, record_visit
from www2json import ingest_to_file
from video import VideoDownloadError, open_youtube_in_vlc

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
        "form",
    }
)

HEADING_TAGS = frozenset({"h1", "h2", "h3", "h4", "h5", "h6"})

SKIP_SECTION_TITLES = frozenset(
    {
        "references",
        "notes",
        "sources",
        "further reading",
        "external links",
        "see also",
        "bibliography",
        "citations",
        "footnotes",
        "end notes",
    }
)


def is_skipped_section(title: str) -> bool:
    return title.strip().lower() in SKIP_SECTION_TITLES


def heading_level(tag: str) -> int:
    if len(tag) == 2 and tag[0] == "h" and tag[1].isdigit():
        return int(tag[1])
    return 6


@dataclass
class SixelBlock:
    sixel: str
    pixel_height: int
    label: str
    kind: str = "text"
    image_path: Path | None = None


class TuiMessageBox:
    def __init__(self, console: Console):
        self.console = console

    def information(self, _parent, title: str, text: str):
        self.console.print(f"[yellow]{title}:[/] {text}")


class JS2PY_RUNTIME:
    def __init__(self, console: Console):
        self.console = console
        self.functions: dict = {}

    def register_runtime_scripts(self, python_src: str):
        if not python_src or not python_src.strip():
            return
        from www2json import is_runnable_script

        if not is_runnable_script(python_src):
            return

        namespace = {"QMessageBox": TuiMessageBox(self.console)}
        try:
            exec(python_src, namespace)
            self.functions.update(
                {k: v for k, v in namespace.items() if isinstance(v, types.FunctionType)}
            )
        except Exception as exc:
            print(f"Runtime execution compilation error: {exc}", file=sys.stderr)


def strip_html(fragment: str) -> str:
    text = re.sub(r"<br\s*/?>", "\n", fragment, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    return unescape(text).strip()


def extract_links(fragment: str) -> list[tuple[str, str]]:
    links: list[tuple[str, str]] = []
    for match in re.finditer(
        r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',
        fragment,
        flags=re.IGNORECASE | re.DOTALL,
    ):
        href = unescape(match.group(1))
        label = strip_html(match.group(2))
        if label or href:
            links.append((label or href, href))
    return links


def resolve_asset_path(bundle_path: Path, src: str) -> Path:
    candidate = Path(src)
    if candidate.is_absolute():
        return candidate
    return (bundle_path.parent / candidate).resolve()


def launch_image_viewer(image_path: Path) -> None:
    viewer = SCRIPT_DIR / "qt_image_viewer.py"
    subprocess.Popen(
        [sys.executable, str(viewer), str(image_path.resolve())],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def text_block(text: str, *, heading: bool = False, label: str = "", font_size: int | None = None) -> SixelBlock | None:
    plain = strip_html(text)
    if not plain:
        return None
    size = font_size if font_size is not None else (TITLE_FONT_SIZE if heading else TEXT_FONT_SIZE)
    sixel, _width, height = get_text_sixel(plain, font_size=size, bold=heading)
    return SixelBlock(
        sixel=sixel,
        pixel_height=height,
        label=label or plain[:60],
        kind="heading" if heading else "text",
    )


def section_block(
    heading: str | None,
    heading_tag: str | None,
    body_parts: list[str],
) -> SixelBlock | None:
    segments: list[TextSegment] = []
    if heading:
        segments.append(
            TextSegment(
                heading,
                font_size=heading_font_size(heading_tag or "h2"),
                bold=True,
            )
        )
    body = "\n\n".join(part for part in body_parts if part is not None)
    if body.strip():
        segments.append(TextSegment(body, font_size=TEXT_FONT_SIZE, bold=False))
    if not segments:
        return None

    sixel, _width, height = get_mixed_text_sixel(segments)
    label = heading or body[:60]
    return SixelBlock(
        sixel=sixel,
        pixel_height=height,
        label=label,
        kind="section",
    )


class TerminalBrowser:
    def __init__(self, console: Console | None = None):
        self.console = console or Console()
        self.bundle_path = cache_bundle_path(DEFAULT_HOME)
        self.source = DEFAULT_HOME
        self.page_title = ""
        self.render_bundle: dict = {}
        self.runtime = JS2PY_RUNTIME(self.console)
        self.links: list[tuple[str, str]] = []
        self.buttons: list[tuple[str, object]] = []
        self.images: list[tuple[str, Path]] = []
        self.form_fields: dict[str, str] = {}
        self.active_form: dict | None = None
        self.primary_form: dict | None = None
        self._section_heading: str | None = None
        self._section_heading_tag: str | None = None
        self._section_body: list[str] = []
        self._skip_section_level: int | None = None

    def clear_state(self):
        self.links.clear()
        self.buttons.clear()
        self.images.clear()
        self.form_fields.clear()
        self.active_form = None
        self.primary_form = None
        self.runtime = JS2PY_RUNTIME(self.console)
        self._reset_section()

    def _reset_section(self):
        self._section_heading = None
        self._section_heading_tag = None
        self._section_body = []
        self._skip_section_level = None

    def _section_is_skipped(self) -> bool:
        return self._skip_section_level is not None

    def _add_body(self, text: str):
        if self._section_is_skipped():
            return
        plain = strip_html(text).strip()
        if plain:
            self._section_body.append(plain)

    def _begin_heading(self, tag: str, text: str, output: list[SixelBlock | str]):
        self._flush_section(output)
        plain = strip_html(text).strip()
        if not plain:
            return
        level = heading_level(tag)

        if self._skip_section_level is not None:
            if level <= self._skip_section_level:
                if is_skipped_section(plain):
                    self._skip_section_level = level
                else:
                    self._skip_section_level = None
                    self._section_heading = plain
                    self._section_heading_tag = tag
            return

        if is_skipped_section(plain):
            self._skip_section_level = level
            return

        self._section_heading = plain
        self._section_heading_tag = tag

    def _flush_section(self, output: list[SixelBlock | str]):
        if self._section_is_skipped():
            self._section_heading = None
            self._section_heading_tag = None
            self._section_body = []
            return

        block = section_block(self._section_heading, self._section_heading_tag, self._section_body)
        if block:
            output.append(block)
        self._section_heading = None
        self._section_heading_tag = None
        self._section_body = []

    def load_bundle(self, render_bundle: dict, bundle_path: Path):
        self.clear_state()
        self.render_bundle = render_bundle
        self.bundle_path = bundle_path
        self.source = render_bundle.get("source", str(bundle_path))
        self.page_title = render_bundle.get("title", "")
        self.runtime.register_runtime_scripts(render_bundle.get("scripts", ""))

    def navigate_to(self, target: str):
        target = prepare_fetch_url(target)
        self.console.print(f"[dim]Loading {target}...[/]")
        bundle_path = cache_bundle_path(target)
        render_bundle = ingest_to_file(target, bundle_path)
        record_visit(target, bundle_path, viewer="tui")
        if "google.com/search" in target:
            record_search(search_query_from_url(target), target)
        self.load_bundle(render_bundle, bundle_path)
        if is_youtube_watch(target):
            self.play_youtube_video()

    def play_youtube_video(self, video_id: str | None = None):
        video_id = video_id or youtube_video_id_from_url(self.source)
        if not video_id:
            return
        self.console.print(f"[dim]Opening {video_id} in VLC...[/]")
        try:
            _, mode = open_youtube_in_vlc(video_id, self.source)
            if mode == "cache":
                self.console.print("[green]Playing cached video in VLC[/]")
            else:
                self.console.print("[green]Streaming in VLC[/] [dim](caching in background)[/]")
        except Exception as exc:
            self.console.print(f"[red]Video error:[/] {exc}")

    def render_page(self) -> list[SixelBlock | str]:
        pieces: list[SixelBlock | str] = []
        header = self.page_title or Path(self.source).name or "Page"
        header_block = text_block(f"{header}\n{self.source}", heading=True, label=header)
        if header_block:
            pieces.append(header_block)

        if self.render_bundle.get("dom"):
            pieces.extend(self.render_node(self.render_bundle["dom"]))

        self._flush_section(pieces)
        return pieces

    def display(self):
        footer_lines: list[str] = []
        if self.images:
            footer_lines.append(
                "Images: " + ", ".join(f"[i {i}] {label[:30]}" for i, (label, _) in enumerate(self.images, 1))
            )
        if self.buttons:
            footer_lines.append(
                "Buttons: " + ", ".join(f"[b {i}] {label[:30]}" for i, (label, _) in enumerate(self.buttons, 1))
            )
        if self.links:
            footer_lines.append(
                "Links: " + ", ".join(f"[l {i}] {label[:30]}" for i, (label, _) in enumerate(self.links, 1))
            )

        for piece in self.render_page():
            if isinstance(piece, SixelBlock):
                self._print_sixel_block(piece)
            else:
                block = text_block(piece)
                if block:
                    self._print_sixel_block(block)

        if footer_lines:
            sys.stdout.write("\n".join(footer_lines) + "\n")
            sys.stdout.flush()

    def _print_sixel_block(self, block: SixelBlock):
        sys.stdout.write(block.sixel)
        if block.kind == "image" and block.image_path:
            index = next(
                (i for i, (_, path) in enumerate(self.images, 1) if path == block.image_path),
                None,
            )
            hint = f"i {index}" if index else "i"
            sys.stdout.write(f"\n[{hint}] {block.label} — Qt viewer for full image\n")
        else:
            sys.stdout.write("\n")
        sys.stdout.flush()

    def render_node(self, node: dict) -> list[SixelBlock | str]:
        node_type = node.get("type")
        attributes = node.get("attributes", {})
        output: list[SixelBlock | str] = []

        if node_type == "form":
            previous_form = self.active_form
            self.primary_form = node
            self.active_form = node
            for child in node.get("children", []):
                output.extend(self.render_node(child))
            self.active_form = previous_form
            return output

        if node_type == "input":
            input_type = attributes.get("type", "text").lower()
            name = attributes.get("name", "")
            if input_type == "hidden":
                return output
            if input_type in {"submit", "button"}:
                label = attributes.get("value") or name or "Submit"
                self.buttons.append((label, ("submit", name, attributes.get("value", ""))))
                return output
            if input_type in {"text", "search", ""}:
                placeholder = attributes.get("title") or attributes.get("aria-label", "Search")
                default = attributes.get("value", "")
                if name:
                    self.form_fields[name] = default
                self._flush_section(output)
                block = text_block(f"{placeholder}: {default}", label=placeholder)
                if block:
                    output.append(block)
                return output
            return output

        if node_type == "textarea":
            name = attributes.get("name", "")
            default = attributes.get("value", "")
            if name:
                self.form_fields[name] = default
            self._flush_section(output)
            block = text_block(default)
            if block:
                output.append(block)
            return output

        if node_type in STRUCTURAL_TAGS:
            for child in node.get("children", []):
                output.extend(self.render_node(child))
            return output

        if node_type == "br":
            self._add_body("")
            return output

        if node_type == "hr":
            self._add_body("─" * 48)
            return output

        if node_type == "img":
            self._flush_section(output)
            src = attributes.get("src", "")
            alt = attributes.get("alt", "") or src
            image_path = resolve_asset_path(self.bundle_path, src)
            self.images.append((alt, image_path))
            if image_path.exists():
                try:
                    sixel, _width, height = get_sixel_preview(image_path)
                    output.append(
                        SixelBlock(
                            sixel=sixel,
                            pixel_height=height,
                            label=alt,
                            kind="image",
                            image_path=image_path,
                        )
                    )
                except Exception as exc:
                    self._flush_section(output)
                    block = text_block(f"[image: {alt}] ({exc})")
                    if block:
                        output.append(block)
            else:
                self._flush_section(output)
                block = text_block(f"[image: {alt}]")
                if block:
                    output.append(block)
            return output

        if node_type == "figure":
            for child in node.get("children", []):
                output.extend(self.render_node(child))
            return output

        if node_type in {"ul", "ol"}:
            for index, child in enumerate(node.get("children", []), start=1):
                if child.get("type") != "li":
                    output.extend(self.render_node(child))
                    continue
                prefix = f"{index}. " if node_type == "ol" else "• "
                text = child.get("html") or child.get("text", "")
                self._add_body(prefix + strip_html(text))
                for nested in child.get("children", []):
                    output.extend(self.render_node(nested))
            return output

        if node_type == "table":
            for row in self.collect_table_rows(node):
                cells = [strip_html(cell.get("html") or cell.get("text", "")) for cell in row]
                self._add_body(" | ".join(cells))
            return output

        if node_type == "button":
            label = node.get("text", "button")
            if attributes.get("data-action") == "play-vlc":
                video_id = attributes.get("data-video-id", "")
                self.buttons.append((label, ("play-vlc", video_id)))
            else:
                onclick = attributes.get("onclick", "")
                hook_name = onclick.split("(")[0].strip()
                callback = self.runtime.functions.get(hook_name)
                self.buttons.append((label, callback))
            self._flush_section(output)
            block = text_block(f"[button] {label}")
            if block:
                output.append(block)
            return output

        if node_type in HEADING_TAGS:
            text = node.get("html") or node.get("text", "")
            self._begin_heading(node_type, text, output)
            return output

        if node_type in {"p", "span", "figcaption", "blockquote", "cite", "dt", "dd"}:
            text = node.get("html") or node.get("text", "")
            if text:
                plain = strip_html(text)
                if plain:
                    self._add_body(plain)
                for label, href in extract_links(text):
                    self.links.append((label, href))
            return output

        if node_type == "a":
            if node.get("children"):
                for child in node.get("children", []):
                    output.extend(self.render_node(child))
                return output
            text = strip_html(node.get("html") or node.get("text", ""))
            href = attributes.get("href", "")
            if text or href:
                if href:
                    self.links.append((text or href, href))
                self._add_body(text or href)
            return output

        block_children = [
            child
            for child in node.get("children", [])
            if child.get("type") not in {"#text", "css-rule", "css-property"}
        ]
        if block_children and node_type not in {"ul", "ol", "table", "figure", "img"}:
            for child in block_children:
                output.extend(self.render_node(child))
        return output

    def collect_table_rows(self, node: dict) -> list[list[dict]]:
        rows: list[list[dict]] = []

        def walk_table(table_node: dict):
            for child in table_node.get("children", []):
                ctype = child.get("type")
                if ctype == "tr":
                    row_cells = [
                        cell
                        for cell in child.get("children", [])
                        if cell.get("type") in {"td", "th"}
                    ]
                    if row_cells:
                        rows.append(row_cells)
                elif ctype in {"tbody", "thead", "tfoot"}:
                    walk_table(child)

        walk_table(node)
        return rows

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
        action_url = urllib.parse.urljoin(self.source, action or self.source)
        params = dict(self.form_fields)
        if submit_name:
            params[submit_name] = submit_value if submit_value is not None else submit_name
        target = action_url + ("&" if "?" in action_url else "?") + urllib.parse.urlencode(params)
        self.navigate_to(target)
        self.display()

    def activate_button(self, index: int) -> bool:
        if index < 1 or index > len(self.buttons):
            return False
        label, action = self.buttons[index - 1]
        if isinstance(action, tuple) and action[0] == "submit":
            _, submit_name, submit_value = action
            self.submit_form(submit_name, submit_value)
            return True
        if isinstance(action, tuple) and action[0] == "play-vlc":
            _, video_id = action
            self.play_youtube_video(video_id or None)
            return True
        if callable(action):
            self.console.print(f"[dim]Button:[/] {label}")
            action()
            return True
        return False

    def open_image(self, index: int) -> bool:
        if index < 1 or index > len(self.images):
            return False
        _, image_path = self.images[index - 1]
        if image_path.exists():
            launch_image_viewer(image_path)
            return True
        self.console.print(f"[red]Missing image:[/] {image_path}")
        return False

    def follow_link(self, index: int) -> bool:
        if index < 1 or index > len(self.links):
            return False
        _, href = self.links[index - 1]
        if href.startswith("//"):
            href = "https:" + href
        target = urllib.parse.urljoin(self.source, href)
        self.navigate_to(target)
        self.display()
        return True

    def run_interactive(self):
        self.display()
        help_text = (
            "[dim]Commands: [/][bold]go <url|search>[/]  "
            "[bold]b/i/l <n>[/]  [bold]home[/]  [bold]q[/] quit"
        )
        while True:
            self.console.print(help_text)
            try:
                command = Prompt.ask("browse").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not command:
                continue
            if command in {"q", "quit", "exit"}:
                break
            if command == "home":
                self.navigate_to(DEFAULT_HOME)
                self.display()
                continue
            if command.startswith("go "):
                try:
                    self.navigate_to(normalize_url(command[3:].strip()))
                    self.display()
                except ValueError as exc:
                    self.console.print(f"[red]{exc}[/]")
                continue
            if command.startswith("b "):
                try:
                    if not self.activate_button(int(command.split(maxsplit=1)[1])):
                        self.console.print("[red]Invalid button number[/]")
                    else:
                        self.display()
                except (IndexError, ValueError):
                    self.console.print("[red]Usage: b <number>[/]")
                continue
            if command.startswith("i "):
                try:
                    if not self.open_image(int(command.split(maxsplit=1)[1])):
                        self.console.print("[red]Invalid image number[/]")
                except (IndexError, ValueError):
                    self.console.print("[red]Usage: i <number>[/]")
                continue
            if command.startswith("l "):
                try:
                    if not self.follow_link(int(command.split(maxsplit=1)[1])):
                        self.console.print("[red]Invalid link number[/]")
                except (IndexError, ValueError):
                    self.console.print("[red]Usage: l <number>[/]")
                continue
            try:
                self.navigate_to(normalize_url(command))
                self.display()
            except ValueError as exc:
                self.console.print(f"[red]{exc}[/]")


def render_bundle_to_string(render_bundle: dict, bundle_path: Path) -> str:
    console = Console(width=100, record=True)
    browser = TerminalBrowser(console)
    browser.load_bundle(render_bundle, bundle_path)
    lines: list[str] = []
    for piece in browser.render_page():
        if isinstance(piece, SixelBlock):
            lines.append(f"[sixel:{piece.kind}] {piece.label}")
        else:
            lines.append(strip_html(piece))
    return "\n".join(lines)


def main():
    args = sys.argv[1:]
    online = False
    if "--online" in args:
        online = True
        args.remove("--online")
    interactive = "--interactive" in args or sys.stdout.isatty()
    if "--interactive" in args:
        args.remove("--interactive")
    if "--plain" in args:
        interactive = False
        args.remove("--plain")

    browser = TerminalBrowser()

    if online:
        browser.navigate_to(DEFAULT_HOME)
    elif args:
        bundle_path = Path(args[0])
        render_bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
        record_visit(render_bundle.get("source", str(bundle_path)), bundle_path, viewer="tui")
        browser.load_bundle(render_bundle, bundle_path)
    else:
        bundle_path = cache_bundle_path(DEFAULT_HOME)
        if not bundle_path.exists():
            bundle_path = default_bundle_path()
        if not bundle_path.exists():
            print("Error: no bundle found. Run www2json.py or use --online.", file=sys.stderr)
            sys.exit(1)
        render_bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
        record_visit(render_bundle.get("source", str(bundle_path)), bundle_path, viewer="tui")
        browser.load_bundle(render_bundle, bundle_path)

    if interactive:
        browser.run_interactive()
    else:
        browser.display()


if __name__ == "__main__":
    main()
