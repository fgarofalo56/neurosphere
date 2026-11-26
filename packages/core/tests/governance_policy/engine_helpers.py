"""In-memory policy engine harness for the item-3 tests (synthetic data only, no I/O).

One :class:`Engine` wires the in-memory stores, a real :class:`AuditRepository`, a real
:class:`HitlService`, the in-memory catalog seeded through ``rules_helpers`` and the real rule
evaluators, so the evaluation run, exception flow, lifecycle and projection are exercised end to
end on fakes.
"""

from __future__ import annotations

import copy
import hashlib
import itertools
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from neurosphere_contracts.actions.v1.actor import Actor
from neurosphere_contracts.audit.v1.audit_record import AuditRecord
from neurosphere_contracts.scope.v1.identity_scope import IdentityScope as ContractScope
from neurosphere_core.audit import AuditRepository, InMemoryAuditStore
from neurosphere_core.auth.scope.permissions import Permission, customer_control_domain_id
from neurosphere_core.catalog.repo import InMemoryCatalogRepository
from neurosphere_core.governance.policy import (
    BindingStore,
    EvaluationBudget,
    EvaluationRun,
    ExceptionDecidedEvent,
    ExceptionReconciler,
    ExceptionRequester,
    InMemoryBindingStore,
    InMemoryDocumentBackend,
    InMemoryEvaluationStatusStore,
    InMemoryExceptionStore,
    InMemoryPolicyDefinitionStore,
    InMemoryViolationStore,
    LifecycleAuditContext,
    LifecycleOutcome,
    PolicyEvaluator,
    PolicyLifecycle,
    StoredPolicy,
    ViolationEvent,
)
from neurosphere_core.governance.policy.rules import (
    DataSensitivityAccessEvaluator,
    RuleContext,
    RuleEvaluatorRegistry,
    RuleOutcome,
)
from neurosphere_core.hitl import (
    DecisionLog,
    HitlService,
    InMemoryDecisionStore,
    InMemoryHitlStore,
    ReviewPolicyRegistry,
)
from neurosphere_core.scope import IdentityScope

from .builders import draft
from .rules.rules_helpers import (
    NOW,
    access_engine,
    agent,
    agent_id,
    dom,
    grounding_source,
    reads,
    seed,
    source_id,
)

CUSTOMER = "acme"
CHAIN = "acme.governance-policy"
DOMAIN_A = dom("a")
DOMAIN_B = dom("b")
DOMAIN_HIDDEN = dom("hidden")
CONTROL = customer_control_domain_id("commercial", CUSTOMER)
READER = agent_id("reader")
CUSTOMERS_SOURCE = source_id("customers")
READ_EDGE = "commercial:acme:neurosphere:reads:r-reader-customers"
PII_PARAMS = {
    "sensitivity_categories": ["pii"],
    "access": "read",
    "allowed_when": "agent_version_approved",
}
INTENT = "00000001-0000-4000-8000-000000000001"


def principal_id(hex_char: str) -> str:
    return f"commercial:{CUSTOMER}:entra:person:p-{hex_char * 64}"


def pseudonym(hex_char: str) -> str:
    return f"p-{hex_char * 64}"


WORKER_ID = principal_id("a")
REQUESTER_ID = principal_id("b")
REVIEWER_ID = principal_id("c")
VIEWER_ID = principal_id("d")


def make_scope(
    hex_char: str, roles: Sequence[tuple[str, Sequence[str]]], allowed: Sequence[str]
) -> IdentityScope:
    payload: dict[str, Any] = {
        "schema_version": "1.0.0",
        "cloud": "commercial",
        "customer_id": CUSTOMER,
        "principal": {
            "principal_id": principal_id(hex_char),
            "principal_pseudonym": pseudonym(hex_char),
            "principal_kind": "user",
        },
        "roles": [{"role": role, "domain_ids": list(domains)} for role, domains in roles],
        "allowed_domains": list(allowed),
        "allowed_resources": [],
        "policy_version": "v1",
        "derived_at": "2026-01-01T00:00:00Z",
        "scope_hash": "sha256:" + hashlib.sha256(hex_char.encode()).hexdigest(),
    }
    return IdentityScope._from_verified_contract(ContractScope.model_validate(payload))


WORKER_SCOPE = make_scope(
    "a", [("domain_steward", [DOMAIN_A, DOMAIN_B, CONTROL])], [DOMAIN_A, DOMAIN_B, CONTROL]
)
REQUESTER_SCOPE = make_scope("b", [("analyst", [DOMAIN_A])], [DOMAIN_A])
VIEWER_SCOPE = make_scope("d", [("viewer", [DOMAIN_A])], [DOMAIN_A])


def actor(hex_char: str) -> Actor:
    return Actor.model_validate(
        {
            "principal_pseudonym": pseudonym(hex_char),
            "principal_kind": "user",
            "on_behalf_of": None,
        }
    )


def rule(
    rule_id: str = "pii-read", kind: str = "data_sensitivity_access", params: Any = None
) -> dict[str, Any]:
    return {
        "rule_id": rule_id,
        "kind": kind,
        "severity": None,
        "applies_to": {"entity_types": [], "tags": [], "environments": [], "entity_ids": []},
        "params": copy.deepcopy(PII_PARAMS if params is None else params),
    }


def policy_draft(
    policy_id: str = "pii-guard",
    *,
    domain: str = DOMAIN_A,
    mode: str = "audit",
    rules: Sequence[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    body = draft(policy_id, domain=domain)
    body["rules"] = [copy.deepcopy(r) for r in (rules or [rule()])]
    body["mode"] = mode
    body["display_name"] = "No unapproved agent reads PII"
    return body


class Clock:
    """A settable wall clock."""

    def __init__(self, now: datetime = NOW) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **delta: float) -> datetime:
        self.now = self.now + timedelta(**delta)
        return self.now


class AuditClock:
    """Strictly increasing timestamps for the audit chain."""

    def __init__(self, start: datetime = NOW) -> None:
        self._now = start

    def __call__(self) -> datetime:
        self._now += timedelta(milliseconds=1)
        return self._now


def uuid_ids(prefix: str) -> Any:
    counter = itertools.count(1)
    return lambda: f"{prefix}-{next(counter):012d}"


@dataclass
class FakeAuthorizer:
    """HITL reviewer authorizer: grants by real principal id, in domain A only."""

    grants: dict[str, set[Permission]] = field(default_factory=dict)

    async def can_review(
        self, principal_id: str, customer_id: str, domain_id: str, permission: Permission
    ) -> bool:
        return domain_id == DOMAIN_A and permission in self.grants.get(principal_id, set())


class Sink:
    """``ViolationEventSink`` that records every event."""

    def __init__(self) -> None:
        self.opened_events: list[ViolationEvent] = []
        self.resolved_events: list[ViolationEvent] = []
        self.decided_events: list[ExceptionDecidedEvent] = []

    async def opened(self, event: ViolationEvent) -> None:
        self.opened_events.append(event)

    async def resolved(self, event: ViolationEvent) -> None:
        self.resolved_events.append(event)

    async def exception_decided(self, event: ExceptionDecidedEvent) -> None:
        self.decided_events.append(event)


class CannedEvaluator:
    """A rule evaluator with a settable outcome (for resolve and truncation cases)."""

    def __init__(self, kind: str, outcome: RuleOutcome | None = None) -> None:
        self._kind = kind
        self.outcome = outcome or RuleOutcome(kind=kind)
        self.calls: list[RuleContext] = []

    @property
    def kind(self) -> str:
        return self._kind

    async def evaluate(self, ctx: RuleContext, policy: Any, rule: Any) -> RuleOutcome:
        self.calls.append(ctx)
        return self.outcome


@dataclass
class Engine:
    catalog: InMemoryCatalogRepository
    definitions: InMemoryDocumentBackend
    policies: InMemoryPolicyDefinitionStore
    statuses: InMemoryEvaluationStatusStore
    violations: InMemoryViolationStore
    exceptions: InMemoryExceptionStore
    bindings: BindingStore
    audit: AuditRepository
    registry: RuleEvaluatorRegistry
    lifecycle: PolicyLifecycle
    hitl: HitlService
    authorizer: FakeAuthorizer
    sink: Sink
    clock: Clock
    reconciler: ExceptionReconciler
    requester: ExceptionRequester
    evaluator: PolicyEvaluator

    async def records(self, chain: str = CHAIN) -> list[AuditRecord]:
        return await self.audit.read_range(chain, start=0, limit=500)

    async def operations(self, chain: str = CHAIN) -> list[str]:
        return [r.operation for r in await self.records(chain)]

    async def create(self, body: dict[str, Any]) -> StoredPolicy:
        return await self.policies.create_draft(body)

    async def publish(
        self, body: dict[str, Any], *, scope: IdentityScope = WORKER_SCOPE
    ) -> LifecycleOutcome:
        created = await self.create(body)
        return await self.lifecycle.publish(
            created.policy.policy_id.root,
            created.policy.policy_version,
            expected_etag=created.etag,
            audit_ctx=LifecycleAuditContext(
                scope=scope, correlation_id="corr-publish", intent_id=INTENT
            ),
        )

    async def tick(
        self,
        *,
        scope: IdentityScope = WORKER_SCOPE,
        budget: EvaluationBudget | None = None,
        advance_minutes: float = 5,
    ) -> EvaluationRun:
        self.clock.advance(minutes=advance_minutes)
        return await self.evaluator.run(
            CUSTOMER,
            scope=scope,
            trigger="interval",
            budget=budget or EvaluationBudget(max_subjects_per_rule=1000, seconds_per_rule=60),
        )


async def pii_world() -> InMemoryCatalogRepository:
    """Agent ``reader`` (no approved version) has a ``reads`` edge to a PII grounding source."""
    repo = InMemoryCatalogRepository()
    await seed(
        repo,
        agent("reader"),
        grounding_source("customers", sensitivity_categories=["pii"]),
        reads("r-reader-customers", READER, CUSTOMERS_SOURCE),
    )
    return repo


async def build_engine(
    *,
    catalog: InMemoryCatalogRepository | None = None,
    real_pii_evaluator: bool = True,
    max_days: int = 90,
) -> Engine:
    repo = catalog or await pii_world()
    definitions = InMemoryDocumentBackend()
    policies = InMemoryPolicyDefinitionStore(definitions)
    statuses = InMemoryEvaluationStatusStore(definitions)
    violations = InMemoryViolationStore()
    exceptions = InMemoryExceptionStore()
    bindings = InMemoryBindingStore(cloud="commercial")
    audit = AuditRepository(InMemoryAuditStore(), clock=AuditClock())
    registry = RuleEvaluatorRegistry()
    if real_pii_evaluator:
        registry.register(DataSensitivityAccessEvaluator(repo, access_engine(repo)))
    clock = Clock()
    lifecycle = PolicyLifecycle(policies, bindings, audit, registry, repo, clock=clock)
    authorizer = FakeAuthorizer(
        grants={
            REVIEWER_ID: {Permission.CATALOG_CURATE},
            REQUESTER_ID: {Permission.CATALOG_CURATE},
        }
    )
    hitl = HitlService(
        InMemoryHitlStore(),
        DecisionLog(audit, InMemoryDecisionStore()),
        audit,
        ReviewPolicyRegistry(),
        authorizer,
        id_factory=uuid_ids("22222222-2222-4222-8222"),
    )
    sink = Sink()
    reconciler = ExceptionReconciler(exceptions, violations, hitl, audit, events=sink)
    requester = ExceptionRequester(
        violations, exceptions, hitl, audit, max_days=max_days, clock=clock
    )
    evaluator = PolicyEvaluator(
        policies,
        violations,
        statuses,
        registry,
        audit,
        events=sink,
        exceptions=reconciler,
        lifecycle=lifecycle,
        clock=clock,
        id_factory=uuid_ids("33333333-3333-4333-8333"),
    )
    return Engine(
        catalog=repo,
        definitions=definitions,
        policies=policies,
        statuses=statuses,
        violations=violations,
        exceptions=exceptions,
        bindings=bindings,
        audit=audit,
        registry=registry,
        lifecycle=lifecycle,
        hitl=hitl,
        authorizer=authorizer,
        sink=sink,
        clock=clock,
        reconciler=reconciler,
        requester=requester,
        evaluator=evaluator,
    )
