#!/usr/bin/env python3
"""End-to-end localhost tests for HTML fetch, JS translation, and image I/O."""

from __future__ import annotations

import json
import socket
import subprocess
import sys
import time
import types
import urllib.error
import urllib.request
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPT_DIR))

from store import BUNDLES_DIR, TEST_UPLOADS_DIR
SERVER_SCRIPT = SCRIPT_DIR / "testserver" / "server.py"
ASSETS_DIR = SCRIPT_DIR / "testserver" / "assets"
UPLOADS_DIR = TEST_UPLOADS_DIR
SAMPLE_PNG = ASSETS_DIR / "sample.png"
SAMPLE_SIZE = (32, 32)

JS_CASES = (
    {
        "page": "basic.html",
        "title": "Basic JS Test",
        "functions": ("greet",),
        "button_hooks": ("greet",),
        "script_markers": ("PyJsHoisted_greet_", "var.get('alert')", "hello from localhost"),
    },
    {
        "page": "multi.html",
        "title": "Multi handler test",
        "functions": ("hello", "goodbye"),
        "button_hooks": ("hello", "goodbye"),
        "script_markers": ("PyJsHoisted_hello_", "PyJsHoisted_goodbye_", "var.get('alert')"),
    },
    {
        "page": "upload.html",
        "title": "Upload image test",
        "functions": ("onPick",),
        "button_hooks": (),
        "script_markers": ("PyJsHoisted_onPick_", "var.get('alert')", "file selected"),
        "file_inputs": ("image",),
        "form_action": "/upload",
        "form_enctype": "multipart/form-data",
    },
    {
        "page": "dom-mutation.html",
        "title": "DOM mutation test",
        "title_after_scripts": "DOM updated",
        "functions": (),
        "button_hooks": (),
        "script_markers": ("createElement", "appendChild", "Hello from translated JS"),
        "dom_markers": ("Hello from translated JS",),
    },
)


def ensure_sample_asset() -> None:
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    try:
        from PIL import Image

        if SAMPLE_PNG.exists():
            with Image.open(SAMPLE_PNG) as img:
                img.load()
            if img.size == SAMPLE_SIZE and img.mode == "RGB":
                return
    except Exception:
        pass

    from PIL import Image

    image = Image.new("RGB", SAMPLE_SIZE, color=(255, 128, 0))
    for y in range(SAMPLE_SIZE[1]):
        for x in range(SAMPLE_SIZE[0]):
            if (x + y) % 2:
                image.putpixel((x, y), (0, 100, 200))
    image.save(SAMPLE_PNG, format="PNG")


def sample_png_bytes() -> bytes:
    ensure_sample_asset()
    return SAMPLE_PNG.read_bytes()


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
        if UPLOADS_DIR.exists():
            for path in UPLOADS_DIR.iterdir():
                path.unlink(missing_ok=True)
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


def find_first(node: dict, node_type: str) -> dict | None:
    if node.get("type") == node_type:
        return node
    for child in node.get("children", []):
        found = find_first(child, node_type)
        if found is not None:
            return found
    return None


def find_inputs(node: dict, input_type: str | None = None) -> list[dict]:
    matches: list[dict] = []
    if node.get("type") == "input":
        if input_type is None or node.get("attributes", {}).get("type", "text") == input_type:
            matches.append(node)
    for child in node.get("children", []):
        matches.extend(find_inputs(child, input_type))
    return matches


def hook_name(onclick: str) -> str:
    return onclick.split("(")[0].strip()


def assert_js_case(case: dict, bundle: dict) -> None:
    assert bundle.get("title") == case["title"], bundle.get("title")
    assert bundle.get("dom"), "missing DOM tree"

    scripts = bundle.get("scripts", "")
    assert scripts.strip(), "compiled scripts are empty"
    for marker in case["script_markers"]:
        assert marker in scripts, f"missing script marker: {marker}"

    namespace: dict = {}
    from script_runtime import apply_scripts_to_dom

    document_dom = bundle.get("document_dom") or bundle.get("dom")
    mutated_dom, namespace_handlers, doc_title = apply_scripts_to_dom(document_dom, scripts)
    namespace.update(namespace_handlers)
    if case.get("title_after_scripts"):
        assert doc_title == case["title_after_scripts"], doc_title
    for func_name in case["functions"]:
        assert func_name in namespace, f"missing function: {func_name}"
        assert isinstance(namespace[func_name], types.FunctionType), func_name

    dom_text = json.dumps(mutated_dom)
    for marker in case.get("dom_markers", ()):
        assert marker in dom_text, f"missing DOM marker: {marker}"

    buttons = find_buttons(bundle["dom"])
    assert len(buttons) == len(case["button_hooks"]), buttons
    wired = {hook_name(btn.get("attributes", {}).get("onclick", "")) for btn in buttons}
    assert wired == set(case["button_hooks"]), wired

    for input_name in case.get("file_inputs", ()):
        file_inputs = [
            node
            for node in find_inputs(bundle["dom"], "file")
            if node.get("attributes", {}).get("name") == input_name
        ]
        assert file_inputs, f"missing file input: {input_name}"

    if "form_action" in case:
        form = find_first(bundle["dom"], "form")
        assert form is not None, "missing form"
        assert form.get("attributes", {}).get("action") == case["form_action"]
        assert case["form_enctype"] in form.get("attributes", {}).get("enctype", "")


def assert_download_image_case(bundle: dict, bundle_dir: Path) -> None:
    assert bundle.get("title") == "Download image test", bundle.get("title")
    image = find_first(bundle["dom"], "img")
    assert image is not None, "missing img node"
    src = image.get("attributes", {}).get("src", "")
    assert src, "image src missing"
    assert not src.startswith(("http://", "https://", "//")), src
    local_path = (bundle_dir / src).resolve()
    assert local_path.exists(), local_path
    data = local_path.read_bytes()
    assert data.startswith(b"\x89PNG\r\n\x1a\n"), "cached file is not a PNG"
    assert data == sample_png_bytes(), "cached PNG does not match sample asset"


def post_multipart_upload(port: int, filename: str, payload: bytes) -> str:
    boundary = "----OfflineBrowserTestBoundary"
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="image"; filename="{filename}"\r\n'
        f"Content-Type: image/png\r\n\r\n"
    ).encode("utf-8") + payload + f"\r\n--{boundary}--\r\n".encode("utf-8")
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/upload",
        data=body,
        method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        assert response.status == 200 or response.status == 303 or response.geturl()
        return response.geturl()


def assert_upload_endpoint(port: int) -> None:
    payload = sample_png_bytes()
    final_url = post_multipart_upload(port, "sample.png", payload)
    assert "upload-done" in final_url, final_url

    uploaded = UPLOADS_DIR / "last.png"
    assert uploaded.exists(), uploaded
    assert uploaded.read_bytes() == payload

    with urllib.request.urlopen(f"http://127.0.0.1:{port}/uploads/last.png", timeout=5) as response:
        served = response.read()
    assert served == payload


def assert_upload_done_page(port: int) -> None:
    sys.path.insert(0, str(SCRIPT_DIR))
    from www2json import ingest

    bundle = ingest(f"http://127.0.0.1:{port}/pages/upload-done.html")
    image = find_first(bundle["dom"], "img")
    assert image is not None
    attrs = image.get("attributes", {})
    assert attrs.get("src_original", "").endswith("last.png"), attrs
    src = attrs.get("src", "")
    assert src and not src.startswith(("http://", "https://", "//")), src
    local_path = (BUNDLES_DIR / src).resolve()
    assert local_path.exists(), local_path
    assert local_path.read_bytes() == sample_png_bytes()


def assert_xhr_search(port: int) -> None:
    from script_runtime import apply_scripts_to_dom
    from www2json import ingest

    page_url = f"http://127.0.0.1:{port}/pages/xhr-search.html"
    bundle = ingest(page_url)
    scripts = bundle.get("scripts", "")
    assert "XMLHttpRequest" in scripts
    assert "callprop('send'" in scripts

    mutated_dom, _, doc_title = apply_scripts_to_dom(
        bundle.get("document_dom") or bundle["dom"],
        scripts,
        {"page_url": page_url},
    )
    dom_text = json.dumps(mutated_dom)
    assert "Python" in dom_text or "python" in dom_text.lower(), dom_text[:500]
    assert doc_title.lower().startswith("xhr:"), doc_title


def assert_xhr_mail(port: int) -> None:
    import urllib.parse

    from script_runtime import apply_scripts_to_dom
    from www2json import ingest

    page_url = f"http://127.0.0.1:{port}/pages/mail.html"
    bundle = ingest(page_url)
    scripts = bundle.get("scripts", "")
    assert "XMLHttpRequest" in scripts
    assert "doLogin" in scripts
    assert "loadInbox" in scripts
    assert "openMessage" in scripts

    mutated_dom, _, _ = apply_scripts_to_dom(
        bundle.get("document_dom") or bundle["dom"],
        scripts,
        {"page_url": page_url},
    )
    assert "MockMail" in json.dumps(mutated_dom)

    login_body = urllib.parse.urlencode({"username": "demo", "password": "demo"}).encode()
    login_req = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/mail/login",
        data=login_body,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(login_req, timeout=5) as response:
        login_payload = json.loads(response.read().decode("utf-8"))
    assert login_payload.get("ok"), login_payload
    token = login_payload["token"]

    with urllib.request.urlopen(
        f"http://127.0.0.1:{port}/api/mail/inbox?token={urllib.parse.quote(token)}",
        timeout=5,
    ) as response:
        inbox_payload = json.loads(response.read().decode("utf-8"))
    assert inbox_payload.get("ok"), inbox_payload
    assert len(inbox_payload.get("messages", [])) >= 1

    message_id = inbox_payload["messages"][0]["id"]
    with urllib.request.urlopen(
        f"http://127.0.0.1:{port}/api/mail/message/{message_id}?token={urllib.parse.quote(token)}",
        timeout=5,
    ) as response:
        message_payload = json.loads(response.read().decode("utf-8"))
    assert message_payload.get("ok"), message_payload
    assert message_payload["message"]["subject"]


def assert_mock_search(port: int) -> None:
    from www2json import ingest

    home = ingest(f"http://127.0.0.1:{port}/")
    assert home.get("title") == "Mock Search", home.get("title")
    home_text = json.dumps(home["dom"])
    assert '"name": "q"' in home_text or '"name":"q"' in home_text.replace(" ", "")

    results = ingest(f"http://127.0.0.1:{port}/search?q=python")
    assert "Mock Search" in results.get("title", "")
    results_text = json.dumps(results["dom"])
    assert "Python" in results_text or "python" in results_text.lower()
    assert results.get("scripts", "").strip()

    detail = ingest(f"http://127.0.0.1:{port}/result/python-docs")
    assert "Python documentation" in json.dumps(detail["dom"])


def run_tests() -> None:
    ensure_sample_asset()
    sys.path.insert(0, str(SCRIPT_DIR))
    from www2json import ingest

    with LocalTestServer() as port:
        for case in JS_CASES:
            url = f"http://127.0.0.1:{port}/pages/{case['page']}"
            bundle = ingest(url)
            assert_js_case(case, bundle)
            print(f"    ok  {case['page']}")

        download_url = f"http://127.0.0.1:{port}/pages/download.html"
        download_bundle = ingest(download_url)
        assert_download_image_case(download_bundle, BUNDLES_DIR)
        print("    ok  download.html (image cached)")

        assert_upload_endpoint(port)
        print("    ok  POST /upload")

        assert_upload_done_page(port)
        print("    ok  upload-done.html")

        assert_mock_search(port)
        print("    ok  mock search")

        assert_xhr_search(port)
        print("    ok  xhr search")

        assert_xhr_mail(port)
        print("    ok  xhr mail")


def main() -> int:
    print("==> localhost JS pipeline")
    try:
        run_tests()
    except Exception as exc:
        print(f"    FAIL  {exc}", file=sys.stderr)
        return 1
    print("    all localhost tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
