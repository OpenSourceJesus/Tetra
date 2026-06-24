#!/usr/bin/env python3
"""Serve static test pages and accept image uploads for localhost tests."""

from __future__ import annotations

import argparse
import re
import shutil
import sys
import urllib.parse
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPT_DIR))

from store import TEST_UPLOADS_DIR

ROOT = Path(__file__).resolve().parent
UPLOADS_DIR = TEST_UPLOADS_DIR


class TestPageHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def log_message(self, format: str, *args) -> None:
        if self.server.verbose:
            super().log_message(format, *args)

    def translate_path(self, path: str) -> str:
        parsed = urllib.parse.urlparse(path)
        clean = urllib.parse.unquote(parsed.path)
        if clean.startswith("/uploads/"):
            relative = clean[len("/uploads/") :]
            return str((UPLOADS_DIR / relative).resolve())
        return super().translate_path(path)

    def do_POST(self):
        if self.path.rstrip("/") == "/upload":
            self.handle_upload()
            return
        self.send_error(404, "POST endpoint not found")

    def handle_upload(self):
        content_type = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in content_type:
            self.send_error(400, "Expected multipart/form-data")
            return

        match = re.search(r"boundary=(.+)", content_type)
        if not match:
            self.send_error(400, "Missing multipart boundary")
            return

        boundary = match.group(1).strip().strip('"')
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        file_bytes, filename = extract_uploaded_file(body, boundary.encode())
        if not file_bytes:
            self.send_error(400, "No image uploaded")
            return

        UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
        suffix = Path(filename or "upload.bin").suffix.lower()
        if suffix not in {".png", ".jpg", ".jpeg", ".gif", ".webp"}:
            suffix = ".png"
        dest = UPLOADS_DIR / f"last{suffix}"
        dest.write_bytes(file_bytes)

        location = "/pages/upload-done.html"
        self.send_response(303)
        self.send_header("Location", location)
        self.end_headers()


def extract_uploaded_file(body: bytes, boundary: bytes) -> tuple[bytes, str]:
    delimiter = b"--" + boundary
    filename = "upload.png"
    for part in body.split(delimiter):
        part = part.strip(b"\r\n")
        if not part or part == b"--":
            continue
        header_block, _, payload = part.partition(b"\r\n\r\n")
        if not payload:
            continue
        payload = payload.rstrip(b"\r\n")
        headers = header_block.decode("utf-8", errors="replace")
        if 'name="image"' not in headers and "filename=" not in headers:
            continue
        name_match = re.search(r'filename="([^"]*)"', headers)
        if name_match:
            filename = name_match.group(1) or filename
        return payload, filename
    return b"", ""


def reset_uploads() -> None:
    if UPLOADS_DIR.exists():
        shutil.rmtree(UPLOADS_DIR)
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve browser test pages")
    parser.add_argument("--bind", default="127.0.0.1", help="Address to bind")
    parser.add_argument("--port", type=int, default=8765, help="Port to listen on")
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress request logging (used by automated tests)",
    )
    args = parser.parse_args()

    reset_uploads()
    server = HTTPServer((args.bind, args.port), TestPageHandler)
    server.verbose = not args.quiet
    print(f"Serving test pages at http://{args.bind}:{args.port}/pages/")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
        server.server_close()


if __name__ == "__main__":
    main()
