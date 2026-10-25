"""HitlReviewRouter: the HITL-backed ReviewRouter (PRP-29 item 3)."""

from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, datetime

import pytest
from neurosphere_api.recommendations.review import (
    InMemoryReviewRouter,
    ReviewRequest,
    ReviewRouter,
)
from neurosphere_api.recommendations.review_hitl import HitlReviewRouter
from neurosphere_contracts.scope.v1.identity_scope import IdentityScope as ContractScope
from neurosphere_core.audit import AuditRepository, InMemoryAuditStore
from neurosphere_core.auth.scope.permissions import Permission
from neurosphere_core.errors import ForbiddenError, InvalidSchemaError
from neurosphere_core.hitl import (
    DecisionLog,
    HitlService,
    InMemoryDecisionStore,
    InMemoryHitlStore,
    ReviewPolicyRegistry,
    audit_chain_for,
)
from neurosphere_core.scope import IdentityScope

CUSTOMER = "contoso"
DOMAIN = "commercial:contoso:catalog:domain:retail"
OTHER_DOMAIN = "commercial:contoso:catalog:domain:finance"
REC_1 = "commercial:contoso:recommendation:rec:r-0001"
REC_2 = "commercial:contoso:recommendation:rec:r-0002"
NOW = datetime(2026, 10, 24, 9, 0, 0, tzinfo=UTC)


class _NoReviewers:
    async def can_review(
        self, principal_id: str, customer_id: str, domain_id: str, permission: Permission
    ) -> bool:
        return False


def make_scope(domains: tuple[str, ...] = (DOMAIN,), customer: str = CUSTOMER) -> IdentityScope:
    contract = ContractScope.model_validate(
        {
            "schema_version": "1.0.0",
            "cloud": "commercial",
            "customer_id": customer,
            "principal": {
                "principal_id": f"commercial:{customer}:entra:person:psn_0123456789abcdef",
                "principal_pseudonym": "p-7f3a9c21",
                "principal_kind": "user",
            },
            "roles": [],
            "allowed_domains": list(domains),
            "allowed_resources": [],
            "policy_version": "v1",
            "derived_at": "2026-10-10T00:00:00Z",
            "scope_hash": "sha256:" + hashlib.sha256(b"scope").hexdigest(),
        }
    )
    return IdentityScope._from_verified_contract(contract)  # pyright: ignore[reportPrivateUsage]


class Rig:
    def __init__(self) -> None:
        self.store = InMemoryHitlStore()
        self.audit_store = InMemoryAuditStore()
        self.audit = AuditRepository(self.audit_store)
        self.service = HitlService(
            self.store,
            DecisionLog(self.audit, InMemoryDecisionStore()),
            self.audit,
            ReviewPolicyRegistry(),
            _NoReviewers(),
        )
        self.router = HitlReviewRouter(self.service, clock=lambda: NOW)


@pytest.fixture
def rig() -> Rig:
    return Rig()


def test_satisfies_the_review_router_protocol(rig: Rig) -> None:
    assert isinstance(rig.router, ReviewRouter)
    assert isinstance(InMemoryReviewRouter(), ReviewRouter)


async def test_route_opens_one_pending_hitl_item(rig: Rig) -> None:
    created = await rig.router.route(make_scope(), DOMAIN, REC_1)
    assert isinstance(created, ReviewRequest)
    assert created.state == "pending_review"
    item = await rig.service.get(created.review_request_id)
    assert item is not None
    assert (item.kind, item.state_name) == ("recommendation", "pending")
    assert (item.customer_id, item.domain_id, item.subject_ref) == (CUSTOMER, DOMAIN, REC_1)
    assert item.created_at == NOW


async def test_routing_twice_returns_the_same_review_request(rig: Rig) -> None:
    scope = make_scope()
    first = await rig.router.route(scope, DOMAIN, REC_1)
    second = await rig.router.route(scope, DOMAIN, REC_1)
    assert second == first
    assert len((await rig.store.list(scope, DOMAIN)).items) == 1


async def test_concurrent_routes_open_a_single_item(rig: Rig) -> None:
    scope = make_scope()
    results = await asyncio.gather(*(rig.router.route(scope, DOMAIN, REC_1) for _ in range(8)))
    assert len({r.review_request_id for r in results}) == 1
    assert len((await rig.store.list(scope, DOMAIN)).items) == 1


async def test_distinct_recommendations_get_distinct_requests(rig: Rig) -> None:
    scope = make_scope()
    one = await rig.router.route(scope, DOMAIN, REC_1)
    two = await rig.router.route(scope, DOMAIN, REC_2)
    assert one.review_request_id != two.review_request_id


async def test_status_reports_routed_and_unrouted(rig: Rig) -> None:
    scope = make_scope()
    assert await rig.router.status(scope, DOMAIN, REC_1) is None
    created = await rig.router.route(scope, DOMAIN, REC_1)
    assert await rig.router.status(scope, DOMAIN, REC_1) == created
    assert await rig.router.status(scope, DOMAIN, REC_2) is None


async def test_the_item_is_created_through_the_hitl_service_and_audited(rig: Rig) -> None:
    created = await rig.router.route(make_scope(), DOMAIN, REC_1)
    records = await rig.audit.read_range(audit_chain_for(CUSTOMER, DOMAIN), start=0, limit=50)
    operations = [r.operation for r in records]
    assert "hitl.review.open" in operations
    assert any(r.actor.principal_pseudonym == "p-7f3a9c21" for r in records)
    assert (await rig.service.get(created.review_request_id)) is not None


async def test_other_customers_and_domains_do_not_share_requests(rig: Rig) -> None:
    mine = await rig.router.route(make_scope(), DOMAIN, REC_1)
    other_domain = await rig.router.route(make_scope((DOMAIN, OTHER_DOMAIN)), OTHER_DOMAIN, REC_1)
    assert mine.review_request_id != other_domain.review_request_id
    stranger = make_scope(("commercial:fabrikam:catalog:domain:retail",), customer="fabrikam")
    assert await rig.router.status(stranger, DOMAIN, REC_1) is None


async def test_a_domain_outside_the_scope_is_refused_and_nothing_is_created(rig: Rig) -> None:
    with pytest.raises(ForbiddenError):
        await rig.router.route(make_scope(), OTHER_DOMAIN, REC_1)
    assert rig.store._items == {}  # pyright: ignore[reportPrivateUsage]


async def test_an_invalid_recommendation_id_is_a_schema_error(rig: Rig) -> None:
    with pytest.raises(InvalidSchemaError):
        await rig.router.route(make_scope(), DOMAIN, "not a canonical id")
