"""FastAPI providers for the reports API (PRP-19 item 5).

=========================  ==================================================================
``app.state`` key          Type
=========================  ==================================================================
``report_store``           :class:`~neurosphere_api.reports.store.ReportStore` (required)
``report_tool_registry``   ``neurosphere_core.copilot.tools.ToolRegistry`` (required; the same
                           bounded registry the copilot uses)
``report_clock``           optional ``() -> datetime`` (aware; default UTC now)
``report_run_cache``       optional :class:`~neurosphere_api.reports.cache.RunCache`
=========================  ==================================================================

Missing or mistyped required keys fail closed with 503 ``reports_unconfigured``. No
``from __future__ import annotations``: FastAPI inspects these signatures.
"""

from fastapi import FastAPI, Request
from neurosphere_core.copilot.tools import ToolRegistry
from neurosphere_core.errors import DependencyTransientError

from neurosphere_api.reports.cache import RunCache
from neurosphere_api.reports.service import Clock, ReportService
from neurosphere_api.reports.store import ReportStore

__all__ = ["configure_reports", "get_report_service"]

_UNCONFIGURED = "reports_unconfigured"


def get_report_service(request: Request) -> ReportService:
    state = request.app.state
    store = getattr(state, "report_store", None)
    registry = getattr(state, "report_tool_registry", None)
    if not isinstance(store, ReportStore) or not isinstance(registry, ToolRegistry):
        raise DependencyTransientError("reports are not configured", reason=_UNCONFIGURED)
    cache = getattr(state, "report_run_cache", None)
    if cache is not None and not isinstance(cache, RunCache):
        raise DependencyTransientError("reports are not configured", reason=_UNCONFIGURED)
    clock: Clock | None = getattr(state, "report_clock", None)
    if clock is None:
        return ReportService(store, registry, cache=cache)
    return ReportService(store, registry, clock=clock, cache=cache)


def configure_reports(
    app: FastAPI,
    *,
    store: ReportStore,
    tool_registry: ToolRegistry,
    clock: Clock | None = None,
    run_cache: RunCache | None = None,
) -> None:
    """Install the report collaborators on ``app.state`` (one call for PRP-19 item 7)."""
    app.state.report_store = store
    app.state.report_tool_registry = tool_registry
    app.state.report_clock = clock
    app.state.report_run_cache = run_cache
