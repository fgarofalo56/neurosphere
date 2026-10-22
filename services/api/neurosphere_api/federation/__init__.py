"""Cloud-bounded federated summaries (PRP-21 item 3): ``/api/v1/federation``.

Wiring (a later item): call ``neurosphere_api.federation.register(registry)`` and set
``app.state.federation`` to a :class:`FederationState`.
"""

from neurosphere_api.federation.cache import SummaryCache, summary_cache_key
from neurosphere_api.federation.client import (
    CELL_SUMMARY_PATH,
    CellClient,
    HttpCellClient,
    InProcessCellClient,
)
from neurosphere_api.federation.models import CellOutcome, MergedSummary
from neurosphere_api.federation.router import PREFIX, build_router, get_federation, register
from neurosphere_api.federation.service import FederationState, Federator

__all__ = [
    "CELL_SUMMARY_PATH",
    "PREFIX",
    "CellClient",
    "CellOutcome",
    "FederationState",
    "Federator",
    "HttpCellClient",
    "InProcessCellClient",
    "MergedSummary",
    "SummaryCache",
    "build_router",
    "get_federation",
    "register",
    "summary_cache_key",
]
