from __future__ import annotations

import contextvars
import uuid

_request_id: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")


def new_request_id() -> str:
    return f"req_{uuid.uuid4().hex[:24]}"


def set_request_id(value: str) -> None:
    _request_id.set(value)


def current_request_id() -> str:
    return _request_id.get()
