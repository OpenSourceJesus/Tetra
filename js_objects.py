"""PyJs-compatible values for Js2Py-translated Python."""

from __future__ import annotations

import re
import types
from typing import Any, Callable, Iterator

import json
import urllib.parse

from dom_model import DomModel


def _key(value: Any) -> str:
    if isinstance(value, JsBase):
        raw = value.value
        if isinstance(raw, float) and raw.is_integer():
            return str(int(raw))
        return str(raw) if raw is not None else ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _unwrap(value: Any) -> Any:
    if isinstance(value, JsBase):
        return value.to_python()
    return value


def _js_number(value: Any) -> float:
    if isinstance(value, JsBase):
        return value._number()
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return float("nan")


def _truthy(value: Any) -> bool:
    if isinstance(value, JsBase):
        return value.is_truthy()
    if value is None:
        return False
    if isinstance(value, (list, dict)) and not value:
        return False
    if value in (0, 0.0, ""):
        return False
    return True


def _raw(value: Any) -> Any:
    return value.value if isinstance(value, JsBase) else value


def _int32(value: Any) -> int:
    number = _js_number(value)
    if number != number or number in (float("inf"), float("-inf")):
        return 0
    return int(number) & 0xFFFFFFFF


def _js_str(value: Any) -> str:
    value = _raw(value)
    if value is None:
        return "undefined"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        if value != value:
            return "NaN"
        if value == float("inf"):
            return "Infinity"
        if value == float("-inf"):
            return "-Infinity"
        if value.is_integer():
            return str(int(value))
        return repr(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return ",".join(_js_str(item) for item in value)
    if isinstance(value, dict):
        return "[object Object]"
    return str(value)


class JsRegExp:
    def __init__(self, pattern: Any, flags: Any = ""):
        source = _unwrap(pattern)
        flag_text = _unwrap(flags)
        if isinstance(source, str) and source.startswith("/") and source.rfind("/") > 0:
            cut = source.rfind("/")
            flag_text = source[cut + 1 :]
            source = source[1:cut]
        self.source = source if isinstance(source, str) else ""
        try:
            self.pattern = re.compile(self.source, _regex_flags(flag_text))
        except re.error:
            try:
                self.pattern = re.compile(re.escape(self.source), _regex_flags(flag_text))
            except re.error:
                self.pattern = re.compile("(?!x)x")

    def callprop(self, name: str, *args: Any) -> Any:
        name = _key(name)
        if name == "test":
            return Js(bool(self.pattern.search(str(_unwrap(args[0])))))
        if name == "exec":
            match = self.pattern.search(str(_unwrap(args[0])))
            return Js(match.group(0)) if match else Js(None)
        return Js(None)


def _regex_flags(flag_text: str) -> int:
    flags = 0
    if "i" in flag_text:
        flags |= re.IGNORECASE
    if "m" in flag_text:
        flags |= re.MULTILINE
    if "s" in flag_text:
        flags |= re.DOTALL
    return flags


class JsBase:
    def __init__(self, value: Any = None):
        self.value = value

    def _number(self) -> float:
        if isinstance(self.value, bool):
            return float(self.value)
        if isinstance(self.value, (int, float)):
            return float(self.value)
        if self.value is None:
            return float("nan")
        try:
            return float(self.value)
        except (TypeError, ValueError):
            return float("nan")

    def __gt__(self, other: Any) -> bool:
        return self._number() > _js_number(other)

    def __lt__(self, other: Any) -> bool:
        return self._number() < _js_number(other)

    def __ge__(self, other: Any) -> bool:
        return self._number() >= _js_number(other)

    def __le__(self, other: Any) -> bool:
        return self._number() <= _js_number(other)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, JsBase):
            return self.value == other.value
        return self.value == other

    def __hash__(self) -> int:
        try:
            return hash(self.value)
        except TypeError:
            return id(self)

    def __add__(self, other: Any) -> Js:
        left = _raw(self)
        right = _raw(other)
        if isinstance(left, str) or isinstance(right, str):
            return Js(_js_str(left) + _js_str(right))
        return Js(self._number() + _js_number(other))

    def __radd__(self, other: Any) -> Js:
        left = _raw(other)
        right = _raw(self)
        if isinstance(left, str) or isinstance(right, str):
            return Js(_js_str(left) + _js_str(right))
        return Js(_js_number(other) + self._number())

    def __sub__(self, other: Any) -> Js:
        return Js(self._number() - _js_number(other))

    def __rsub__(self, other: Any) -> Js:
        return Js(_js_number(other) - self._number())

    def __mul__(self, other: Any) -> Js:
        return Js(self._number() * _js_number(other))

    def __rmul__(self, other: Any) -> Js:
        return Js(_js_number(other) * self._number())

    def __truediv__(self, other: Any) -> Js:
        divisor = _js_number(other)
        return Js(self._number() / divisor if divisor else float("nan"))

    def __rtruediv__(self, other: Any) -> Js:
        divisor = self._number()
        return Js(_js_number(other) / divisor if divisor else float("nan"))

    def __mod__(self, other: Any) -> Js:
        divisor = _js_number(other)
        return Js(self._number() % divisor if divisor else float("nan"))

    def __neg__(self) -> Js:
        return Js(-self._number())

    def __pos__(self) -> Js:
        return Js(self._number())

    def _int32(self) -> int:
        number = self._number()
        if number != number or number in (float("inf"), float("-inf")):
            return 0
        return int(number) & 0xFFFFFFFF

    def __or__(self, other: Any) -> Js:
        return Js(float(self._int32() | _int32(other)))

    def __ror__(self, other: Any) -> Js:
        return Js(float(_int32(other) | self._int32()))

    def __and__(self, other: Any) -> Js:
        return Js(float(self._int32() & _int32(other)))

    def __rand__(self, other: Any) -> Js:
        return Js(float(_int32(other) & self._int32()))

    def __xor__(self, other: Any) -> Js:
        return Js(float(self._int32() ^ _int32(other)))

    def __lshift__(self, other: Any) -> Js:
        return Js(float(self._int32() << (_int32(other) & 31)))

    def __rshift__(self, other: Any) -> Js:
        return Js(float(self._int32() >> (_int32(other) & 31)))

    def typeof(self) -> Js:
        value = self.value
        if value is None:
            return Js("undefined")
        if isinstance(value, bool):
            return Js("boolean")
        if isinstance(value, (int, float)):
            return Js("number")
        if isinstance(value, str):
            return Js("string")
        return Js("object")

    def to_number(self) -> float:
        return self._number()

    def to_string(self) -> Js:
        return Js(_js_str(self.value))

    def __call__(self, *args: Any) -> Any:
        return Js(None)

    def is_truthy(self) -> bool:
        return _truthy(self.value)

    def __bool__(self) -> bool:
        return self.is_truthy()

    def neg(self) -> Js:
        return Js(not self.is_truthy())

    def contains(self, key: Any) -> Js:
        key_text = _key(key)
        if isinstance(self.value, dict):
            return Js(key_text in self.value)
        if isinstance(self.value, (list, tuple)):
            return Js(key_text.isdigit() and int(key_text) < len(self.value))
        return Js(False)

    def get(self, key: Any) -> Any:
        key_text = _key(key)
        if isinstance(self.value, dict):
            if key_text in self.value:
                return _wrap(self.value[key_text])
            return Js(None)
        if isinstance(self.value, (list, tuple)):
            if key_text == "length":
                return Js(float(len(self.value)))
            if key_text.isdigit():
                index = int(key_text)
                if 0 <= index < len(self.value):
                    return _wrap(self.value[index])
            return Js(None)
        if isinstance(self.value, str):
            if key_text == "length":
                return Js(float(len(self.value)))
            return Js(None)
        return Js(None)

    def put(self, key: Any, val: Any, op: str | None = None) -> Any:
        key_text = _key(key)
        py_val = _unwrap(val)
        if not isinstance(self.value, dict):
            self.value = {}
        if op == "+":
            current = self.value.get(key_text, 0)
            try:
                self.value[key_text] = current + py_val
            except TypeError:
                self.value[key_text] = str(current) + str(py_val)
        else:
            self.value[key_text] = py_val
        return _wrap(self.value[key_text])

    def delete(self, key: Any) -> Js:
        key_text = _key(key)
        if isinstance(self.value, dict) and key_text in self.value:
            del self.value[key_text]
            return Js(True)
        return Js(True)

    def callprop(self, name: str, *args: Any) -> Any:
        key = _key(name)
        if isinstance(self.value, dict) and key in self.value:
            member = self.value[key]
            if isinstance(member, JsFunction) or callable(member):
                return call_value(member, args, this=self)
            return Js(None)
        if isinstance(self.value, list):
            return self._array_method(key, args)
        if isinstance(self.value, str):
            return JsString(self.value).callprop(key, *args)
        return Js(None)

    def _array_method(self, name: str, args: tuple[Any, ...]) -> Any:
        items = self.value
        if name == "push":
            for arg in args:
                items.append(_unwrap(arg))
            return Js(float(len(items)))
        if name == "pop":
            return _wrap(items.pop()) if items else Js(None)
        if name == "shift":
            return _wrap(items.pop(0)) if items else Js(None)
        if name == "unshift":
            for arg in reversed(args):
                items.insert(0, _unwrap(arg))
            return Js(float(len(items)))
        if name == "indexOf":
            target = _unwrap(args[0]) if args else None
            try:
                return Js(float(items.index(target)))
            except ValueError:
                return Js(-1.0)
        if name == "join":
            sep = str(_unwrap(args[0])) if args else ","
            return Js(sep.join("" if item is None else str(item) for item in items))
        if name == "slice":
            start = int(_unwrap(args[0])) if args else 0
            end = int(_unwrap(args[1])) if len(args) > 1 else None
            return _wrap(items[start:end] if end is not None else items[start:])
        if name == "concat":
            combined = list(items)
            for arg in args:
                value = _unwrap(arg)
                combined.extend(value if isinstance(value, list) else [value])
            return _wrap(combined)
        if name in {"forEach", "map", "filter"}:
            callback = args[0] if args else None
            results = []
            for index, item in enumerate(items):
                outcome = call_value(callback, (_wrap(item), Js(float(index))), this=self)
                if name == "map":
                    results.append(_unwrap(outcome))
                elif name == "filter" and _truthy(outcome):
                    results.append(item)
            if name == "map":
                return _wrap(results)
            if name == "filter":
                return _wrap(results)
            return Js(None)
        return Js(None)

    def create(self, *args: Any, **kwargs: Any) -> Any:
        if isinstance(self.value, JsFunction) or callable(self.value):
            return call_value(self.value, args)
        return Js(None)

    def to_python(self) -> Any:
        if isinstance(self.value, dict):
            return {key: _unwrap(value) for key, value in self.value.items()}
        if isinstance(self.value, list):
            return [_unwrap(item) for item in self.value]
        return self.value

    def __iter__(self) -> Iterator[Any]:
        if isinstance(self.value, dict):
            yield from self.value
        elif isinstance(self.value, (list, tuple)):
            yield from self.value
        elif isinstance(self.value, str):
            yield from self.value


class JsString(JsBase):
    def callprop(self, name: str, *args: Any) -> Any:
        name = _key(name)
        text = str(self.value)
        if name == "indexOf":
            needle = str(_unwrap(args[0]))
            start = int(_unwrap(args[1])) if len(args) > 1 else 0
            return Js(float(text.find(needle, start)))
        if name == "substr":
            start = int(_unwrap(args[0]))
            length = int(_unwrap(args[1])) if len(args) > 1 else None
            return Js(text[start : start + length] if length is not None else text[start:])
        if name == "replace":
            pattern = args[0]
            repl = str(_unwrap(args[1]))
            if isinstance(pattern, JsRegExp):
                return Js(pattern.pattern.sub(repl, text))
            return Js(text.replace(str(_unwrap(pattern)), repl))
        if name == "match":
            pattern = args[0]
            if isinstance(pattern, JsRegExp):
                found = pattern.pattern.search(text)
                return Js(found.group(0) if found else None)
            return Js(None)
        if name == "split":
            sep = str(_unwrap(args[0])) if args else None
            return Js(text.split(sep) if sep is not None else list(text))
        if name == "toLowerCase":
            return Js(text.lower())
        if name == "toUpperCase":
            return Js(text.upper())
        if name == "trim":
            return Js(text.strip())
        if name == "charAt":
            index = int(_unwrap(args[0])) if args else 0
            return Js(text[index] if 0 <= index < len(text) else "")
        if name == "slice" or name == "substring":
            start = int(_unwrap(args[0])) if args else 0
            end = int(_unwrap(args[1])) if len(args) > 1 else None
            return Js(text[start:end] if end is not None else text[start:])
        return Js(None)


class JsArguments(JsBase):
    def __init__(self, items: Any):
        super().__init__(list(items))

    def get(self, key: Any) -> Any:
        key_text = _key(key)
        if key_text == "length":
            return Js(float(len(self.value)))
        if key_text.isdigit():
            index = int(key_text)
            if 0 <= index < len(self.value):
                return self.value[index]
        return Js(None)

    def __iter__(self) -> Iterator[Any]:
        return iter(self.value)


class JsFunction(JsBase):
    def _set_name(self, name: str) -> Any:
        self.value.func_name = name
        return self

    def typeof(self) -> Js:
        return Js("function")

    def __call__(self, *args: Any) -> Any:
        return call_value(self.value, args)

    def callprop(self, name: str, *args: Any) -> Any:
        if _key(name) == "call":
            return call_value(self.value, args[1:], this=args[0] if args else None)
        if _key(name) == "apply":
            this = args[0] if args else None
            params = args[1] if len(args) > 1 else []
            if isinstance(params, JsBase):
                params = list(params)
            return call_value(self.value, params, this=this)
        if _key(name) == "bind":
            bound_this = args[0] if args else None
            func = self.value
            return JsFunction(lambda *call_args: call_value(func, call_args, this=bound_this))
        return Js(None)

    def create(self, *args: Any, **kwargs: Any) -> Any:
        return call_value(self.value, args)


class DomElement(JsBase):
    def __init__(self, node: dict[str, Any], model: DomModel):
        super().__init__(node)
        self.node = node
        self.model = model

    def get(self, key: Any) -> Any:
        key_text = _key(key)
        if key_text == "style":
            return DomStyle(self.node, self.model)
        if key_text == "body":
            return DomElement(self.model.body, self.model)
        if key_text in self.node.get("attributes", {}):
            return Js(self.node["attributes"][key_text])
        if key_text in {"innerHTML", "outerHTML", "textContent", "id", "className", "value"}:
            return self._get_property(key_text)
        return Js(None)

    def put(self, key: Any, val: Any, op: str | None = None) -> Any:
        key_text = _key(key)
        if key_text in {"innerHTML", "textContent", "id", "className", "value", "onclick", "onload", "onerror"}:
            self._set_property(key_text, _unwrap(val))
            return _wrap(val)
        if key_text == "style" and isinstance(val, DomStyle):
            return val
        self.node.setdefault("attributes", {})[_key(key)] = str(_unwrap(val))
        if _key(key) == "id":
            self.model._reindex()
        return _wrap(val)

    def callprop(self, name: str, *args: Any) -> Any:
        name = _key(name)
        if name == "appendChild":
            child = args[0]
            if isinstance(child, DomElement):
                self.model.append_child(self.node, child.node)
            return args[0]
        if name == "removeChild":
            child = args[0]
            if isinstance(child, DomElement):
                self.model.remove_child(self.node, child.node)
            return args[0]
        if name == "setAttribute":
            self.model.set_attribute(self.node, _key(args[0]), _unwrap(args[1]))
            return Js(None)
        if name == "getAttribute":
            return Js(self.model.get_attribute(self.node, _key(args[0])))
        if name == "addEventListener":
            event = _key(args[0])
            handler = args[1]
            if isinstance(handler, JsFunction):
                handler = handler.value
            self.model.add_event_listener(event, lambda h=handler: _call_js_function(h, (), None))
            return Js(None)
        if name == "click":
            self.model.click_element(self.node)
            return Js(None)
        return super().callprop(name, *args)

    def _get_property(self, name: str) -> Any:
        if name == "innerHTML":
            return Js(self.model.get_inner_html(self.node))
        if name == "textContent":
            return Js(self.model.get_text_content(self.node))
        if name == "id":
            return Js(self.node.get("attributes", {}).get("id", ""))
        if name == "className":
            return Js(self.node.get("attributes", {}).get("class", ""))
        if name == "value":
            return Js(self.node.get("attributes", {}).get("value", ""))
        return Js(None)

    def _set_property(self, name: str, value: Any) -> None:
        if name == "innerHTML":
            self.model.set_inner_html(self.node, str(value))
            return
        if name == "textContent":
            self.model.set_text_content(self.node, str(value))
            return
        if name == "id":
            self.model.set_attribute(self.node, "id", value)
            return
        if name == "className":
            self.model.set_attribute(self.node, "class", value)
            return
        if name == "value":
            self.model.set_attribute(self.node, "value", value)
            return
        if name.startswith("on"):
            self.node.setdefault("attributes", {})[name] = str(value)


def _parse_style(text: str) -> dict[str, str]:
    props: dict[str, str] = {}
    for decl in str(text).split(";"):
        decl = decl.strip()
        if not decl or ":" not in decl:
            continue
        name, value = decl.split(":", 1)
        props[name.strip().lower()] = value.strip()
    return props


def _serialize_style(props: dict[str, str]) -> str:
    return "; ".join(f"{name}: {value}" for name, value in props.items())


class DomStyle(JsBase):
    def __init__(self, node: dict[str, Any], model: DomModel):
        super().__init__({})
        self.node = node
        self.model = model

    def get(self, key: Any) -> Any:
        props = _parse_style(self.node.get("attributes", {}).get("style", ""))
        return Js(props.get(_key(key).strip().lower(), ""))

    def put(self, key: Any, val: Any, op: str | None = None) -> Any:
        attrs = self.node.setdefault("attributes", {})
        props = _parse_style(attrs.get("style", ""))
        props[_key(key).strip().lower()] = _js_str(_unwrap(val))
        attrs["style"] = _serialize_style(props)
        return _wrap(val)


class DomDocument(DomElement):
    def get(self, key: Any) -> Any:
        key_text = _key(key)
        if key_text == "body":
            return DomElement(self.model.body, self.model)
        if key_text == "title":
            return Js(self.model.title)
        return super().get(key)

    def put(self, key: Any, val: Any, op: str | None = None) -> Any:
        if _key(key) == "title":
            self.model.title = str(_unwrap(val))
            return _wrap(val)
        return super().put(key, val, op)

    def callprop(self, name: str, *args: Any) -> Any:
        name = _key(name)
        if name == "getElementById":
            node = self.model.get_element_by_id(_key(args[0]))
            return DomElement(node, self.model) if node else Js(None)
        if name == "querySelector":
            node = self.model.query_selector(_key(args[0]))
            return DomElement(node, self.model) if node else Js(None)
        if name == "createElement":
            return DomElement(self.model.create_element(_key(args[0])), self.model)
        if name == "addEventListener":
            event = _key(args[0])
            handler = args[1]
            if isinstance(handler, JsFunction):
                handler = handler.value
            self.model.add_event_listener(event, lambda h=handler: _call_js_function(h, (), None))
            return Js(None)
        return super().callprop(name, *args)


class JsFactory:
    def __call__(self, arg: Any = None) -> Any:
        if callable(arg):
            def _set_name(name: str) -> Any:
                arg.func_name = name
                return arg

            arg._set_name = _set_name
            arg.func_name = getattr(arg, "func_name", arg.__name__)
            return JsFunction(arg)
        if isinstance(arg, dict):
            return JsBase({key: _unwrap(value) for key, value in arg.items()})
        if isinstance(arg, list):
            return JsBase([_unwrap(value) for value in arg])
        if arg is None:
            return JsBase(None)
        if isinstance(arg, bool):
            return JsBase(arg)
        if isinstance(arg, (int, float)):
            return JsBase(float(arg))
        return JsString(arg)


Js = JsFactory()


def _wrap(value: Any) -> Any:
    from js_xhr import JsXMLHttpRequest

    if isinstance(value, JsXMLHttpRequest):
        return value
    if isinstance(value, JsBase):
        return value
    if isinstance(value, DomElement):
        return value
    if callable(value):
        return JsFunction(value)
    if isinstance(value, bool):
        return Js(value)
    if isinstance(value, (int, float)):
        return Js(float(value))
    if value is None:
        return Js(None)
    if isinstance(value, dict):
        return JsBase(value)
    if isinstance(value, (list, tuple)):
        return JsBase(list(value))
    return JsString(value)


def invoke_js(func: Callable, js_args: tuple[Any, ...] | list[Any], this: Any = None) -> Any:
    """Call a Js2Py-translated function, binding JS args to its parameters."""
    wrapped_args = [arg if isinstance(arg, (JsBase, DomElement)) else _wrap(arg) for arg in js_args]
    code = getattr(func, "__code__", None)
    if code is None:
        return _wrap(func(*wrapped_args))

    arg_names = code.co_varnames[: code.co_argcount]
    if "this" in arg_names and "arguments" in arg_names:
        param_count = arg_names.index("this")
        bound = [
            wrapped_args[i] if i < len(wrapped_args) else Js(None)
            for i in range(param_count)
        ]
        return _wrap(func(*bound, this, JsArguments(wrapped_args)))
    return _wrap(func(*wrapped_args))


def call_value(value: Any, js_args: tuple[Any, ...] | list[Any], this: Any = None) -> Any:
    """Invoke a JS-callable value (JsFunction, raw callable, or undefined)."""
    if isinstance(value, JsFunction):
        return invoke_js(value.value, js_args, this)
    if callable(value):
        return invoke_js(value, js_args, this)
    return Js(None)


def _call_js_function(func: Callable, args: tuple[Any, ...] | list[Any], this: Any, var: Any = None) -> Any:
    return call_value(func, args, this=this)


def PyJsStrictEq(left: Any, right: Any) -> Js:
    return Js(_unwrap(left) == _unwrap(right))


def PyJsStrictNeq(left: Any, right: Any) -> Js:
    return Js(_unwrap(left) != _unwrap(right))


def PyJsComma(*values: Any) -> Any:
    return values[-1] if values else Js(None)


def _to_js_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _to_js_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_to_js_value(item) for item in value]
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return float(value)
    if value is None:
        return None
    return str(value)


def _from_js_value(value: Any) -> Any:
    if isinstance(value, JsBase):
        raw = value.value
        if isinstance(raw, dict):
            return {key: _from_js_value(_wrap(item)) for key, item in raw.items()}
        if isinstance(raw, list):
            return [_from_js_value(_wrap(item)) for item in raw]
        return raw
    return value


class JsImage:
    def put(self, key: Any, val: Any, op: str | None = None) -> Any:
        return _wrap(val)

    def get(self, key: Any) -> Any:
        return Js(None)


class JsError:
    def __init__(self) -> None:
        self.data: dict[str, Any] = {"message": "", "stack": "", "name": "Error", "fileName": "", "lineNumber": 0}

    def put(self, key: Any, val: Any, op: str | None = None) -> Any:
        self.data[_key(key)] = _unwrap(val)
        return _wrap(val)

    def get(self, key: Any) -> Any:
        return Js(self.data.get(_key(key)))


def build_browser_objects(dom_model: DomModel, namespace: dict[str, Any]) -> dict[str, Any]:
    from js_xhr import xhr_constructor

    page_url = str(namespace.get("page_url", "") or "")
    xhr_complete = namespace.get("xhr_complete")
    on_complete = xhr_complete if callable(xhr_complete) else None
    document = DomDocument(dom_model.body, dom_model)
    window = JsBase({})
    window.put("document", document)
    window.put("window", window)

    def image_factory(*_args: Any, **_kwargs: Any) -> JsImage:
        return JsImage()

    def error_factory(*_args: Any, **_kwargs: Any) -> JsError:
        return JsError()

    def string_factory(value: Any = "") -> JsString:
        return JsString(_unwrap(value))

    def json_parse(value: Any, **_kwargs: Any) -> Js:
        data = json.loads(str(_unwrap(value)))
        return Js(_to_js_value(data))

    def json_stringify(value: Any, **_kwargs: Any) -> Js:
        return Js(json.dumps(_from_js_value(value)))

    def encode_uri_component(value: Any, **_kwargs: Any) -> Js:
        return Js(urllib.parse.quote(str(_unwrap(value)), safe=""))

    builtins = {
        "true": Js(True),
        "false": Js(False),
        "null": Js(None),
        "undefined": Js(None),
        "Infinity": Js(float("inf")),
        "NaN": Js(float("nan")),
        "document": document,
        "window": window,
        "XMLHttpRequest": xhr_constructor(page_url, on_complete),
        "JSON": JsBase({"parse": JsFunction(json_parse), "stringify": JsFunction(json_stringify)}),
        "encodeURIComponent": JsFunction(encode_uri_component),
        "Image": JsFunction(image_factory),
        "Error": JsFunction(error_factory),
        "String": JsFunction(string_factory),
        "parseInt": JsFunction(lambda value, radix=10, **_k: Js(int(str(_unwrap(value)), int(_unwrap(radix))))),
        "parseFloat": JsFunction(lambda value, **_k: Js(float(str(_unwrap(value))))),
        "isNaN": JsFunction(lambda value, **_k: Js(_unwrap(value) != _unwrap(value))),
        "console": JsBase({"log": JsFunction(lambda *parts, **_k: None)}),
    }
    for name, value in builtins.items():
        if name not in {"document", "window"}:
            window.put(name, value)
    builtins.update(namespace)
    return builtins
