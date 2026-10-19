"""Reconciliation route (PRP-14 item 4), mounted at ``/api/v1/reconciliation``.

``GET /domains/{domain}?days=1..90`` requires ``data.read`` on the PATH domain, checked against the
server-derived ``IdentityScope`` (403 when outside it; 503 when the policy store is unavailable).
The customer is the scope's, never a request value; a ``customer_id``/``domain_id`` query
parameter is not declared and so cannot widen anything.

This module deliberately has no ``from __future__ import annotations``: FastAPI must see real
annotation objects on the route function.
"""

from datetime import UTC, datetime, timedelta
from typing import Annotated, Final

from fastapi import APIRouter, Depends, Path, Query, Response
from neurosphere_core.aggregates import AggregateReader, AggregateWindow, bucket_start
from neurosphere_core.auth.scope import Permission
from neurosphere_core.scope import IdentityScope

from neurosphere_api.authz import domain_from_path, require
from neurosphere_api.reconciliation.dependencies import get_now, get_reader
from neurosphere_api.reconciliation.models import ReconciliationResponse
from neurosphere_api.reconciliation.service import build_response
from neurosphere_api.routers import RouterRegistry

__all__ = ["PREFIX", "build_router", "register"]

PREFIX: Final = "/api/v1/reconciliation"
_MAX_DOMAIN_LENGTH: Final = 512
_MAX_SERIES: Final = 50  # one series per currency
_MAX_DAYS: Final = 90

_read_domain = require(Permission.DATA_READ, resource=domain_from_path("domain"))


def build_router() -> APIRouter:
    router = APIRouter(tags=["reconciliation"])

    @router.get("/domains/{domain}", response_model=ReconciliationResponse)
    async def reconcile(
        response: Response,
        domain: Annotated[str, Path(min_length=1, max_length=_MAX_DOMAIN_LENGTH)],
        scope: Annotated[IdentityScope, Depends(_read_domain)],
        reader: Annotated[AggregateReader, Depends(get_reader)],
        now: Annotated[datetime, Depends(get_now)],
        days: Annotated[int, Query(ge=1, le=_MAX_DAYS)] = 30,
    ) -> ReconciliationResponse:
        started = datetime.now(UTC)
        today = bucket_start(now, "day")
        window = AggregateWindow(
            start=today - timedelta(days=days - 1), end=today + timedelta(days=1)
        )
        result = await reader.query(
            scope.customer_id,
            domain,
            "reconciliation",
            "day",
            window,
            max_series=_MAX_SERIES,
            max_points=_MAX_DAYS,
        )
        status = await reader.status(scope.customer_id)
        body = build_response(domain, window, result, status, now)
        elapsed_ms = (datetime.now(UTC) - started).total_seconds() * 1000
        response.headers["Server-Timing"] = f"app;dur={elapsed_ms:.1f}"
        return body

    return router


def register(registry: RouterRegistry) -> None:
    registry.register(PREFIX, build_router())
