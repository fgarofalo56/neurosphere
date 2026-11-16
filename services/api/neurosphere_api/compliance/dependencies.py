"""FastAPI providers for the compliance API (PRP-56 item 5).

The evidence sources read the existing stores from ``app.state`` and are built per request. A
store that is not configured does not fail the request: its source reports ``unavailable`` and
the bundle says so. The control library is package data; if it cannot load the route answers 503.

No ``from __future__ import annotations``: FastAPI inspects these signatures.
"""

import functools
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from fastapi import Request
from neurosphere_core.compliance import ControlLibrary, LibraryLoadError, load_library
from neurosphere_core.compliance.sources import (
    AuditChainSource,
    CatalogOwnershipSource,
    ConfigurationFindingsSource,
    CostAttributionSource,
    EvaluationResultsSource,
    EvidenceSource,
    HitlDecisionsSource,
)
from neurosphere_core.errors import DependencyTransientError

__all__ = ["Clock", "get_clock", "get_library", "get_sources"]

Clock = Callable[[], datetime]


@functools.cache
def _library() -> ControlLibrary:
    return load_library()


def get_library() -> ControlLibrary:
    try:
        return _library()
    except LibraryLoadError:
        raise DependencyTransientError(
            "compliance library is unavailable", reason="compliance_library_unavailable"
        ) from None


def _utc_now() -> datetime:
    return datetime.now(UTC)


def get_clock() -> Clock:
    return _utc_now


def get_sources(request: Request) -> list[EvidenceSource]:
    state: Any = request.app.state
    hitl_service = getattr(state, "hitl_service", None)
    return [
        CatalogOwnershipSource(getattr(state, "catalog_repository", None)),
        AuditChainSource(getattr(state, "audit_repository", None)),
        HitlDecisionsSource(getattr(hitl_service, "store", None)),
        EvaluationResultsSource(getattr(state, "evaluation_store", None)),
        CostAttributionSource(getattr(state, "ledger_store", None)),
        ConfigurationFindingsSource(getattr(state, "recommendation_store", None)),
    ]
