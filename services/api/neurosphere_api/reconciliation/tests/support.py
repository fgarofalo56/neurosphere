"""Builders: synthetic contributions, rolled up by the real rollup, in the in-memory store."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from authz.authz_helpers import (  # pyright: ignore[reportMissingImports]
    ALICE,
    CUSTOMER,
    FINANCE,
    Harness,
    harness,
    policy,
    role,
)
from fastapi.testclient import TestClient
from neurosphere_core.aggregates import (
    AllocationFact,
    Contribution,
    EntryFact,
    InMemoryAggregateStore,
    SourceFact,
)
from neurosphere_core.aggregates.models import SourceName
from neurosphere_core.auth.scope import Role
from neurosphere_workers.aggregates.rollups import rollup_bucket

from neurosphere_api.reconciliation import PREFIX, build_router, get_now

NOW = datetime(2026, 10, 19, 12, 0, 0, tzinfo=UTC)
DAY = datetime(2026, 10, 18, tzinfo=UTC)
STAMP = "2026-10-18T10:00:00Z"
ReportedBy = dict[SourceName, str | None]


def entry(
    key: str,
    amount: str | None,
    reported: ReportedBy,
    *,
    currency: str = "USD",
    customer: str = CUSTOMER,
    domain: str = FINANCE,
) -> Contribution:
    """One ledger entry. ``reported`` maps source to its amount (None: reported, unknown)."""
    facts = [
        SourceFact(
            source=source,
            amount=None if value is None else Decimal(value),
            known=value is not None,
        )
        for source, value in reported.items()
    ]
    return Contribution(
        id=f"entry-{key}",
        customer_id=customer,
        domain_id=domain,
        origin="ledger_entry",
        occurred_at=STAMP,
        observed_at=STAMP,
        entry=EntryFact(
            currency=currency,
            amount=None if amount is None else Decimal(amount),
            sources=facts,
        ),
    )


def vendor_allocation(
    key: str, amount: str, *, currency: str = "USD", domain: str = FINANCE
) -> Contribution:
    return Contribution(
        id=f"alloc-{key}",
        customer_id=CUSTOMER,
        domain_id=domain,
        origin="allocation",
        occurred_at=STAMP,
        observed_at=STAMP,
        billing_observed_at=STAMP,
        allocation=AllocationFact(
            source="billing", granularity="vendor", currency=currency, amount=Decimal(amount)
        ),
    )


async def _fill(store: InMemoryAggregateStore, contributions: list[Contribution]) -> None:
    by_scope: dict[tuple[str, str], list[Contribution]] = {}
    for c in contributions:
        by_scope.setdefault((c.customer_id, c.domain_id), []).append(c)
    for (customer, domain), group in by_scope.items():
        docs = rollup_bucket(customer, domain, "day", DAY, group)
        await store.replace_bucket(customer, domain, "day", docs[0].bucket_start, docs)


def make_store(*contributions: Contribution) -> InMemoryAggregateStore:
    store = InMemoryAggregateStore()
    asyncio.run(_fill(store, list(contributions)))
    return store


def make_api(store: Any, *, viewer_of: str = FINANCE) -> tuple[Harness, TestClient]:
    h = harness(
        policy(ALICE, role(Role.VIEWER, viewer_of)),
        routers={PREFIX: build_router()},
    )
    h.app.state.aggregate_reader = store
    h.app.dependency_overrides[get_now] = lambda: NOW
    return h, h.client


def fetch(h: Harness, client: TestClient, domain: str = FINANCE, **params: Any) -> dict[str, Any]:
    response = client.get(f"{PREFIX}/domains/{domain}", params=params, headers=h.auth(ALICE))
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body
