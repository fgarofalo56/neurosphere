"""FinOps forecast API (PRP-21 item 4): simple trend forecast over ledger aggregates.

Public API:

* :func:`register` -- router hook (prefix ``/api/v1/finops``) for ``RouterRegistry``. Not yet
  attached in ``routers.py``; the wiring item adds it to ``REGISTERED``.
* :func:`build_forecast` -- the computation, shared by the router and the evidence hook.
* :func:`get_ledger_store` -- provider reading ``app.state.ledger_store`` (503 when unset).
"""

from neurosphere_api.finops.dependencies import get_clock, get_ledger_store
from neurosphere_api.finops.models import ForecastResponse
from neurosphere_api.finops.router import PREFIX, build_router, register
from neurosphere_api.finops.service import build_forecast

__all__ = [
    "PREFIX",
    "ForecastResponse",
    "build_forecast",
    "build_router",
    "get_clock",
    "get_ledger_store",
    "register",
]
