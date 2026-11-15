"""Two ``HitlReviewRouter`` instances racing over one store open exactly one review item (#133)."""

from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, datetime
from typing import Any

from neurosphere_contracts.scope.v1.identity_scope import IdentityScope as ContractScope
from neurosphere_core.audit import AuditRepository, InMemoryAuditStore
from neurosphere_core.auth.scope.permissions import Permission
from neurosphere_core.hitl import (
    DecisionLog,
    HitlService,
    InMemoryDecisionStore,
    InMemoryHitlStore,
    ReviewPolicyRegistry,
)
from neurosphere_core.scope import IdentityScope

from neurosphere_api.recommendations.review_hitl import HitlReviewRouter, review_item_id

CUSTOMER = "contoso"
DOMAIN = "commercial:contoso:catalog:domain:retail"
REC = "commercial:contoso:recommendation:rec:r-0001"
NOW = datetime(2026, 10, 24, 9, 0, 0, tzinfo=UTC)


class _NoReviewers:
    async def can_review(
        self, principal_id: str, customer_id: str, domain_id: str, permission: Permission
    ) -> bool:
        return False


def _scope() -> IdentityScope:
    contract = ContractScope.model_validate(
        {
            "schema_version": "1.0.0",
            "cloud": "commercial",
            "customer_id": CUSTOMER,
            "principal": {
                "principal_id": f"commercial:{CUSTOMER}:entra:person:psn_0123456789abcdef",
                "principal_pseudonym": "p-7f3a9c21",
                "principal_kind": "user",
            },
            "roles": [],
            "allowed_domains": [DOMAIN],
            "allowed_resources": [],
            "policy_version": "v1",
            "derived_at": "2026-10-10T00:00:00Z",
            "scope_hash": "sha256:" + hashlib.sha256(b"scope").hexdigest(),
        }
    )
    return IdentityScope._from_verified_contract(contract)  # pyright: ignore[reportPrivateUsage]


class _BarrierStore(InMemoryHitlStore):
    """Holds every ``list`` call until ``parties`` callers arrived: both routers have looked, found
    nothing, and only then proceed to open (the worst interleaving of two processes)."""

    def __init__(self, parties: int) -> None:
        super().__init__()
        self._parties = parties
        self._arrived = 0
        self._gate = asyncio.Event()

    async def list(self, *args: Any, **kwargs: Any) -> Any:
        page = await super().list(*args, **kwargs)
        self._arrived += 1
        if self._arrived >= self._parties:
            self._gate.set()
        await self._gate.wait()
        return page


def _service(store: InMemoryHitlStore) -> HitlService:
    audit = AuditRepository(InMemoryAuditStore())
    return HitlService(
        store,
        DecisionLog(audit, InMemoryDecisionStore()),
        audit,
        ReviewPolicyRegistry(),
        _NoReviewers(),
    )


async def test_two_router_instances_open_exactly_one_item() -> None:
    store = _BarrierStore(parties=2)
    # Two routers (two processes), each with its own lock and its own service over one store.
    first = HitlReviewRouter(_service(store), clock=lambda: NOW)
    second = HitlReviewRouter(_service(store), clock=lambda: NOW)
    scope = _scope()
    a, b = await asyncio.gather(first.route(scope, DOMAIN, REC), second.route(scope, DOMAIN, REC))
    assert a.review_request_id == b.review_request_id
    assert a.review_request_id == review_item_id(CUSTOMER, DOMAIN, REC)
    page = await InMemoryHitlStore.list(store, scope, DOMAIN, kind="recommendation", limit=50)
    assert [item.item_id for item in page.items] == [a.review_request_id]


async def test_item_id_is_stable_and_scoped() -> None:
    one = review_item_id(CUSTOMER, DOMAIN, REC)
    assert one == review_item_id(CUSTOMER, DOMAIN, REC)
    assert one != review_item_id("other", DOMAIN, REC)
    assert one != review_item_id(CUSTOMER, DOMAIN + "x", REC)
    assert one != review_item_id(CUSTOMER, DOMAIN, REC + "x")
