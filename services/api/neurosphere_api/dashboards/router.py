"""Dashboards route (PRP-14 item 2), mounted at ``/api/v1/dashboards``.

| Method | Path                                  | Permission  |
|--------|---------------------------------------|-------------|
| GET    | ``/domains/{domain}/{metric}``        | ``data.read`` |

The path ``{domain}`` is the addressed resource and the authorization TARGET: ``require`` checks
``data.read`` on exactly that domain against the scope derived from the bearer token, so a caller
outside the domain gets 403 (never an empty 200), a policy-store outage 503. ``customer_id`` comes
only from the derived ``IdentityScope``; query parameters named ``customer_id`` or ``domain_id``
are not read. Data comes only from ``AggregateReader`` (hot aggregates): never the ledger and never
the analytics adapter, so the endpoint keeps serving when analytics is stopped.

Budgets: ``days`` 1-90, ``grain`` day|hour (hour at most 14 days), ``max_series`` 1-50,
``max_points`` 1-2160. Out-of-range values are 422 and ``truncated`` reports a cut result.

No ``from __future__ import annotations``: FastAPI inspects these signatures.
"""

import time
from collections.abc import Callable, Coroutine
from datetime import timedelta
from typing import Annotated, Any, Final

from fastapi import APIRouter, Depends, Path, Query, Request, Response
from fastapi.routing import APIRoute
from neurosphere_core.aggregates import (
    HOUR_RETENTION_DAYS,
    MAX_POINTS_CEILING,
    MAX_SERIES_CEILING,
    AggregateReader,
    AggregateWindow,
    bucket_start,
    format_bucket,
)
from neurosphere_core.auth.scope import Permission
from neurosphere_core.errors import DependencyTransientError, InvalidSchemaError, NeuroSphereError
from neurosphere_core.scope import IdentityScope

from neurosphere_api.authz import domain_from_path, require
from neurosphere_api.dashboards.analytics import AnalyticsProbe, resolve_analytics
from neurosphere_api.dashboards.dependencies import (
    Clock,
    get_aggregate_reader,
    get_analytics_probe,
    get_clock,
)
from neurosphere_api.dashboards.mapping import map_result
from neurosphere_api.dashboards.models import (
    DashboardResponse,
    Freshness,
    GrainName,
    MetricName,
    Window,
)
from neurosphere_api.routers import RouterRegistry

__all__ = ["PREFIX", "SERVER_TIMING", "build_router", "register"]

PREFIX: Final = "/api/v1/dashboards"
SERVER_TIMING: Final = "Server-Timing"

ReadScope = Annotated[
    IdentityScope, Depends(require(Permission.DATA_READ, domain_from_path("domain")))
]
Reader = Annotated[AggregateReader, Depends(get_aggregate_reader)]
Probe = Annotated[AnalyticsProbe, Depends(get_analytics_probe)]
Now = Annotated[Clock, Depends(get_clock)]
DomainPath = Annotated[str, Path(min_length=1, max_length=512)]
Days = Annotated[int, Query(ge=1, le=90)]
MaxSeries = Annotated[int, Query(ge=1, le=MAX_SERIES_CEILING)]
MaxPoints = Annotated[int, Query(ge=1, le=MAX_POINTS_CEILING)]


class TimedRoute(APIRoute):
    """Adds ``Server-Timing: app;dur=<ms>`` to every response the handler produces."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        original = super().get_route_handler()

        async def timed(request: Request) -> Response:
            started = time.perf_counter()
            response = await original(request)
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            response.headers[SERVER_TIMING] = f"app;dur={elapsed_ms:.1f}"
            return response

        return timed


def _window(now_end: AggregateWindow) -> Window:
    return Window(start=format_bucket(now_end.start), end=format_bucket(now_end.end))


def build_router() -> APIRouter:
    router = APIRouter(tags=["dashboards"], route_class=TimedRoute)

    @router.get("/domains/{domain}/{metric}", response_model=DashboardResponse)
    async def get_dashboard(
        domain: DomainPath,
        metric: MetricName,
        scope: ReadScope,
        reader: Reader,
        probe: Probe,
        clock: Now,
        days: Days = 30,
        grain: GrainName = "day",
        max_series: MaxSeries = 20,
        max_points: MaxPoints = 720,
    ) -> DashboardResponse:
        if grain == "hour" and days > HOUR_RETENTION_DAYS:
            raise InvalidSchemaError(
                f"the hour grain is limited to {HOUR_RETENTION_DAYS} days", reason="hour_window"
            )
        step = timedelta(days=1) if grain == "day" else timedelta(hours=1)
        end = bucket_start(clock(), grain) + step
        window = AggregateWindow(start=end - timedelta(days=days), end=end)
        customer_id = scope.customer_id  # derived scope only; never a request value
        try:
            result = await reader.query(
                customer_id,
                domain,
                metric,
                grain,
                window,
                max_series=max_series,
                max_points=max_points,
            )
            status = await reader.status(customer_id)
        except NeuroSphereError:
            raise
        except Exception as exc:
            raise DependencyTransientError(
                "aggregates are unavailable", reason="aggregates_unavailable"
            ) from exc
        lag = status.lag_seconds(clock()) if status is not None else None
        mapped = map_result(metric, result)
        analytics = await resolve_analytics(probe, lag)
        return DashboardResponse(
            metric=metric,
            domain_id=domain,
            grain=grain,
            window=_window(window),
            freshness=Freshness(
                watermark=status.watermark if status is not None else None,
                lag_seconds=lag,
                billing_source_freshness=status.billing_observed_at if status is not None else None,
            ),
            analytics=analytics,
            complete=bool(mapped.series)
            and not result.truncated
            and all(s.total.complete for s in mapped.series),
            truncated=result.truncated,
            series=mapped.series,
            price_versions=mapped.price_versions,
        )

    return router


def register(registry: RouterRegistry) -> None:
    registry.register(PREFIX, build_router())
