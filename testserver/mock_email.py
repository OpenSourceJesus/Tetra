"""Localhost mock webmail API and login page for XHR integration tests."""

from __future__ import annotations

import json
import secrets
import urllib.parse
from typing import Any

USERS: dict[str, str] = {
    "demo": "demo",
    "alice": "secret",
}

MAILBOX: dict[str, list[dict[str, Any]]] = {
    "demo": [
        {
            "id": 1,
            "from": "alice@example.com",
            "subject": "Welcome to MockMail",
            "preview": "Your account is ready. Try opening this message.",
            "body": (
                "Hello demo,\n\n"
                "This message was fetched with a second XMLHttpRequest after login. "
                "The Python browser translated the page JavaScript with Js2Py and "
                "executed each XHR step against this mock server.\n\n"
                "— MockMail"
            ),
        },
        {
            "id": 2,
            "from": "team@example.com",
            "subject": "Pipeline check",
            "preview": "Multi-step XHR: login, inbox, then message detail.",
            "body": (
                "Step 1: POST /api/mail/login\n"
                "Step 2: GET /api/mail/inbox\n"
                "Step 3: GET /api/mail/message/{id}\n\n"
                "If you can read this, the round trip works."
            ),
        },
        {
            "id": 3,
            "from": "noreply@example.com",
            "subject": "Weekly digest",
            "preview": "Three translated scripts, three HTTP calls.",
            "body": "Digest content for offline-browser testing.",
        },
    ],
    "alice": [
        {
            "id": 10,
            "from": "demo@example.com",
            "subject": "Re: Welcome",
            "preview": "Thanks for the invite.",
            "body": "Glad the mock mail server is working.",
        },
    ],
}

SESSIONS: dict[str, str] = {}


def reset_sessions() -> None:
    SESSIONS.clear()


def _parse_form_body(body: bytes) -> dict[str, str]:
    text = body.decode("utf-8", errors="replace")
    if not text.strip():
        return {}
    if text.lstrip().startswith("{"):
        try:
            payload = json.loads(text)
            if isinstance(payload, dict):
                return {str(key): str(value) for key, value in payload.items()}
        except json.JSONDecodeError:
            pass
    return {
        key: urllib.parse.unquote_plus(values[0])
        for key, values in urllib.parse.parse_qs(text, keep_blank_values=True).items()
    }


def _session_user(token: str | None) -> str | None:
    if not token:
        return None
    return SESSIONS.get(token)


def _login(username: str, password: str) -> tuple[int, bytes]:
    user = username.strip()
    expected = USERS.get(user)
    if expected is None or expected != password:
        payload = {"ok": False, "error": "Invalid username or password"}
        return 401, json.dumps(payload).encode("utf-8")

    token = secrets.token_urlsafe(16)
    SESSIONS[token] = user
    payload = {"ok": True, "token": token, "user": user}
    return 200, json.dumps(payload).encode("utf-8")


def _inbox(token: str | None) -> tuple[int, bytes]:
    user = _session_user(token)
    if user is None:
        payload = {"ok": False, "error": "Not authenticated"}
        return 401, json.dumps(payload).encode("utf-8")

    messages = MAILBOX.get(user, [])
    payload = {
        "ok": True,
        "user": user,
        "messages": [
            {
                "id": message["id"],
                "from": message["from"],
                "subject": message["subject"],
                "preview": message["preview"],
            }
            for message in messages
        ],
    }
    return 200, json.dumps(payload).encode("utf-8")


def _message(token: str | None, message_id: str) -> tuple[int, bytes]:
    user = _session_user(token)
    if user is None:
        payload = {"ok": False, "error": "Not authenticated"}
        return 401, json.dumps(payload).encode("utf-8")

    try:
        numeric_id = int(message_id)
    except ValueError:
        payload = {"ok": False, "error": "Invalid message id"}
        return 400, json.dumps(payload).encode("utf-8")

    for message in MAILBOX.get(user, []):
        if message["id"] == numeric_id:
            payload = {
                "ok": True,
                "message": {
                    "id": message["id"],
                    "from": message["from"],
                    "subject": message["subject"],
                    "body": message["body"],
                },
            }
            return 200, json.dumps(payload).encode("utf-8")

    payload = {"ok": False, "error": "Message not found"}
    return 404, json.dumps(payload).encode("utf-8")


def handle_mock_email(
    path: str,
    query: str,
    *,
    method: str = "GET",
    body: bytes = b"",
) -> tuple[int, str, bytes] | None:
    """Return (status, content_type, body) for mock-mail routes, or None."""
    clean = path.rstrip("/") or "/"

    if clean == "/api/mail/login" and method == "POST":
        form = _parse_form_body(body)
        status, payload = _login(form.get("username", ""), form.get("password", ""))
        return status, "application/json; charset=utf-8", payload

    if clean == "/api/mail/inbox" and method == "GET":
        params = urllib.parse.parse_qs(query)
        token = urllib.parse.unquote_plus(params.get("token", [""])[0])
        status, payload = _inbox(token or None)
        return status, "application/json; charset=utf-8", payload

    if clean.startswith("/api/mail/message/") and method == "GET":
        params = urllib.parse.parse_qs(query)
        message_id = urllib.parse.unquote(clean[len("/api/mail/message/") :])
        token = urllib.parse.unquote_plus(params.get("token", [""])[0])
        status, payload = _message(token or None, message_id)
        return status, "application/json; charset=utf-8", payload

    return None
