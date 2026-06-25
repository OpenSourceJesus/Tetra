"""Bridge to the vendored Js2Py translator (JavaScript -> Python source)."""

from __future__ import annotations

import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent
JS2PY_ROOT = ROOT / "Js2Py"

_TRANSLATOR_HEADER = "# translated by Js2Py\n"
_translate_js = None
_clean_stacks = None


def _purge_js2py_modules() -> None:
    for name in list(sys.modules):
        if name == "js2py" or name.startswith("js2py."):
            del sys.modules[name]


def _ensure_js2py_translator():
    global _translate_js, _clean_stacks
    if _translate_js is not None and _clean_stacks is not None:
        return _translate_js, _clean_stacks

    _purge_js2py_modules()

    root = str(JS2PY_ROOT)
    if root in sys.path:
        sys.path.remove(root)
    sys.path.insert(0, root)

    js2py = types.ModuleType("js2py")
    js2py.__path__ = [str(JS2PY_ROOT / "js2py")]
    translators = types.ModuleType("js2py.translators")
    translators.__path__ = [str(JS2PY_ROOT / "js2py" / "translators")]
    sys.modules["js2py"] = js2py
    sys.modules["js2py.translators"] = translators

    import pyjsparser.parser

    pyjsparser.parser.ENABLE_PYIMPORT = False

    from js2py.translators import translating_nodes
    from js2py.translators.translator import translate_js

    _translate_js = translate_js
    _clean_stacks = translating_nodes.clean_stacks
    return _translate_js, _clean_stacks


def translate_script(js_code: str) -> str:
    """Translate JavaScript to Python with Js2Py. JavaScript is never executed."""
    stripped = js_code.strip()
    if not stripped:
        return ""

    translate_js, clean_stacks = _ensure_js2py_translator()
    clean_stacks()
    try:
        return translate_js(stripped, HEADER=_TRANSLATOR_HEADER)
    except Exception:
        return ""


def translate_handlers(js_code: str) -> str:
    """Translate and keep only scripts that define onclick-style handlers."""
    translated = translate_script(js_code)
    if "PyJsHoisted_" not in translated:
        return ""
    return translated
