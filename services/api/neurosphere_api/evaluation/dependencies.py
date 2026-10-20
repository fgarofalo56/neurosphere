"""FastAPI providers for the evaluation API (PRP-16 item 4).

* :func:`get_evaluation_store` -- ``app.state.evaluation_store`` (an ``EvaluationStore``); fails
  closed with 503 when unset.
* :func:`get_pilot_dataset_ids` -- ``app.state.evaluation_pilot_dataset_ids`` (an iterable of
  dataset ids); empty when unset, which makes the pilot grounded rate not estimable.

No ``from __future__ import annotations``: FastAPI inspects these signatures.
"""

from fastapi import Request
from neurosphere_core.errors import DependencyTransientError
from neurosphere_core.evaluation.store import EvaluationStore

__all__ = ["get_evaluation_store", "get_pilot_dataset_ids"]


def get_evaluation_store(request: Request) -> EvaluationStore:
    store = getattr(request.app.state, "evaluation_store", None)
    if not isinstance(store, EvaluationStore):
        raise DependencyTransientError(
            "evaluation store is not configured", reason="evaluation_unconfigured"
        )
    return store


def get_pilot_dataset_ids(request: Request) -> frozenset[str]:
    configured = getattr(request.app.state, "evaluation_pilot_dataset_ids", None)
    if not configured or isinstance(configured, str):
        return frozenset()
    return frozenset(str(d) for d in configured)
