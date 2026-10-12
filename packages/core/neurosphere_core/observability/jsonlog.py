"""JSON structured log formatter and the single logger factory."""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import IO, Any, Final

from neurosphere_core.observability.redaction import (
    STANDARD_ATTRS,
    RedactionFilter,
    redact_text,
    redact_value,
)

_NS_HANDLER_FLAG: Final = "_ns_handler"


class JsonFormatter(logging.Formatter):
    """One JSON object per line. Redacts again as defence in depth."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": redact_text(record.getMessage()),
        }
        for name, value in record.__dict__.items():
            if name not in STANDARD_ATTRS:
                payload[name] = redact_value(value, key=name)
        if record.exc_info:
            payload["exception"] = redact_text(self.formatException(record.exc_info))
        return json.dumps(payload, default=str)


def get_logger(
    name: str,
    *,
    level: int = logging.INFO,
    stream: IO[str] | None = None,
    redact: bool = True,
) -> logging.Logger:
    """Return a JSON logger with the redaction filter installed (on by default).

    Idempotent per logger name: a second call returns the logger unchanged.
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)
    if any(getattr(h, _NS_HANDLER_FLAG, False) for h in logger.handlers):
        return logger
    handler = logging.StreamHandler(stream if stream is not None else sys.stderr)
    handler.setFormatter(JsonFormatter())
    setattr(handler, _NS_HANDLER_FLAG, True)
    if redact:
        handler.addFilter(RedactionFilter())
        logger.addFilter(RedactionFilter())
    logger.addHandler(handler)
    logger.propagate = False
    return logger
