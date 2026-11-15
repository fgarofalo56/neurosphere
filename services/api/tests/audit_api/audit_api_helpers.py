"""A real authz harness plus seeded audit chains for the PRP-40 route tests (no emulator)."""

from __future__ import annotations

import hashlib
import itertools
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from authz.authz_helpers import (  # pyright: ignore[reportMissingImports]
    FINANCE,
    HR,
    OPERATIONS,
    Harness,
    RecordingDenials,
    harness,
    policy,
    role,
)
from neurosphere_api.audit.search_store import RepositoryAuditSearchStore
from neurosphere_core.audit import (
    AuditContext,
    AuditDraft,
    AuditRepository,
    InMemoryAuditStore,
    build_after,
    build_before,
    build_denied,
    make_subject,
)
from neurosphere_core.audit.chains import domain_audit_chain_id
from neurosphere_core.auth.scope import Role, customer_control_domain_id

CUSTOMER = "contoso"
CONTROL = customer_control_domain_id("commercial", CUSTOMER)
DENIALS_CHAIN = f"{CUSTOMER}.authz-denials"
#: Object ids (dev issuer ``oid``) of the test principals.
AUDITOR_FO = "b16c7d8e-9fa0-4b12-83d4-e5f6a7b8c9bb"  # auditor of FINANCE + OPERATIONS
AUDITOR_ALL = "c27d8e9f-a0b1-4c23-94e5-f6a7b8c9d0cc"  # auditor incl. the control domain
STEWARD = "a05b6c7d-8e9f-4a01-b2c3-d4e5f6a7b8aa"  # steward of FINANCE (no audit.*)

BASE = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
SINCE = "2026-11-01T00:00:00Z"
UNTIL = "2026-11-02T00:00:00Z"
SCOPE_HASH = "sha256:" + hashlib.sha256(b"seed").hexdigest()
MEMBERS = (FINANCE, OPERATIONS, HR, CONTROL)


def chain_of(domain_id: str) -> str:
    return domain_audit_chain_id(CUSTOMER, domain_id)


class StepClock:
    """Each append is one minute after the previous one, starting at ``BASE``."""

    def __init__(self) -> None:
        self._now = BASE

    def __call__(self) -> datetime:
        self._now += timedelta(minutes=1)
        return self._now


def ctx(
    operation: str = "action.execute", pseudonym: str = "p-0a1b2c3d", correlation: str = "corr-1"
) -> AuditContext:
    return AuditContext.model_validate(
        {
            "actor": {
                "principal_pseudonym": pseudonym,
                "principal_kind": "user",
                "on_behalf_of": None,
            },
            "scope_hash": SCOPE_HASH,
            "correlation_id": correlation,
            "operation": operation,
            "channel": "rest",
        }
    )


def subject(domain_id: str) -> Any:
    return make_subject(domain_id, "domain", state={"v": 1})


@dataclass
class World:
    h: Harness
    repository: AuditRepository
    store: InMemoryAuditStore
    denials: RecordingDenials

    def get(self, who: str, path: str, **params: Any) -> Any:
        return self.h.client.get(path, params=params, headers=self.h.auth(who))


def make_world(*, with_search_store: bool = True) -> World:
    denials = RecordingDenials()
    h = harness(
        policy(
            AUDITOR_FO,
            role(Role.SECURITY_AUDITOR, FINANCE, OPERATIONS),
            memberships=MEMBERS,
        ),
        policy(
            AUDITOR_ALL,
            role(Role.SECURITY_AUDITOR, FINANCE, OPERATIONS, HR, CONTROL),
            memberships=MEMBERS,
        ),
        policy(STEWARD, role(Role.DOMAIN_STEWARD, FINANCE), memberships=MEMBERS),
        routers={},
        denials=denials,
    )
    store = InMemoryAuditStore()
    counter = itertools.count(1)
    repository = AuditRepository(
        store,
        clock=StepClock(),
        id_factory=lambda: f"00000000-0000-4000-8000-{next(counter):012d}",
    )
    h.app.state.audit_repository = repository
    if with_search_store:
        h.app.state.audit_search_store = RepositoryAuditSearchStore(repository)
    return World(h=h, repository=repository, store=store, denials=denials)


async def seed(world: World) -> dict[str, list[str]]:
    """Interleaved records on FINANCE, OPERATIONS and HR chains plus two denials.

    Returns ``{chain: [audit_id, ...]}`` in append order.
    """
    plan: list[tuple[str, AuditDraft]] = []
    for i in range(4):
        plan.append(
            (chain_of(FINANCE), build_before(ctx(correlation=f"corr-f{i}"), subject(FINANCE)))
        )
        plan.append(
            (
                chain_of(OPERATIONS),
                build_after(
                    ctx("catalog.update", pseudonym="p-11112222"),
                    subject(OPERATIONS),
                    result="failed" if i % 2 else "succeeded",
                    verified=False,
                ),
            )
        )
        plan.append((chain_of(HR), build_before(ctx(), subject(HR))))
    plan.append(
        (DENIALS_CHAIN, build_denied(ctx(), code="forbidden", reason="target_out_of_scope"))
    )
    plan.append((DENIALS_CHAIN, build_denied(ctx(), code="forbidden", reason="permission_missing")))
    out: dict[str, list[str]] = {}
    for chain, draft in plan:
        record = await world.repository.append(chain, draft)
        out.setdefault(chain, []).append(record.audit_id.root)
    return out
