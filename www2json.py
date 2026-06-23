#!/usr/bin/env python3
"""Fetch or load HTML, compile scripts, and serialize the DOM to DOM.json."""

import hashlib
import json
import re
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path

from html_parse import (
    SKIP_TAGS,
    extract_page_content,
    extract_title,
    flatten_text,
    inline_html,
    iter_nodes,
    parse_html,
)
from navigation import BROWSER_UA, prepare_fetch_url
from search import build_google_search_dom, google_html_has_results

SCRIPT_DIR = Path(__file__).resolve().parent
JS2QT = SCRIPT_DIR / "js2qt.py"

TEXT_TAGS = frozenset(
    {
        "button",
        "p",
        "span",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "figcaption",
        "li",
        "th",
        "td",
        "caption",
        "title",
        "a",
    }
)

INLINE_TAGS = frozenset({"b", "strong", "i", "em", "sup", "sub", "abbr", "span", "a"})
PHRASING_CONTAINERS = frozenset(
    {
        "p",
        "span",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "a",
        "button",
        "figcaption",
        "label",
        "li",
        "th",
        "td",
        "cite",
        "dt",
        "dd",
        "blockquote",
    }
)

BLOCK_SKIP_CLASSES = frozenset(
    {
        "navbox",
        "vertical-navbox",
        "metadata",
        "ambox",
        "mbox-small",
        "noprint",
        "mw-editsection",
        "reference",
        "mw-references-wrap",
        "reflist",
        "refbegin",
        "navbox-inner",
        "sidebar",
        "toc",
        "mw-jump-link",
    }
)


def load_html(target: str) -> str:
    fetch_target = prepare_fetch_url(target) if target.startswith("http") else target
    if fetch_target.startswith("http://") or fetch_target.startswith("https://"):
        req = urllib.request.Request(fetch_target, headers={"User-Agent": BROWSER_UA})
        with urllib.request.urlopen(req, timeout=30) as response:
            return response.read().decode("utf-8", errors="replace")
    return Path(fetch_target).read_text(encoding="utf-8")


def compile_javascript(js_payload: str) -> str:
    process = subprocess.run(
        [sys.executable, str(JS2QT)],
        input=js_payload,
        capture_output=True,
        text=True,
        check=False,
    )
    if process.returncode != 0:
        print(f"Compilation warning: {process.stderr.strip()}", file=sys.stderr)
        return ""
    return sanitize_compiled_python(process.stdout)


def sanitize_compiled_python(python_src: str) -> str:
    """Drop untranslatable JS fragments that would fail at runtime."""
    if not python_src.strip():
        return ""

    kept: list[str] = []
    for line in python_src.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if re.match(r"None\s*\(", stripped):
            continue
        if re.match(r"None\.[\w.]+\s*\(", stripped):
            continue
        if re.search(r"=\s*None\.[\w.]+\s*\(", stripped):
            continue
        if re.search(r"=\s*None\s*\(", stripped):
            continue
        kept.append(line)

    result = "\n".join(kept)
    if not result.strip():
        return ""

    try:
        compile(result, "<scripts>", "exec")
    except SyntaxError:
        return ""

    return result


def parse_css_rules(css_text: str) -> list[dict]:
    rules = []
    cleaned = re.sub(r"/\*.*?\*/", "", css_text, flags=re.DOTALL)
    for block in cleaned.split("}"):
        if "{" not in block:
            continue
        selector, declarations = block.split("{", 1)
        selector = selector.strip()
        if not selector:
            continue
        properties = []
        for decl in declarations.split(";"):
            decl = decl.strip()
            if not decl or ":" not in decl:
                continue
            name, value = decl.split(":", 1)
            properties.append(
                {
                    "type": "css-property",
                    "name": name.strip(),
                    "value": value.strip(),
                }
            )
        if properties:
            rules.append(
                {
                    "type": "css-rule",
                    "selector": selector,
                    "children": properties,
                }
            )
    return rules


def should_skip_node(node: dict) -> bool:
    if node.get("type") in SKIP_TAGS | {"style", "meta", "link"}:
        return True
    if node.get("type") == "input":
        input_type = node.get("attributes", {}).get("type", "text").lower()
        return input_type == "hidden"
    attrs = node.get("attributes", {})
    class_attr = attrs.get("class", "")
    classes = set(class_attr.split())
    if classes & BLOCK_SKIP_CLASSES:
        return True
    if attrs.get("role") == "navigation":
        return True
    style = attrs.get("style", "")
    if "display:none" in style.replace(" ", "").lower():
        return True
    return False


def resolve_url(url: str, base_url: str) -> str:
    if url.startswith("//"):
        return "https:" + url
    return urllib.parse.urljoin(base_url, url)


def download_asset(url: str, base_url: str, assets_dir: Path, bundle_dir: Path) -> str | None:
    absolute = resolve_url(url, base_url)
    try:
        req = urllib.request.Request(absolute, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as response:
            data = response.read()
            content_type = response.headers.get("Content-Type", "")
    except Exception as exc:
        print(f"Asset warning ({absolute}): {exc}", file=sys.stderr)
        return None

    parsed = urllib.parse.urlparse(absolute)
    suffix = Path(parsed.path).suffix.lower()
    if suffix not in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ico"}:
        content_type = response.headers.get("Content-Type", "")
        if "png" in content_type:
            suffix = ".png"
        elif "jpeg" in content_type or "jpg" in content_type:
            suffix = ".jpg"
        elif "gif" in content_type:
            suffix = ".gif"
        elif "webp" in content_type:
            suffix = ".webp"
        elif "svg" in content_type:
            suffix = ".svg"
        else:
            suffix = ".bin"

    digest = hashlib.sha256(absolute.encode("utf-8")).hexdigest()[:16]
    assets_dir.mkdir(parents=True, exist_ok=True)
    local_path = (assets_dir / f"{digest}{suffix}").resolve()
    if not local_path.exists():
        local_path.write_bytes(data)
    return str(local_path.relative_to(bundle_dir))


def localize_assets(node: dict, base_url: str, assets_dir: Path, bundle_dir: Path) -> None:
    if node.get("type") == "img":
        src = node.get("attributes", {}).get("src")
        if src:
            local = download_asset(src, base_url, assets_dir, bundle_dir)
            if local:
                node["attributes"]["src_original"] = src
                node["attributes"]["src"] = local
    for child in node.get("children", []):
        localize_assets(child, base_url, assets_dir, bundle_dir)


def serialize_dom(node: dict | None) -> dict | None:
    if node is None:
        return None

    if node.get("type") == "#text":
        text = node.get("text", "")
        if not text.strip():
            return None
        return {"type": "#text", "text": text}

    node_type = node.get("type")
    if node_type in {"#document", "html", "head", "body"}:
        children = []
        for child in node.get("children", []):
            serialized = serialize_dom(child)
            if serialized:
                children.append(serialized)
        if not children:
            return None
        if len(children) == 1:
            return children[0]
        return {"type": "div", "attributes": {}, "children": children}

    if should_skip_node(node):
        return None

    element_meta: dict = {
        "type": node_type,
        "attributes": dict(node.get("attributes", {})),
        "children": [],
    }

    inline_parts: list[str] = []
    block_children: list[dict] = []
    allows_inline = node_type in PHRASING_CONTAINERS

    for child in node.get("children", []):
        if child.get("type") == "#text":
            text = child.get("text", "")
            if text.strip() or (text and allows_inline):
                inline_parts.append(text)
            continue

        child_type = child.get("type")
        if allows_inline and child_type in INLINE_TAGS:
            serialized = serialize_dom(child)
            if serialized:
                if serialized["type"] == "#text":
                    inline_parts.append(serialized["text"])
                else:
                    inline_parts.append(flatten_text(child))
            continue

        serialized = serialize_dom(child)
        if serialized:
            block_children.append(serialized)

    if inline_parts and allows_inline:
        element_meta["text"] = "".join(inline_parts).strip()
        element_meta["html"] = inline_html(node)

    element_meta["children"] = block_children
    if node_type in PHRASING_CONTAINERS and element_meta.get("text"):
        return element_meta
    if block_children or node_type in {
        "img",
        "br",
        "hr",
        "table",
        "ul",
        "ol",
        "figure",
        "div",
        "form",
        "input",
        "textarea",
    }:
        if block_children or node_type in {"img", "br", "hr"}:
            return element_meta
        if node_type == "div" and not block_children:
            return None
        return element_meta
    if element_meta.get("text"):
        return element_meta
    return None


def extract_scripts(document: dict) -> str:
    compiled_chunks: list[str] = []
    for node in iter_nodes(document):
        if node.get("type") != "script":
            continue
        if node.get("attributes", {}).get("src"):
            continue
        js_payload = node.get("text", "").strip()
        if not js_payload:
            continue
        compiled = compile_javascript(js_payload)
        if compiled.strip():
            compiled_chunks.append(compiled)
    return "\n\n".join(compiled_chunks)


def ingest(target: str, output_path: Path | None = None) -> dict:
    if output_path is None:
        output_path = SCRIPT_DIR / "DOM.json"
    assets_dir = (output_path.parent / f"{output_path.stem}_assets").resolve()

    html_src = load_html(target)
    document = parse_html(html_src)
    title = extract_title(document)
    content_root = extract_page_content(document, target)

    if "google.com/search" in target and not google_html_has_results(html_src):
        serialized_dom = build_google_search_dom(target, html_src)
        title = "Google Search"
    else:
        serialized_dom = serialize_dom(content_root)
        if serialized_dom is None:
            serialized_dom = {"type": "div", "attributes": {}, "children": []}

    base_url = target if target.startswith("http") else Path(target).resolve().as_uri()
    bundle_dir = output_path.parent.resolve()
    localize_assets(serialized_dom, base_url, assets_dir, bundle_dir)

    return {
        "source": target,
        "title": title,
        "dom": serialized_dom,
        "scripts": extract_scripts(document),
    }


def ingest_to_file(target: str, output_path: Path) -> dict:
    bundle = ingest(target, output_path)
    output_path.write_text(json.dumps(bundle, indent=2), encoding="utf-8")
    return bundle


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 www2json.py <FILE|URL> [OUTPUT.json]")
        sys.exit(1)

    target = sys.argv[1]
    output_path = Path(sys.argv[2]) if len(sys.argv) > 2 else SCRIPT_DIR / "DOM.json"

    ingest_to_file(target, output_path)
    print(f"Parsed layout configuration saved successfully to: {output_path}")


if __name__ == "__main__":
    main()
