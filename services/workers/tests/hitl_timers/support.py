"""Test support for the HITL timer worker: a settable clock and a service over shared stores.

Stores are passed in explicitly so a test can discard a worker (and its service) and build a
new one over the SAME persisted state, which is what a process restart looks like.
"""

from __future__ import annotations

import hashlib
import itertools
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from neurosphere_contracts.actions.v1.actor import Actor
from neurosphere_contracts.audit.v1.audit_record import AuditRecord
from neurosphere_core.audit import AuditRepository, InMemoryAuditStore
from neurosphere_core.auth.scope.permissions import Permission
from neurosphere_core.hitl import (
    DecisionLog,
    EmailNotifierStub,
    HitlService,
    InMemoryDecisionStore,
    InMemoryHitlStore,
    ReviewItem,
    ReviewPolicy,
    ReviewPolicyRegistry,
    TeamsNotifierStub,
)
from neurosphere_core.hitl.policy import default_policies
from neurosphere_workers.hitl_timers import HitlTimerWorker

T0 = datetime(2026, 10, 20, 9, 0, 0, tzinfo=UTC)
CUSTOMER = "contoso"
DOMAIN = "commercial:contoso:catalog:domain:retail"
CHAIN = "contoso.retail"
EDGE = "commercial:contoso:catalog:edge:e-0001"
TARGET = "commercial:contoso:foundry:model_deployment:eastus2/chat-prod"
SCOPE_HASH = "sha256:" + hashlib.sha256(b"scope").hexdigest()
CONFIRMATION = "sha256:" + hashlib.sha256(b"intent-1").hexdigest()
MAKER_ID = "commercial:contoso:entra:person:psn_maker000000001"
CHECKER_ID = "commercial:contoso:entra:person:psn_checker00000002"
MAKER = Actor(principal_pseudonym="p-maker", principal_kind="user", on_behalf_of=None)
CHECKER = Actor(principal_pseudonym="p-checker", principal_kind="user", on_behalf_of=None)

#: Short, explicit timings so tests read as arithmetic.
POLICY = ReviewPolicy(
    approver_permission=Permission.CATALOG_CURATE,
    assignment_timeout=timedelta(hours=1),
    sla=timedelta(hours=4),
    escalation_step=timedelta(hours=2),
    max_escalations=2,
    expiry=timedelta(hours=24),
    policy_version="test-timers-1",
)


class FakeClock:
    def __init__(self, start: datetime = T0) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, delta: timedelta) -> None:
        self.now += delta


class StepClock:
    def __init__(self, start: datetime = T0) -> None:
        self._now = start

    def __call__(self) -> datetime:
        self._now += timedelta(milliseconds=1)
        return self._now


def ids(prefix: str) -> Callable[[], str]:
    counter = itertools.count(1)
    return lambda: f"{prefix}-{next(counter):012d}"


class AllowAll:
    async def can_review(
        self, principal_id: str, customer_id: str, domain_id: str, permission: Permission
    ) -> bool:
        return True


@dataclass
class Persisted:
    """Everything that survives a restart: the stores. Workers and services are rebuilt."""

    store: InMemoryHitlStore = field(default_factory=InMemoryHitlStore)
    audit_store: InMemoryAuditStore = field(default_factory=InMemoryAuditStore)
    decision_store: InMemoryDecisionStore = field(default_factory=InMemoryDecisionStore)
    generation: int = 0

    def service(self, policy: ReviewPolicy = POLICY) -> HitlService:
        """A fresh service (new process) over the persisted stores."""
        self.generation += 1
        audit = AuditRepository(
            self.audit_store,
            clock=StepClock(),
            id_factory=ids(f"00000000-0000-4000-8{self.generation:03d}"),
        )
        policies = {**default_policies(), "relationship": policy, "maker_checker": policy}
        return HitlService(
            self.store,
            DecisionLog(audit, self.decision_store),
            audit,
            ReviewPolicyRegistry(kind_defaults=policies),
            AllowAll(),
            notifiers=[EmailNotifierStub(audit), TeamsNotifierStub(audit)],
            id_factory=ids(f"22222222-2222-4222-8{self.generation:03d}"),
        )

    def worker(self, clock: FakeClock, policy: ReviewPolicy = POLICY) -> HitlTimerWorker:
        return HitlTimerWorker(self.service(policy), clock=clock)

    async def audit_records(self) -> list[AuditRecord]:
        audit = AuditRepository(self.audit_store)
        tail = await audit.tail(CHAIN)
        if tail is None:
            return []
        found: list[AuditRecord] = []
        start = 0
        while start <= tail.sequence:
            found.extend(await audit.read_range(CHAIN, start=start, limit=500))
            start += 500
        return found

    async def notifications(self, event: str) -> list[str]:
        """Operations of recorded notification sends for ``event`` (one per stub channel)."""
        return [
            r.operation
            for r in await self.audit_records()
            if r.operation.startswith("hitl.notify.")
            and r.outcome is not None
            and (r.outcome.detail or "").endswith(f".{event}=recorded")
        ]

    async def chain_ok(self) -> bool:
        return (await AuditRepository(self.audit_store).verify(CHAIN)).ok


async def open_relationship(service: HitlService, now: datetime = T0) -> ReviewItem:
    return await service.open_item(
        kind="relationship",
        customer_id=CUSTOMER,
        domain_id=DOMAIN,
        subject_ref=EDGE,
        now=now,
        correlation_id="corr-open-1",
    )


async def claim(service: HitlService, item: ReviewItem, now: datetime) -> ReviewItem:
    return await service.assign(
        item.item_id,
        None,
        CHECKER_ID,
        now,
        by=CHECKER,
        scope_hash=SCOPE_HASH,
        correlation_id="corr-claim-1",
    )
