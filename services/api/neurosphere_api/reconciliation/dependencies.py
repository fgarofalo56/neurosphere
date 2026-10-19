"""FastAPI dependencies for the reconciliation view (PRP-14 item 4).

* :func:`get_reader` -- ``app.state.aggregate_reader`` (an ``AggregateReader``); fails closed with
  503 when it is unset. Tests override it with ``app.dependency_overrides``.
* :func:`get_now` -- the clock; overridable in tests.

No ``from __future__ import annotations``: FastAPI inspects these signatures.
"""

from datetime import UTC, datetime
from typing import Final

from fastapi import Request
from neurosphere_core.aggregates import AggregateReader
from neurosphere_core.errors import DependencyTransientError

__all__ = ["READER_STATE_KEY", "get_now", "get_reader"]

READER_STATE_KEY: Final = "aggregate_reader"


def get_reader(request: Request) -> AggregateReader:
    reader = getattr(request.app.state, READER_STATE_KEY, None)
    if not isinstance(reader, AggregateReader):
        raise DependencyTransientError(
            "aggregate reader is not configured", reason="aggregate_reader_unconfigured"
        )
    return reader


def get_now() -> datetime:
    return datetime.now(UTC)
