"""Request-scoped message language for user-facing backend text.

The UI sends ``Accept-Language`` with every request. Korean is the source language and the default, so callers
that send no header (scripts, tests) keep getting Korean. Use ``tr(korean, english)`` where a message reaches the user.
"""
from __future__ import annotations

from contextvars import ContextVar
from typing import Literal

Locale = Literal["ko", "en"]

_current: ContextVar[Locale] = ContextVar("clone_voice_locale", default="ko")


def current_locale() -> Locale:
    return _current.get()


def set_locale(locale: Locale):
    """Set the language for the current context and return the token for ``reset_locale``."""
    return _current.set(locale)


def reset_locale(token) -> None:
    _current.reset(token)


def parse_accept_language(header: str | None) -> Locale:
    """Pick ko or en from an Accept-Language value; anything unknown or missing falls back to Korean."""
    for part in (header or "").split(","):
        language = part.split(";", 1)[0].strip().lower()
        if language.startswith("ko"):
            return "ko"
        if language.startswith("en"):
            return "en"
    return "ko"


def tr(korean: str, english: str) -> str:
    return english if _current.get() == "en" else korean


class LocaleMiddleware:
    """Pure ASGI middleware, so the language also reaches worker threads started from the request."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] not in {"http", "websocket"}:
            await self.app(scope, receive, send)
            return
        header = next((value.decode("latin-1") for name, value in scope.get("headers", []) if name == b"accept-language"), None)
        token = set_locale(parse_accept_language(header))
        try:
            await self.app(scope, receive, send)
        finally:
            reset_locale(token)
