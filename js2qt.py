#!/usr/bin/env python3
"""CLI entry point for Js2Py script translation."""

import sys

from js2py_translator import translate_script


def main():
    js_code = sys.stdin.read()
    if not js_code.strip():
        return

    try:
        print(translate_script(js_code))
    except Exception as exc:
        print(f"# Translation Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
