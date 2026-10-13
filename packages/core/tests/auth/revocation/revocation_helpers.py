"""Shared fixtures for item 5 tests. Builds on item 2's helpers (fake clock, claims, policies)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from neurosphere_core.auth.revocation import (
    CachedRevocationChecker,
    InMemoryRevocationStore,
    RevocationAuditEvent,
    RevocationEntry,
    RevocationHookRegistry,
    RevocationService,
    ScopePermissionRevocationAuthorizer,
)
from neurosphere_core.auth.scope import InMemoryPolicyRepository, Role, ScopeDeriver
from neurosphere_core.scope import IdentityScope

from ..scope.scope_helpers import (
    CUSTOMER,
    FINANCE,
    OBJECT_ID,
    OPERATIONS,
    T0,
    FakeClock,
    make_claims,
    make_deriver,
    make_repo,
    principal_id_for,
    principal_policy,
    role,
)

__all__ = [
    "ADMIN_OID",
    "ANALYST_OID",
    "CUSTOMER",
    "FINANCE",
    "OBJECT_ID",
    "OTHER_OID",
    "T0",
    "UPN",
    "FakeClock",
    "FakePushRegistry",
    "RecordingAuditor",
    "admin_scope",
    "analyst_scope",
    "entry_for",
    "make_claims",
    "make_deriver",
    "policy_repo",
    "principal_id_for",
    "service_for",
]

ADMIN_OID = "11111111-2222-4333-8444-555555555555"
ANALYST_OID = "6c1d2e3f-4a5b-4c6d-8e7f-000000000001"
OTHER_OID = "6c1d2e3f-4a5b-4c6d-8e7f-000000000002"
#: Things that must never reach a log line: an object id and a UPN-shaped string.
UPN = "alice.example@contoso.example"


def policy_repo() -> InMemoryPolicyRepository:
    """Analyst (OBJECT_ID, ANALYST_OID, OTHER_OID) and time-bound Admin (ADMIN_OID) policies."""
    repo = make_repo(principal_policy(roles=(role(Role.ANALYST, FINANCE, OPERATIONS),)))
    for oid in (ANALYST_OID, OTHER_OID):
        repo.put_principal(
            principal_policy(object_id=oid, roles=(role(Role.ANALYST, FINANCE, OPERATIONS),))
        )
    repo.put_principal(
        principal_policy(object_id=ADMIN_OID, roles=(role(Role.ADMIN, FINANCE, expires_in=7200),))
    )
    return repo


async def _scope_for(object_id: str, clock: FakeClock) -> IdentityScope:
    return await make_deriver(policy_repo(), clock=clock).from_verified_claims(
        make_claims(object_id=object_id)
    )


async def admin_scope(clock: FakeClock) -> IdentityScope:
    return await _scope_for(ADMIN_OID, clock)


async def analyst_scope(clock: FakeClock) -> IdentityScope:
    return await _scope_for(ANALYST_OID, clock)


def entry_for(principal_id: str, revoked_at: datetime, *, reason: str = "test") -> RevocationEntry:
    return RevocationEntry(
        principal_id=principal_id,
        revoked_at=revoked_at,
        reason=reason,
        revoked_by=principal_id_for(ADMIN_OID),
    )


class RecordingAuditor:
    def __init__(self) -> None:
        self.events: list[RevocationAuditEvent] = []
        self.fail_on: set[str] = set()

    async def record(self, event: RevocationAuditEvent) -> None:
        if event.phase in self.fail_on:
            raise RuntimeError("audit store unavailable")
        self.events.append(event)

    @property
    def phases(self) -> list[str]:
        return [e.phase for e in self.events]


class FakePushRegistry:
    """Fake PRP-18 registry. Optional failure carries sensitive text to prove it is not logged."""

    def __init__(
        self, sessions: int = 1, *, error: BaseException | None = None, on_close: Any = None
    ) -> None:
        self.sessions = sessions
        self.error = error
        self.on_close = on_close
        self.closed_for: list[str] = []

    async def close_for_principal(self, principal_id: str) -> int:
        self.closed_for.append(principal_id)
        if self.on_close is not None:
            await self.on_close(principal_id)
        if self.error is not None:
            raise self.error
        return self.sessions


def service_for(
    store: InMemoryRevocationStore,
    clock: FakeClock,
    *,
    hooks: RevocationHookRegistry | None = None,
    auditor: RecordingAuditor | None = None,
    checker: CachedRevocationChecker | None = None,
    deriver: ScopeDeriver | None = None,
    ttl_seconds: float = 60,
) -> tuple[RevocationService, RevocationHookRegistry, RecordingAuditor]:
    hooks = hooks or RevocationHookRegistry()
    if checker is not None:
        hooks.register_cache_invalidator("revocation-checker", checker.invalidate_principal)
    if deriver is not None:
        hooks.register_cache_invalidator("scope-deriver", deriver.invalidate_principal)
    auditor = auditor or RecordingAuditor()
    service = RevocationService(
        store=store,
        authorizer=ScopePermissionRevocationAuthorizer(clock=clock),
        auditor=auditor,
        hooks=hooks,
        ttl_seconds=ttl_seconds,
        clock=clock,
    )
    return service, hooks, auditor
