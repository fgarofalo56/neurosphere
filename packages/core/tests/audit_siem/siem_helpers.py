"""Small fixtures for the SIEM sink tests (a verified scope, drafts and a deterministic repo)."""

from __future__ import annotations

import hashlib
import itertools
from datetime import UTC, datetime, timedelta

from neurosphere_contracts.scope.v1.identity_scope import IdentityScope as ContractScope
from neurosphere_core.audit import (
    AuditContext,
    AuditDraft,
    AuditRepository,
    InMemoryAuditStore,
    build_before,
    build_denied,
    make_subject,
)
from neurosphere_core.audit.siem import SiemExporter
from neurosphere_core.scope import IdentityScope

CHAIN = "contoso.domain-retail"
TARGET = "commercial:contoso:foundry:model_deployment:eastus2/chat-prod"
SCOPE_HASH = "sha256:" + hashlib.sha256(b"scope").hexdigest()


def make_scope() -> IdentityScope:
    contract = ContractScope.model_validate(
        {
            "schema_version": "1.0.0",
            "cloud": "commercial",
            "customer_id": "contoso",
            "principal": {
                "principal_id": "commercial:contoso:entra:person:psn_0123456789abcdef",
                "principal_pseudonym": "p-7f3a9c21",
                "principal_kind": "user",
            },
            "roles": [],
            "allowed_domains": ["commercial:contoso:catalog:domain:retail"],
            "allowed_resources": [],
            "policy_version": "v1",
            "derived_at": "2026-10-10T00:00:00Z",
            "scope_hash": SCOPE_HASH,
        }
    )
    return IdentityScope._from_verified_contract(contract)  # pyright: ignore[reportPrivateUsage]


def drafts(count: int) -> list[AuditDraft]:
    ctx = AuditContext.from_scope(
        make_scope(), correlation_id="corr-7c41e2", operation="action.execute", channel="rest"
    )
    out: list[AuditDraft] = []
    for i in range(count):
        if i % 2:
            out.append(build_denied(ctx, code="forbidden", reason="domain_out_of_scope"))
        else:
            out.append(
                build_before(
                    ctx, make_subject(TARGET, "model_deployment", target_version=f"etag-{i}")
                )
            )
    return out


class _StepClock:
    def __init__(self) -> None:
        self._now = datetime(2026, 10, 10, 17, 0, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        self._now += timedelta(milliseconds=1)
        return self._now


def make_repo(store: InMemoryAuditStore, exporter: SiemExporter) -> AuditRepository:
    counter = itertools.count(1)
    return AuditRepository(
        store,
        clock=_StepClock(),
        id_factory=lambda: f"00000000-0000-4000-8000-{next(counter):012d}",
        exporter=exporter,
    )
