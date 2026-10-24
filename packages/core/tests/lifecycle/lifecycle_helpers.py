"""Builders for the lifecycle tests (synthetic data only)."""

from __future__ import annotations

import hashlib
import itertools
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from neurosphere_contracts.scope.v1.identity_scope import IdentityScope as ContractScope
from neurosphere_core.audit import (
    AuditContext,
    AuditRepository,
    InMemoryAuditStore,
)
from neurosphere_core.lifecycle import (
    LifecycleEngine,
    PolicyState,
    TargetRecord,
    TargetRegistry,
    load_policy,
)
from neurosphere_core.lifecycle.memory import (
    InMemoryHoldRegistry,
    InMemoryMappingStore,
    InMemoryRequestQueue,
    InMemoryTarget,
)
from neurosphere_core.scope import IdentityScope

CHAIN = "lifecycle.contoso"
NOW = datetime(2026, 10, 23, 12, 0, 0, tzinfo=UTC)
DOMAIN = "commercial:contoso:catalog:domain:retail"
OTHER_DOMAIN = "commercial:contoso:catalog:domain:finance"
POLICY_RAW = {
    "policy_version": "records-2026-1",
    "retain_prompt_response_bodies": False,
    "rules": [
        {"data_class": "telemetry", "min_retention_days": 30, "max_retention_days": 365},
        {"data_class": "conversation_default", "min_retention_days": 0, "max_retention_days": 90},
    ],
}


def policy() -> PolicyState:
    return load_policy(POLICY_RAW)


def make_scope(
    pseudonym: str = "p-7f3a9c21", customer: str = "contoso", domains: tuple[str, ...] = (DOMAIN,)
) -> IdentityScope:
    contract = ContractScope.model_validate(
        {
            "schema_version": "1.0.0",
            "cloud": "commercial",
            "customer_id": customer,
            "principal": {
                "principal_id": "commercial:contoso:entra:person:psn_0123456789abcdef",
                "principal_pseudonym": pseudonym,
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


def make_ctx(scope: IdentityScope | None = None) -> AuditContext:
    return AuditContext.from_scope(
        scope or make_scope(),
        correlation_id="corr-23a1",
        operation="lifecycle.run",
        channel="worker",
    )


def record(
    record_id: str,
    *,
    age_days: int = 0,
    data_class: str = "telemetry",
    subject_id: str | None = None,
    doc_type: str | None = None,
    customer_id: str | None = "contoso",
    domain_id: str | None = DOMAIN,
) -> TargetRecord:
    return TargetRecord(
        record_id=record_id,
        data_class=data_class,
        created_at=NOW - timedelta(days=age_days),
        subject_id=subject_id,
        doc_type=doc_type,
        customer_id=customer_id,
        domain_id=domain_id,
    )


@dataclass
class Rig:
    engine: LifecycleEngine
    audit: AuditRepository
    target: InMemoryTarget
    holds: InMemoryHoldRegistry
    queue: InMemoryRequestQueue
    mappings: InMemoryMappingStore
    registry: TargetRegistry

    async def audit_records(self) -> list[tuple[str, str | None, str | None]]:
        """(kind, denial reason, outcome detail) for every record in the chain."""
        out: list[tuple[str, str | None, str | None]] = []
        for rec in await self.audit.read_range(CHAIN, limit=500):
            reason = rec.denial.reason if rec.denial else None
            detail = rec.outcome.detail if rec.outcome else None
            out.append((rec.kind, reason, detail))
        return out


def make_rig(
    *, state: PolicyState | None = None, ignore_deletes: bool = False, container: str = "records"
) -> Rig:
    counter = itertools.count(1)
    audit = AuditRepository(
        InMemoryAuditStore(),
        clock=lambda: NOW,
        id_factory=lambda: f"00000000-0000-4000-8000-{next(counter):012d}",
    )
    target = InMemoryTarget("catalog", container, ignore_deletes=ignore_deletes)
    registry = TargetRegistry()
    registry.register(target)
    holds = InMemoryHoldRegistry()
    queue = InMemoryRequestQueue()
    mappings = InMemoryMappingStore({"subj-1"})
    engine = LifecycleEngine(
        policy=policy() if state is None else state,
        targets=registry,
        holds=holds,
        queue=queue,
        audit=audit,
        audit_chain_id=CHAIN,
        cloud="commercial",
        customer_id="contoso",
        mappings=mappings,
        clock=lambda: NOW,
    )
    return Rig(engine, audit, target, holds, queue, mappings, registry)
