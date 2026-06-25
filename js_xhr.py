"""XMLHttpRequest for Js2Py-translated page scripts."""

from __future__ import annotations

import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable

from navigation import BROWSER_UA

from js_objects import Js, JsFunction, _key, _unwrap, call_value


def resolve_url(url: str, base: str) -> str:
    url = url.strip()
    if url.startswith(("http://", "https://")):
        return url
    if url.startswith("//"):
        scheme = urllib.parse.urlparse(base).scheme or "http"
        return f"{scheme}:{url}"
    if base:
        return urllib.parse.urljoin(base, url)
    if url.startswith("/"):
        return f"http://127.0.0.1:8765{url}"
    return url


def _handler(value: Any) -> Callable | None:
    if isinstance(value, JsFunction):
        return value.value
    if callable(value):
        return value
    return None


class JsXMLHttpRequest:
    def __init__(self, page_url: str = ""):
        self.page_url = page_url
        self._method = "GET"
        self._url = ""
        self._async = True
        self._headers: dict[str, str] = {}
        self.ready_state = 0
        self.status = 0
        self.response_text = ""
        self.response = ""
        self._onload: Callable | None = None
        self._onerror: Callable | None = None
        self._onreadystatechange: Callable | None = None

    def get(self, key: Any) -> Any:
        name = _key(key)
        if name == "readyState":
            return Js(float(self.ready_state))
        if name == "status":
            return Js(float(self.status))
        if name == "responseText":
            return Js(self.response_text)
        if name == "response":
            return Js(self.response)
        if name == "onload":
            return JsFunction(self._onload) if self._onload else Js(None)
        if name == "onerror":
            return JsFunction(self._onerror) if self._onerror else Js(None)
        if name == "onreadystatechange":
            return JsFunction(self._onreadystatechange) if self._onreadystatechange else Js(None)
        return Js(None)

    def put(self, key: Any, val: Any, op: str | None = None) -> Any:
        name = _key(key)
        if name == "onload":
            self._onload = _handler(val)
        elif name == "onerror":
            self._onerror = _handler(val)
        elif name == "onreadystatechange":
            self._onreadystatechange = _handler(val)
        return _wrap_xhr(val)

    def callprop(self, name: str, *args: Any) -> Any:
        name = _key(name)
        if name == "open":
            self._method = str(_unwrap(args[0])).upper()
            self._url = str(_unwrap(args[1]))
            if len(args) > 2:
                self._async = bool(_unwrap(args[2]))
            self._set_ready_state(1)
            return Js(None)
        if name == "send":
            body = _unwrap(args[0]) if args else None
            self._send(body)
            return Js(None)
        if name == "setRequestHeader":
            self._headers[str(_unwrap(args[0]))] = str(_unwrap(args[1]))
            return Js(None)
        if name == "abort":
            self._set_ready_state(0)
            return Js(None)
        return Js(None)

    def create(self, *_args: Any, **_kwargs: Any) -> JsXMLHttpRequest:
        return JsXMLHttpRequest(self.page_url)

    def _set_ready_state(self, state: int) -> None:
        self.ready_state = state
        if self._onreadystatechange:
            call_value(self._onreadystatechange, [])

    def _send(self, body: Any) -> None:
        url = resolve_url(self._url, self.page_url)
        payload = None
        if body is not None and body != "":
            payload = body.encode("utf-8") if isinstance(body, str) else bytes(body)

        self._set_ready_state(2)
        try:
            request = urllib.request.Request(
                url,
                data=payload if self._method not in {"GET", "HEAD"} else None,
                method=self._method,
                headers={"User-Agent": BROWSER_UA, **self._headers},
            )
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read()
                self.status = response.status
                self.response_text = raw.decode("utf-8", errors="replace")
                self.response = self.response_text
            self._set_ready_state(4)
            if self._onload and 200 <= self.status < 300:
                call_value(self._onload, [])
        except urllib.error.HTTPError as exc:
            self.status = exc.code
            self.response_text = exc.read().decode("utf-8", errors="replace")
            self.response = self.response_text
            self._set_ready_state(4)
            if self._onerror:
                call_value(self._onerror, [])
        except Exception:
            self.status = 0
            self.response_text = ""
            self.response = ""
            self._set_ready_state(4)
            if self._onerror:
                call_value(self._onerror, [])


def _wrap_xhr(value: Any) -> Any:
    return value


def xhr_constructor(page_url: str) -> JsFunction:
    def factory(*_args: Any, **_kwargs: Any) -> JsXMLHttpRequest:
        return JsXMLHttpRequest(page_url)

    return JsFunction(factory)
