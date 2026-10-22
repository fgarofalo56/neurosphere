"""Saved reports / dashboards API (PRP-19 item 5): save, share, add-to-UI approval, run.

Public API:

* :func:`register` -- router hook (prefix ``/api/v1/reports``) for ``RouterRegistry``. Not added
  to ``routers.py`` here; PRP-19 item 7 owns that wiring.
* :func:`configure_reports` -- installs the store, tool registry, clock and optional run cache on
  ``app.state`` (keys in :mod:`neurosphere_api.reports.dependencies`); unset -> 503.
* :class:`InMemoryReportStore` / :class:`CosmosReportStore` -- the two ``ReportStore`` adapters.

A stored report is a chart plan template plus a bounded ``StructuredQuery``; result data is never
stored. Every run re-validates the plan and re-evaluates authorization as the VIEWER.
"""

from neurosphere_api.reports.cache import RunCache, run_cache_key
from neurosphere_api.reports.cosmos_store import (
    DEFAULT_REPORT_CONTAINER,
    REPORT_PARTITION_KEY_PATHS,
    CosmosReportStore,
    create_report_container,
)
from neurosphere_api.reports.dependencies import configure_reports, get_report_service
from neurosphere_api.reports.models import (
    DecisionBody,
    Publication,
    ReportBody,
    ReportList,
    ReportView,
    RunView,
    ShareBody,
    StoredReport,
)
from neurosphere_api.reports.router import PREFIX, build_router, register
from neurosphere_api.reports.service import ReportService
from neurosphere_api.reports.store import InMemoryReportStore, ReportStore

__all__ = [
    "DEFAULT_REPORT_CONTAINER",
    "PREFIX",
    "REPORT_PARTITION_KEY_PATHS",
    "CosmosReportStore",
    "DecisionBody",
    "InMemoryReportStore",
    "Publication",
    "ReportBody",
    "ReportList",
    "ReportService",
    "ReportStore",
    "ReportView",
    "RunCache",
    "RunView",
    "ShareBody",
    "StoredReport",
    "build_router",
    "configure_reports",
    "create_report_container",
    "get_report_service",
    "register",
    "run_cache_key",
]
