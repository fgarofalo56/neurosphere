"""FastAPI providers for the evaluation API (PRP-16 item 4).

* :func:`get_evaluation_store` -- ``app.state.evaluation_store`` (an ``EvaluationStore``); fails
  closed with 503 when unset.
* :func:`get_pilot_dataset_ids` -- ``app.state.evaluation_pilot_dataset_ids`` (an iterable of
  dataset ids); empty when unset, which makes the pilot grounded rate not estimable.

No ``from __future__ import annotations``: FastAPI inspects these signatures.
"""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from fastapi import Request
from neurosphere_core.errors import DependencyTransientError
from neurosphere_core.evaluation.store import (
    DEFAULT_QUALITY_MAX_RESULTS,
    DEFAULT_QUALITY_WINDOW_DAYS,
    EvaluationStore,
)

__all__ = ["get_evaluation_store", "get_pilot_dataset_ids", "get_quality_window"]


def get_evaluation_store(request: Request) -> EvaluationStore:
    store = getattr(request.app.state, "evaluation_store", None)
    if not isinstance(store, EvaluationStore):
        raise DependencyTransientError(
            "evaluation store is not configured", reason="evaluation_unconfigured"
        )
    return store


def get_quality_window(request: Request) -> tuple[datetime, int, int]:
    """``(since, window_days, max_results)`` for the bounded ``/quality`` read.

    Defaults: the last 90 days, at most 5000 results. Overridable (deployment bootstrap or tests)
    via ``app.state.evaluation_quality_window_days`` / ``evaluation_quality_max_results`` (positive
    ints; anything else falls back to the default) and ``app.state.evaluation_clock`` (a callable
    returning an aware ``datetime``; default UTC now).
    """
    state = request.app.state
    days = _positive_int(getattr(state, "evaluation_quality_window_days", None))
    cap = _positive_int(getattr(state, "evaluation_quality_max_results", None))
    window_days = days or DEFAULT_QUALITY_WINDOW_DAYS
    clock: Callable[[], datetime] | None = getattr(state, "evaluation_clock", None)
    now = clock() if callable(clock) else datetime.now(UTC)
    return now - timedelta(days=window_days), window_days, cap or DEFAULT_QUALITY_MAX_RESULTS


def _positive_int(value: object) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    return None


def get_pilot_dataset_ids(request: Request) -> frozenset[str]:
    configured = getattr(request.app.state, "evaluation_pilot_dataset_ids", None)
    if not configured or isinstance(configured, str):
        return frozenset()
    return frozenset(str(d) for d in configured)
