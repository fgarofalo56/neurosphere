"""In-memory harness for the ``policy_eval`` role tests (synthetic data only, no I/O).

Minimal copies of the core governance test fixtures (``packages/core/tests/governance_policy``):
the contract's valid examples, one agent with a ``reads`` edge to a PII grounding source, and a
worker scope. The role is wired through :func:`assemble_policy_eval`, the same function the
Cosmos builder calls, over the in-memory stores.
"""

from __future__ import annotations

import copy
import hashlib
import itertools
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from neurosphere_contracts.catalog.v1.agent import Agent
from neurosphere_contracts.catalog.v1.grounding_source import GroundingSource
from neurosphere_contracts.catalog.v1.reads import ReadsRelation
from neurosphere_contracts.scope.v1.identity_scope import IdentityScope as ContractScope
from neurosphere_core.aggregates.models import AggregateWindow
from neurosphere_core.aggregates.subject import SubjectKind, SubjectLookup
from neurosphere_core.audit import AuditRepository, InMemoryAuditStore
from neurosphere_core.auth.scope.permissions import Permission, customer_control_domain_id
from neurosphere_core.catalog.repo import InMemoryCatalogRepository
from neurosphere_core.governance.policy import (
    InMemoryBindingStore,
    InMemoryDocumentBackend,
    InMemoryEvaluationStatusStore,
    InMemoryExceptionStore,
    InMemoryPolicyDefinitionStore,
    InMemoryViolationStore,
    LifecycleAuditContext,
    LifecycleOutcome,
    NoopViolationEventSink,
)
from neurosphere_core.hitl import (
    DecisionLog,
    HitlService,
    InMemoryDecisionStore,
    InMemoryHitlStore,
    ReviewPolicyRegistry,
)
from neurosphere_core.scope import IdentityScope
from neurosphere_workers.policy_eval.assembly import (
    PolicyEvalParts,
    PolicyEvalStores,
    assemble_policy_eval,
)
from neurosphere_workers.policy_eval.settings import PolicyEvalSettings

CUSTOMER = "acme"
NOW = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)
_SCHEMAS = Path(__file__).resolve().parents[4] / "packages" / "contracts" / "schemas"
_CATALOG = _SCHEMAS / "catalog" / "v1" / "examples" / "valid"
_POLICY = _SCHEMAS / "policy" / "v1" / "examples" / "valid"
INTENT = "00000001-0000-4000-8000-000000000001"


def dom(name: str) -> str:
    return f"commercial:{CUSTOMER}:neurosphere:domain:{name}"


DOMAIN_A = dom("a")
DOMAIN_B = dom("b")
CONTROL = customer_control_domain_id("commercial", CUSTOMER)
READER = f"commercial:{CUSTOMER}:foundry:agent:reader"
SOURCE = f"commercial:{CUSTOMER}:foundry:grounding_source:customers"
READ_EDGE = f"commercial:{CUSTOMER}:neurosphere:reads:r-reader-customers"
AUTHOR = f"commercial:{CUSTOMER}:entra:person:p-" + "1" * 64


def _example(folder: Path, name: str) -> dict[str, Any]:
    return json.loads((folder / name).read_text(encoding="utf-8"))


def make_scope(
    hex_char: str, allowed: Sequence[str], role: str = "domain_steward"
) -> IdentityScope:
    payload: dict[str, Any] = {
        "schema_version": "1.0.0",
        "cloud": "commercial",
        "customer_id": CUSTOMER,
        "principal": {
            "principal_id": f"commercial:{CUSTOMER}:entra:person:p-{hex_char * 64}",
            "principal_pseudonym": f"p-{hex_char * 64}",
            "principal_kind": "user",
        },
        "roles": [{"role": role, "domain_ids": list(allowed)}],
        "allowed_domains": list(allowed),
        "allowed_resources": [],
        "policy_version": "v1",
        "derived_at": "2026-01-01T00:00:00Z",
        "scope_hash": "sha256:" + hashlib.sha256(hex_char.encode()).hexdigest(),
    }
    return IdentityScope._from_verified_contract(ContractScope.model_validate(payload))


WORKER_SCOPE = make_scope("a", [DOMAIN_A, DOMAIN_B, CONTROL])


# --------------------------------------------------------------------------- catalog


def _entity(example: str, entity_id: str, domain: str) -> dict[str, Any]:
    raw = _example(_CATALOG, example)
    raw.update(id=entity_id, customer_id=CUSTOMER, domain_id=domain, version=1, etag="caller-etag")
    return raw


def reader_agent() -> Agent:
    raw = _entity("agent.minimal-and-typical.json", READER, DOMAIN_A)
    raw.update(current_version_id=None, external_agent_id=None, display_name="Agent reader")
    return Agent.model_validate(raw)


def pii_source() -> GroundingSource:
    raw = _entity("grounding_source.sensitivity-residency.json", SOURCE, DOMAIN_A)
    raw.update(
        display_name="Source customers",
        tags=[],
        environment="unknown",
        sensitivity_categories=["pii"],
    )
    return GroundingSource.model_validate(raw)


def reads_edge() -> ReadsRelation:
    raw = _example(_CATALOG, "reads.asserted.json")
    raw.update(
        id=READ_EDGE,
        source_id=READER,
        target_id=SOURCE,
        customer_id=CUSTOMER,
        domain_id=DOMAIN_A,
        version=1,
        etag="caller-etag",
    )
    return ReadsRelation.model_validate(raw)


async def pii_world() -> InMemoryCatalogRepository:
    """Agent ``reader`` (no approved version) has a ``reads`` edge to a PII grounding source."""
    repo = InMemoryCatalogRepository()
    await repo.create_entity(WORKER_SCOPE, reader_agent())
    await repo.create_entity(WORKER_SCOPE, pii_source())
    await repo.put_edge(WORKER_SCOPE, reads_edge(), None)
    return repo


# --------------------------------------------------------------------------- policies


def pii_policy(policy_id: str = "pii-guard", *, domain: str = DOMAIN_A) -> dict[str, Any]:
    """The PII policy (no agent without approval may read PII): one access rule."""
    body = copy.deepcopy(_example(_POLICY, "policy-definition.all-kinds.json"))
    body.update(
        {
            "policy_id": policy_id,
            "policy_version": 1,
            "previous_version": None,
            "domain_id": domain,
            "status": "draft",
            "created_by": AUTHOR,
            "published_at": None,
            "published_intent_id": None,
            "published_audit_id": None,
            "mode": "audit",
            "display_name": "No unapproved agent reads PII",
        }
    )
    body.pop("content_sha256", None)
    body["rules"] = [
        {
            "rule_id": "pii-read",
            "kind": "data_sensitivity_access",
            "severity": None,
            "applies_to": {"entity_types": [], "tags": [], "environments": [], "entity_ids": []},
            "params": {
                "sensitivity_categories": ["pii"],
                "access": "read",
                "allowed_when": "agent_version_approved",
            },
        }
    ]
    return body


# --------------------------------------------------------------------------- fakes


class Clock:
    """A settable wall clock."""

    def __init__(self, now: datetime = NOW) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **delta: float) -> None:
        self.now = self.now + timedelta(**delta)


class Monotonic:
    """A settable monotonic clock (seconds)."""

    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


class AuditClock:
    """Strictly increasing timestamps for the audit chain."""

    def __init__(self, start: datetime = NOW) -> None:
        self._now = start

    def __call__(self) -> datetime:
        self._now += timedelta(milliseconds=1)
        return self._now


class NoSubjects:
    """``SubjectMetricsReader`` with no points (the PII rule reads only the catalog)."""

    async def latest_subject_points(
        self,
        customer_id: str,
        domain_id: str,
        kind: SubjectKind,
        keys: Sequence[str],
        window: AggregateWindow,
    ) -> SubjectLookup:
        return SubjectLookup(points={})

    async def newest_subject_points(
        self, customer_id: str, domain_id: str, window: AggregateWindow, limit: int
    ) -> SubjectLookup:
        return SubjectLookup(points={})


class StaticScopes:
    """The worker's derived scope; ``error`` simulates a failed derivation."""

    def __init__(self, scope: IdentityScope = WORKER_SCOPE) -> None:
        self.scope = scope
        self.error: Exception | None = None

    async def get(self) -> IdentityScope:
        if self.error is not None:
            raise self.error
        return self.scope


class NeverReviewer:
    async def can_review(
        self, principal_id: str, customer_id: str, domain_id: str, permission: Permission
    ) -> bool:
        return False


def _ids(prefix: str) -> Any:
    counter = itertools.count(1)
    return lambda: f"{prefix}-{next(counter):012d}"


@dataclass
class Harness:
    parts: PolicyEvalParts
    catalog: InMemoryCatalogRepository
    definitions: InMemoryDocumentBackend
    violations: InMemoryViolationStore
    audit: AuditRepository
    scopes: StaticScopes
    clock: Clock
    monotonic: Monotonic

    async def publish(self, body: dict[str, Any]) -> LifecycleOutcome:
        created = await self.parts.policies.create_draft(body)
        return await self.parts.lifecycle.publish(
            created.policy.policy_id.root,
            created.policy.policy_version,
            expected_etag=created.etag,
            audit_ctx=LifecycleAuditContext(
                scope=WORKER_SCOPE, correlation_id="corr-publish", intent_id=INTENT
            ),
        )

    async def operations(self) -> list[str]:
        records = await self.audit.read_range("acme.governance-policy", start=0, limit=500)
        return [r.operation for r in records]


async def build_harness(*, interval_seconds: float = 300.0) -> Harness:
    catalog = await pii_world()
    definitions = InMemoryDocumentBackend()
    violations = InMemoryViolationStore()
    audit = AuditRepository(InMemoryAuditStore(), clock=AuditClock())
    hitl = HitlService(
        InMemoryHitlStore(),
        DecisionLog(audit, InMemoryDecisionStore()),
        audit,
        ReviewPolicyRegistry(),
        NeverReviewer(),
        id_factory=_ids("22222222-2222-4222-8222"),
    )
    stores = PolicyEvalStores(
        policies=InMemoryPolicyDefinitionStore(definitions),
        statuses=InMemoryEvaluationStatusStore(definitions),
        violations=violations,
        exceptions=InMemoryExceptionStore(),
        bindings=InMemoryBindingStore(cloud="commercial"),
    )
    scopes = StaticScopes()
    clock = Clock()
    monotonic = Monotonic()
    parts = assemble_policy_eval(
        customer_id=CUSTOMER,
        cloud="commercial",
        settings=PolicyEvalSettings.model_validate({"interval_seconds": interval_seconds}),
        stores=stores,
        audit=audit,
        hitl=hitl,
        catalog=catalog,
        metrics=NoSubjects(),
        scope_provider=scopes,
        cosmos_client=None,
        events=NoopViolationEventSink(),
        finding_reader=None,
        clock=clock,
        monotonic=monotonic,
    )
    return Harness(
        parts=parts,
        catalog=catalog,
        definitions=definitions,
        violations=violations,
        audit=audit,
        scopes=scopes,
        clock=clock,
        monotonic=monotonic,
    )
