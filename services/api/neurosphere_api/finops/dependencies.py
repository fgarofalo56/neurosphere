"""FastAPI providers for the FinOps API (PRP-21 item 4).

* :func:`get_ledger_store` -- ``app.state.ledger_store`` (a ``LedgerStore``); fails closed with
  503 when unset. Tests use ``app.dependency_overrides``.
* :func:`get_clock` -- UTC now, overridable in tests.

No ``from __future__ import annotations``: FastAPI inspects these signatures.
"""

from collections.abc import Callable
from datetime import UTC, datetime

from fastapi import Request
from neurosphere_core.errors import DependencyTransientError
from neurosphere_core.ledger import LedgerStore

__all__ = ["Clock", "get_clock", "get_ledger_store"]

Clock = Callable[[], datetime]


def get_ledger_store(request: Request) -> LedgerStore:
    store = getattr(request.app.state, "ledger_store", None)
    if not isinstance(store, LedgerStore):
        raise DependencyTransientError(
            "ledger store is not configured", reason="ledger_unconfigured"
        )
    return store


def _utc_now() -> datetime:
    return datetime.now(UTC)


def get_clock() -> Clock:
    return _utc_now
