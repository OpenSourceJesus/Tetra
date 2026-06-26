"""Runtime for Js2Py-translated page scripts with live DOM support."""

from __future__ import annotations

import types
from typing import Any, Callable

from dom_model import DomModel
from js_objects import (
    Js,
    JsBase,
    JsFunction,
    JsRegExp,
    PyJsComma,
    PyJsStrictEq,
    PyJsStrictNeq,
    build_browser_objects,
)

_VAR_HOLDER: dict[str, Any] = {"var": None}


def current_var() -> Any:
    return _VAR_HOLDER["var"]


class VarScope:
    def __init__(self, parent: VarScope | None = None, globals_scope: Any | None = None):
        self._parent = parent
        self._values: dict[str, Any] = {}
        self._globals_scope = globals_scope

    def registers(self, names: list[str]) -> None:
        for name in names:
            self._values.setdefault(name, None)

    def get(self, name: str | Any, throw: bool = False, **_kwargs: Any) -> Any:
        key = str(name)
        if key in self._values:
            value = self._values[key]
            return Js(None) if value is None else value
        if self._parent is not None:
            parent_value = self._parent.get(key)
            if parent_value is not None and not (
                isinstance(parent_value, JsBase) and parent_value.value is None
            ):
                return parent_value
        if self._globals_scope is not None:
            return self._globals_scope.get(key)
        return Js(None)

    def _owning_scope(self, name: str) -> VarScope:
        """Find the scope where `name` is declared, mirroring JS var semantics.

        Assignments target the nearest enclosing scope that already declares the
        variable so closures write back to outer variables instead of shadowing
        them locally. Undeclared names fall back to the global (root) scope.
        """
        scope: VarScope | None = self
        root = self
        while scope is not None:
            if name in scope._values:
                return scope
            root = scope
            scope = scope._parent
        return root

    def put(self, name: str, value: Any, op: str | None = None) -> Any:
        target = self._owning_scope(name)
        if op == "+":
            current = target._values.get(name, 0)
            try:
                target._values[name] = current + value
            except TypeError:
                target._values[name] = str(current) + str(value)
        else:
            target._values[name] = value
        if self._globals_scope is not None and name not in {"window", "document", "this"}:
            self._globals_scope.put(name, value, op)
        return value

    def to_python(self) -> dict[str, Any]:
        return dict(self._values)


def Scope(bindings: dict[str, Any], parent: VarScope) -> VarScope:
    scope = VarScope(parent, globals_scope=parent._globals_scope)
    # Function arguments are local declarations, so bind them directly into this
    # scope rather than through put() (which routes assignments to the declaring
    # outer scope and would otherwise leak parameters into the global scope).
    scope._values.update(bindings)
    return scope


def build_runtime(
    extra: dict[str, Any] | None = None,
    dom_model: DomModel | None = None,
) -> dict[str, Any]:
    var = VarScope()
    _VAR_HOLDER["var"] = var
    runtime: dict[str, Any] = {
        "var": var,
        "Scope": Scope,
        "Js": Js,
        "JsRegExp": JsRegExp,
        "PyJsStrictEq": PyJsStrictEq,
        "PyJsStrictNeq": PyJsStrictNeq,
        "PyJsComma": PyJsComma,
        "pass": None,
    }
    browser = build_browser_objects(
        dom_model or DomModel({"type": "body", "attributes": {}, "children": []}),
        extra or {},
    )
    window = browser["window"]
    var._globals_scope = window
    var.put("window", window)
    var.put("document", browser["document"])
    runtime.update(browser)
    if extra:
        runtime.update(extra)
    _inject_browser_apis(var, extra or {})
    return runtime


def _inject_browser_apis(var: VarScope, namespace: dict[str, Any]) -> None:
    message_box = namespace.get("QMessageBox")
    if message_box is not None:
        def alert(msg: Any) -> None:
            message_box.information(None, "Alert", str(msg))

        var.put("alert", alert)


def wrap_js_handler(func: Callable, var: VarScope) -> Callable:
    def callback(*_args: Any, **_kwargs: Any) -> Any:
        return func(None, [], var)

    name = getattr(func, "func_name", getattr(func, "__name__", "handler"))
    callback.__name__ = name
    return callback


def extract_handlers(runtime: dict[str, Any]) -> dict[str, Callable]:
    var: VarScope = runtime["var"]
    handlers: dict[str, Callable] = {}
    for name, value in var.to_python().items():
        func = None
        if isinstance(value, types.FunctionType):
            func = value
        elif isinstance(value, JsFunction) and callable(value.value):
            func = value.value
        if func is not None:
            handlers[name] = wrap_js_handler(func, var)
    return handlers
