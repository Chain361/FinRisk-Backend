# -*- coding: utf-8 -*-
"""Best-effort error/debug logging with PII-conscious masking."""

from __future__ import annotations

import hashlib
import logging
import re

log = logging.getLogger("finrisk.error_log")

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_LONG_DIGIT_RE = re.compile(r"\b\d{6,}\b")
_TOKEN_RE = re.compile(
    r"(?i)\b(password|passwd|pwd|token|secret|api[_-]?key|authorization|bearer)\b\s*[:=]\s*\S+"
)
_MAX_MESSAGE_LENGTH = 500


def sanitize_log_text(value: str | None) -> str | None:
    """Mask common sensitive patterns and cap message length before DB storage."""
    if value is None:
        return None
    sanitized = _TOKEN_RE.sub(r"\1=[MASKED]", value)
    sanitized = _EMAIL_RE.sub("[EMAIL]", sanitized)
    sanitized = _LONG_DIGIT_RE.sub("[NUMBER]", sanitized)
    if len(sanitized) > _MAX_MESSAGE_LENGTH:
        sanitized = sanitized[: _MAX_MESSAGE_LENGTH - 3] + "..."
    return sanitized


def _stack_hash(exc: Exception | None) -> str | None:
    if exc is None:
        return None
    signature = f"{type(exc).__module__}.{type(exc).__name__}:{exc}"
    return hashlib.sha256(signature.encode("utf-8", errors="replace")).hexdigest()


def record_error_debug(
    *,
    level: str,
    logger_name: str,
    message: str,
    method: str | None,
    path: str | None,
    status_code: int | None,
    username: str | None,
    request_id: str | None,
    exc: Exception | None = None,
    connect,
) -> None:
    """
    Insert one error/debug log row, best-effort.

    Never stores request body or query string. `path` should be `request.url.path`.
    """
    try:
        conn = connect()
        try:
            conn.execute(
                """INSERT INTO error_debug_log
                   (level, logger_name, message, error_type, method, path,
                    status_code, username, request_id, stack_hash)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    level,
                    logger_name,
                    sanitize_log_text(message) or "",
                    type(exc).__name__ if exc else None,
                    method,
                    path,
                    status_code,
                    username,
                    sanitize_log_text(request_id),
                    _stack_hash(exc),
                ),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception as insert_exc:  # noqa: BLE001 - logging must never break requests
        log.debug("error_debug_log write skipped: %s", insert_exc)
