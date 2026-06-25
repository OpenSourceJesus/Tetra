"""Load and run Python translated from page JavaScript via Js2Py."""

from __future__ import annotations

import copy
import os
import sys
from typing import Any, Callable

from dom_model import DomModel

HANDLER_MARKERS = ("PyJsHoisted_", ".func_name =")


def is_translated_script(python_src: str) -> bool:
    stripped = python_src.strip()
    if not stripped:
        return False
    lines = [
        line
        for line in stripped.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    return bool(lines)


def is_translated_handler_script(python_src: str) -> bool:
    return is_translated_script(python_src) and any(
        marker in python_src for marker in HANDLER_MARKERS
    )


def _script_chunks(python_src: str) -> list[str]:
    chunks = [chunk.strip() for chunk in python_src.split("\n\n") if chunk.strip()]
    return chunks or ([python_src.strip()] if python_src.strip() else [])


def run_page_scripts(
    python_src: str,
    dom_model: DomModel,
    namespace: dict[str, Any] | None = None,
) -> dict[str, Callable]:
    """Exec translated scripts against a live DOM and return callable handlers."""
    if not is_translated_script(python_src):
        dom_model.dispatch_event("DOMContentLoaded")
        return {}

    from js2py_runtime import build_runtime, extract_handlers

    debug = bool(os.environ.get("BROWSER_DEBUG_JS"))
    runtime = build_runtime(namespace, dom_model=dom_model)
    for chunk in _script_chunks(python_src):
        try:
            exec(chunk, runtime)
        except Exception as exc:
            if debug:
                print(f"Script error: {exc}", file=sys.stderr)

    try:
        dom_model.dispatch_event("DOMContentLoaded")
    except Exception as exc:
        if debug:
            print(f"Script error (DOMContentLoaded): {exc}", file=sys.stderr)
    return extract_handlers(runtime)


def load_scripts(
    python_src: str,
    namespace: dict[str, Any] | None = None,
    dom_model: DomModel | None = None,
) -> dict[str, Callable]:
    model = dom_model or DomModel({"type": "body", "attributes": {}, "children": []})
    return run_page_scripts(python_src, model, namespace)


def apply_scripts_to_dom(
    dom: dict[str, Any],
    python_src: str,
    namespace: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Callable], str]:
    """Run translated scripts on a DOM snapshot and return the mutated tree."""
    dom_model = DomModel(dom)
    handlers = run_page_scripts(python_src, dom_model, namespace)
    return dom_model.display_dom(), handlers, dom_model.title


def load_handlers(
    python_src: str,
    namespace: dict[str, Any] | None = None,
) -> dict[str, Callable]:
    return load_scripts(python_src, namespace)
