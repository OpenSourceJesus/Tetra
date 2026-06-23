#!/usr/bin/env python3
"""Serve static test pages for localhost JavaScript translation tests."""

from __future__ import annotations

import argparse
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

ROOT = Path(__file__).resolve().parent


class TestPageHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def log_message(self, format: str, *args) -> None:
        if self.server.verbose:
            super().log_message(format, *args)


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
