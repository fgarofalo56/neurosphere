"""Shared fixtures for HITL tests: principals, a fake authorizer, clocks and a service harness."""

from __future__ import annotations

import hashlib
import itertools
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from neurosphere_contracts.actions.v1.actor import Actor
from neurosphere_core.audit import AuditRepository, InMemoryAuditStore
from neurosphere_core.auth.scope.permissions import Permission
from neurosphere_core.errors import DependencyTransientError
from neurosphere_core.hitl import (
    DecisionLog,
    HitlService,
    InMemoryDecisionStore,
    InMemoryHitlStore,
    Notifier,
    ReviewItem,
    ReviewKind,
    ReviewPolicyRegistry,
)

CUSTOMER = "contoso"
DOMAIN = "commercial:contoso:catalog:domain:retail"
OTHER_DOMAIN = "commercial:contoso:catalog:domain:finance"
CHAIN = "contoso.retail"
TARGET = "commercial:contoso:foundry:model_deployment:eastus2/chat-prod"
EDGE = "commercial:contoso:catalog:edge:e-0001"
SCOPE_HASH = "sha256:" + hashlib.sha256(b"scope").hexdigest()
CONFIRMATION = "sha256:" + hashlib.sha256(b"intent-1").hexdigest()
OTHER_CONFIRMATION = "sha256:" + hashlib.sha256(b"intent-2").hexdigest()
INTENT_ID = "11111111-1111-4111-8111-111111111111"
T0 = datetime(2026, 10, 20, 9, 0, 0, tzinfo=UTC)

MAKER_ID = "commercial:contoso:entra:person:psn_maker000000001"
CHECKER_ID = "commercial:contoso:entra:person:psn_checker00000002"
THIRD_ID = "commercial:contoso:entra:person:psn_third000000003"
AGENT_ID = "commercial:contoso:entra:agent:agt_copilot0000004"


def actor(pseudonym: str, kind: str = "user", on_behalf_of: str | None = None) -> Actor:
    return Actor.model_validate(
        {"principal_pseudonym": pseudonym, "principal_kind": kind, "on_behalf_of": on_behalf_of}
    )


MAKER = actor("p-maker")
CHECKER = actor("p-checker")
THIRD = actor("p-third")


def sequential_ids(prefix: str = "00000000-0000-4000-8000") -> Callable[[], str]:
    counter = itertools.count(1)
    return lambda: f"{prefix}-{next(counter):012d}"


class StepClock:
    """Each call advances one millisecond (for the audit repository)."""

    def __init__(self, start: datetime = T0) -> None:
        self._now = start

    def __call__(self) -> datetime:
        self._now += timedelta(milliseconds=1)
        return self._now


@dataclass
class FakeAuthorizer:
    """Grants by real principal id. Records every question; ``outage`` raises 503."""

    grants: dict[str, set[Permission]] = field(default_factory=dict)
    outage: bool = False
    calls: list[tuple[str, str, str, Permission]] = field(default_factory=list)

    async def can_review(
        self, principal_id: str, customer_id: str, domain_id: str, permission: Permission
    ) -> bool:
        self.calls.append((principal_id, customer_id, domain_id, permission))
        if self.outage:
            raise DependencyTransientError("policy store down", reason="policy_store_unavailable")
        return domain_id == DOMAIN and permission in self.grants.get(principal_id, set())


STEWARD = {Permission.ACTION_APPROVE, Permission.CATALOG_CURATE}


def default_grants() -> dict[str, set[Permission]]:
    return {MAKER_ID: set(STEWARD), CHECKER_ID: set(STEWARD), THIRD_ID: set(STEWARD)}


@dataclass
class Harness:
    service: HitlService
    store: InMemoryHitlStore
    audit_store: InMemoryAuditStore
    audit: AuditRepository
    decision_store: InMemoryDecisionStore
    decisions: DecisionLog
    authorizer: FakeAuthorizer

    async def records(self) -> list[dict[str, object]]:
        found = await self.audit.read_range(CHAIN, start=0, limit=500)
        return [r.model_dump(mode="json") for r in found]


def build(
    *,
    grants: Mapping[str, set[Permission]] | None = None,
    policies: ReviewPolicyRegistry | None = None,
    notifiers: Callable[[AuditRepository], Sequence[Notifier]] | None = None,
    store: InMemoryHitlStore | None = None,
    audit_store: InMemoryAuditStore | None = None,
) -> Harness:
    audit_store = audit_store or InMemoryAuditStore()
    audit = AuditRepository(audit_store, clock=StepClock(), id_factory=sequential_ids())
    decision_store = InMemoryDecisionStore()
    decisions = DecisionLog(audit, decision_store)
    authorizer = FakeAuthorizer(grants=dict(grants) if grants is not None else default_grants())
    hitl_store = store or InMemoryHitlStore()
    service = HitlService(
        hitl_store,
        decisions,
        audit,
        policies or ReviewPolicyRegistry(),
        authorizer,
        notifiers=notifiers(audit) if notifiers else (),
        id_factory=sequential_ids("22222222-2222-4222-8222"),
    )
    return Harness(service, hitl_store, audit_store, audit, decision_store, decisions, authorizer)


async def open_maker_checker(
    harness: Harness,
    *,
    maker_principal_id: str = MAKER_ID,
    maker: Actor = MAKER,
    on_behalf_of_principal_id: str | None = None,
    action_kind: str = "model_swap",
    now: datetime = T0,
) -> ReviewItem:
    return await harness.service.open_item(
        kind="maker_checker",
        customer_id=CUSTOMER,
        domain_id=DOMAIN,
        subject_ref=TARGET,
        now=now,
        correlation_id="corr-open-1",
        action_kind=action_kind,
        intent_id=INTENT_ID,
        confirmation_hash=CONFIRMATION,
        maker_principal_id=maker_principal_id,
        maker_on_behalf_of_principal_id=on_behalf_of_principal_id,
        maker=maker,
        opened_by=maker,
        scope_hash=SCOPE_HASH,
        channel="rest",
    )


async def open_insight(
    harness: Harness, kind: ReviewKind = "relationship", *, now: datetime = T0
) -> ReviewItem:
    return await harness.service.open_item(
        kind=kind,
        customer_id=CUSTOMER,
        domain_id=DOMAIN,
        subject_ref=EDGE,
        now=now,
        correlation_id="corr-open-2",
    )
