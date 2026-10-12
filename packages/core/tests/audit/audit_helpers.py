"""Shared fixtures for audit tests: a verified scope, contexts, subjects, clock and ids."""

from __future__ import annotations

import hashlib
import itertools
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from neurosphere_contracts.audit.v1.audit_record import Subject
from neurosphere_contracts.scope.v1.identity_scope import IdentityScope as ContractScope
from neurosphere_core.audit import (
    AuditContext,
    AuditDraft,
    AuditRepository,
    InMemoryAuditStore,
    build_after,
    build_allowed,
    build_before,
    build_denied,
    make_subject,
)
from neurosphere_core.scope import IdentityScope

CHAIN = "contoso.domain-retail"
TARGET = "commercial:contoso:foundry:model_deployment:eastus2/chat-prod"
SCOPE_HASH = "sha256:" + hashlib.sha256(b"scope").hexdigest()


def make_scope(pseudonym: str = "p-7f3a9c21", kind: str = "user") -> IdentityScope:
    contract = ContractScope.model_validate(
        {
            "schema_version": "1.0.0",
            "cloud": "commercial",
            "customer_id": "contoso",
            "principal": {
                "principal_id": "commercial:contoso:entra:person:psn_0123456789abcdef",
                "principal_pseudonym": pseudonym,
                "principal_kind": kind,
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


def make_ctx(operation: str = "action.execute", **kwargs: object) -> AuditContext:
    return AuditContext.from_scope(
        make_scope(),
        correlation_id="corr-7c41e2",
        operation=operation,
        channel="rest",
        **kwargs,  # pyright: ignore[reportArgumentType]
    )


def subject(version: str = "etag-1", state: dict[str, object] | None = None) -> Subject:
    return make_subject(TARGET, "model_deployment", target_version=version, state=state or {"v": 1})


def mixed_drafts(count: int) -> list[AuditDraft]:
    """A realistic mix of allow, deny, before and after drafts."""
    ctx = make_ctx()
    makers: list[Callable[[int], AuditDraft]] = [
        lambda i: build_before(ctx, subject(f"etag-{i}")),
        lambda i: build_after(ctx, subject(f"etag-{i}"), result="succeeded", verified=True),
        lambda i: build_denied(ctx, code="forbidden", reason="domain_out_of_scope"),
        lambda i: build_allowed(ctx, subject(f"etag-{i}")),
    ]
    return [makers[i % len(makers)](i) for i in range(count)]


class StepClock:
    """Deterministic clock: each call advances one millisecond."""

    def __init__(self, start: datetime | None = None) -> None:
        self._now = start or datetime(2026, 10, 10, 17, 0, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        self._now += timedelta(milliseconds=1)
        return self._now


def sequential_ids() -> Callable[[], str]:
    counter = itertools.count(1)
    return lambda: f"00000000-0000-4000-8000-{next(counter):012d}"


def make_repo(store: InMemoryAuditStore | None = None, **kwargs: object) -> AuditRepository:
    return AuditRepository(
        store or InMemoryAuditStore(),
        clock=StepClock(),
        id_factory=sequential_ids(),
        **kwargs,  # pyright: ignore[reportArgumentType]
    )
