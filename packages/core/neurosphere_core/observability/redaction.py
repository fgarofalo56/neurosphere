"""Redaction of secrets and sensitive fields before anything reaches a log sink."""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from typing import Any, Final

REDACTED: Final = "[REDACTED]"

# Field names whose values are never logged (compared case-insensitively).
_SENSITIVE_KEYS: Final = frozenset(
    {"prompt", "response", "password", "authorization", "proxy-authorization"}
)

_BEARER = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
_AUTH_HEADER = re.compile(r"""(?i)(\bauthorization["']?\s*[:=]\s*)(?:"[^"]*"|'[^']*'|[^\r\n,;]+)""")
_SAS_SIG = re.compile(r"""(?i)\b(sig=)[^&\s"']+""")
_CONN_KEY = re.compile(r"""(?i)\b(AccountKey|SharedAccessKey|Password|Pwd)(=)[^;\s"']+""")
_SENSITIVE_FIELD = re.compile(
    r"""(?i)\b(prompt|response|password)(["']?\s*[:=]\s*)(?:"[^"]*"|'[^']*'|[^\s,;&]+)"""
)

# Attributes every LogRecord carries; anything else came from `extra=`.
STANDARD_ATTRS: Final = frozenset(
    logging.LogRecord("n", 0, "", 0, "", (), None).__dict__.keys() | {"message", "asctime"}
)


def redact_text(text: str) -> str:
    """Replace bearer tokens, SAS signatures, connection-string secrets and header values."""
    text = _AUTH_HEADER.sub(lambda m: m.group(1) + REDACTED, text)
    text = _BEARER.sub(f"Bearer {REDACTED}", text)
    text = _SAS_SIG.sub(lambda m: m.group(1) + REDACTED, text)
    text = _CONN_KEY.sub(lambda m: m.group(1) + m.group(2) + REDACTED, text)
    return _SENSITIVE_FIELD.sub(lambda m: m.group(1) + m.group(2) + REDACTED, text)


def redact_value(value: Any, *, key: str | None = None) -> Any:
    """Redact recursively; a sensitive key hides its whole value regardless of type."""
    if key is not None and key.lower() in _SENSITIVE_KEYS:
        return REDACTED
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, Mapping):
        return {str(k): redact_value(v, key=str(k)) for k, v in value.items()}  # pyright: ignore
    if isinstance(value, (list, tuple, set, frozenset)):
        return [redact_value(v) for v in value]  # pyright: ignore
    return value


class RedactionFilter(logging.Filter):
    """Rewrites the record in place (message, args and extras) so no handler sees originals."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        safe_args: Any
        if isinstance(args, Mapping):
            safe_args = {k: redact_value(v, key=str(k)) for k, v in args.items()}  # pyright: ignore
        elif args:
            safe_args = tuple(redact_value(a) for a in args)
        else:
            safe_args = ()
        try:
            message = str(record.msg) % safe_args if safe_args else str(record.msg)
        except (TypeError, ValueError, KeyError):
            message = f"{record.msg} {safe_args!r}"
        record.msg = redact_text(message)
        record.args = ()
        for name in tuple(record.__dict__):
            if name not in STANDARD_ATTRS:
                record.__dict__[name] = redact_value(record.__dict__[name], key=name)
        if record.exc_text:
            record.exc_text = redact_text(record.exc_text)
        return True
