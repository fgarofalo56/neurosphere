"""Evaluation quality API (PRP-16 item 4): scoped results and the quality summary.

Public API:

* :func:`register` -- router hook (prefix ``/api/v1/evaluation``) for ``RouterRegistry``.
  Not added to ``routers.py`` here; PRP-16 item 6 owns that wiring.
* :func:`get_evaluation_store` -- reads ``app.state.evaluation_store`` (503 when unset).
* ``app.state.evaluation_pilot_dataset_ids`` -- optional iterable of pilot dataset ids; empty or
  unset makes the pilot grounded rate not estimable.

Read-only. A judge score is never shown without its judge version, calibration state and
uncertainty.
"""

from neurosphere_api.evaluation.dependencies import get_evaluation_store, get_pilot_dataset_ids
from neurosphere_api.evaluation.quality import compute_quality, pilot_grounded_rate
from neurosphere_api.evaluation.router import PREFIX, build_router, register

__all__ = [
    "PREFIX",
    "build_router",
    "compute_quality",
    "get_evaluation_store",
    "get_pilot_dataset_ids",
    "pilot_grounded_rate",
    "register",
]
