from __future__ import annotations

import json
import logging
import re
import sys
from typing import Any

from lyren_core.ids import current_request_id

_SECRET_PATTERNS = (
    re.compile(r"(ocid1\.[a-z]+\.oc1\.\.)[a-z0-9]{10,}", re.IGNORECASE),
    re.compile(r"(Bearer\s+)[A-Za-z0-9._\-]{8,}"),
    re.compile(r"(sk-|gho_|ghp_)[A-Za-z0-9_\-]{8,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
)


def redact(text: str) -> str:
    out = text
    for pattern in _SECRET_PATTERNS:
        out = pattern.sub(lambda m: f"{m.group(1) if m.groups() else ''}<redacted>", out)
    return out


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": redact(record.getMessage()),
            "request_id": current_request_id(),
        }
        extra = getattr(record, "fields", None)
        if isinstance(extra, dict):
            payload.update(extra)
        if record.exc_info:
            payload["exception"] = redact(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())
