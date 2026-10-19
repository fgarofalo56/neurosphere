"""Harness for dashboards API tests: the PRP-06 authz harness (dev-issuer tokens, in-memory policy
store) with the real router, an ``InMemoryAggregateStore`` and a fixed clock. No network."""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, cast

import authz.authz_helpers as helpers  # pyright: ignore[reportMissingImports]
from neurosphere_core.aggregates import (
    AggregateStatus,
    CostPoint,
    CoveragePoint,
    ErrorPoint,
    Grain,
    InMemoryAggregateStore,
    LatencyPoint,
    PriceVersionRef,
    aggregate_doc_id,
    format_bucket,
)
from neurosphere_core.auth.scope import Role

from neurosphere_api.dashboards import (
    PREFIX,
    build_router,
    get_aggregate_reader,
    get_analytics_probe,
    get_clock,
)
from neurosphere_api.dashboards.analytics import AnalyticsProbe

__all__ = [
    "ALICE",
    "BOB",
    "FINANCE",
    "NOW",
    "OPERATIONS",
    "Api",
    "cost_point",
    "coverage_point",
    "error_point",
    "latency_point",
    "make_api",
]

ALICE: str = helpers.ALICE
BOB: str = helpers.BOB
CUSTOMER: str = helpers.CUSTOMER
FINANCE: str = helpers.FINANCE
OPERATIONS: str = helpers.OPERATIONS
NOW = datetime(2027, 1, 15, 8, 30, tzinfo=UTC)
METRICS = ("cost", "latency", "errors", "coverage")
VIEWER_FINANCE = ALICE
VIEWER_OPERATIONS = BOB


def day_start(days_ago: int) -> str:
    base = NOW.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days_ago)
    return format_bucket(base)


def _ident(domain: str, metric: str, start: str, key: str) -> dict[str, Any]:
    return {
        "id": aggregate_doc_id(CUSTOMER, domain, metric, "day", start, key),
        "customer_id": CUSTOMER,
        "domain_id": domain,
        "grain": "day",
        "bucket_start": start,
        "series_key": key,
        "watermark": format_bucket(NOW),
    }


def cost_point(
    domain: str,
    days_ago: int,
    amount: str | None,
    *,
    kind: str = "estimated",
    currency: str = "USD",
    complete: bool = True,
    versions: tuple[PriceVersionRef, ...] = (),
) -> CostPoint:
    start = day_start(days_ago)
    key = f"{kind}:{currency}"
    return CostPoint.model_validate(
        {
            **_ident(domain, "cost", start, key),
            "kind": kind,
            "currency": currency,
            "amount": None if amount is None else Decimal(amount),
            "entry_count": 4,
            "known_count": 0 if amount is None else 4,
            "price_versions": list(versions),
            "complete": complete and amount is not None,
        }
    )


def latency_point(
    domain: str, days_ago: int, p50: int | None, p95: int | None, p99: int | None
) -> LatencyPoint:
    start = day_start(days_ago)
    return LatencyPoint.model_validate(
        {
            **_ident(domain, "latency", start, "latency"),
            "sample_count": 10,
            "missing_count": 0,
            "p50_ms": p50,
            "p95_ms": p95,
            "p99_ms": p99,
            "complete": None not in (p50, p95, p99),
        }
    )


def error_point(
    domain: str,
    days_ago: int,
    errors: int | None,
    requests: int,
    rate: float | None,
) -> ErrorPoint:
    start = day_start(days_ago)
    return ErrorPoint.model_validate(
        {
            **_ident(domain, "errors", start, "errors"),
            "request_count": requests,
            "unknown_count": 0,
            "error_count": errors,
            "error_rate": rate,
            "complete": errors is not None,
        }
    )


def coverage_point(
    domain: str, days_ago: int, known: int, entries: int, coverage: float | None
) -> CoveragePoint:
    start = day_start(days_ago)
    return CoveragePoint.model_validate(
        {
            **_ident(domain, "coverage", start, "USD"),
            "currency": "USD",
            "entry_count": entries,
            "known_count": known,
            "unresolved_count": 0,
            "unknown_count": entries - known,
            "coverage": coverage,
            "complete": known == entries,
        }
    )


@dataclass
class Api:
    h: Any
    store: InMemoryAggregateStore

    def seed(self, *points: Any) -> None:
        async def run() -> None:
            buckets: dict[tuple[str, str, str, str], list[Any]] = {}
            for point in points:  # a bucket's documents are replaced together
                key = (point.customer_id, point.domain_id, point.grain, point.bucket_start)
                buckets.setdefault(key, []).append(point)
            for (customer, domain, grain, start), docs in buckets.items():
                await self.store.replace_bucket(customer, domain, cast(Grain, grain), start, docs)

        asyncio.run(run())

    def set_status(self, *, watermark: str | None, billing: str | None = None) -> None:
        asyncio.run(
            self.store.put_status(
                AggregateStatus(
                    customer_id=CUSTOMER, watermark=watermark, billing_observed_at=billing
                )
            )
        )

    def use_reader(self, reader: object) -> None:
        self.h.app.dependency_overrides[get_aggregate_reader] = lambda: reader

    def use_analytics(self, probe: AnalyticsProbe) -> None:
        self.h.app.dependency_overrides[get_analytics_probe] = lambda: probe

    def get(self, who: str | None, domain: str, metric: str, **params: Any) -> Any:
        headers = self.h.auth(who) if who else {}
        return self.h.client.get(
            f"{PREFIX}/domains/{domain}/{metric}", params=params or None, headers=headers
        )


def make_api(*, clock: Callable[[], datetime] | None = None) -> Api:
    h = helpers.harness(
        helpers.policy(VIEWER_FINANCE, helpers.role(Role.VIEWER, FINANCE)),
        helpers.policy(VIEWER_OPERATIONS, helpers.role(Role.VIEWER, OPERATIONS)),
        routers={PREFIX: build_router()},
    )
    store = InMemoryAggregateStore()
    fixed = clock or (lambda: NOW)
    h.app.dependency_overrides[get_aggregate_reader] = lambda: store
    h.app.dependency_overrides[get_clock] = lambda: fixed
    return Api(h=h, store=store)
