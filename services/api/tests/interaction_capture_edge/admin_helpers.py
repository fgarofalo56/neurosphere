"""Harness for the PRP-103 item 5 capture admin route tests (synthetic data only).

Composes the REAL authz builder, a stub data builder (in-memory audit) and a stub capture
builder that leaves ``app.state`` exactly as ``runtime/builders/interactions.py`` does (or leaves
the attributes absent, as when that builder is not composed). Principals:

* ``CUSTOMER_ADMIN``: ``admin`` on FINANCE and the customer-control domain.
* ``FIN_ADMIN``: ``admin`` on FINANCE only; ``OPS_ADMIN``: ``admin`` on OPERATIONS only.
* ``ANALYST``: analyst in FINANCE (no ``config.manage``).

Object ids are built at runtime (no GUID-shaped literal in the source).
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Final

from authz.authz_helpers import (  # pyright: ignore[reportMissingImports]
    CUSTOMER,
    FINANCE,
    OPERATIONS,
    POLICY_VERSION,
    FakeClock,
    make_validator,
    role,
)
from fastapi.testclient import TestClient
from neurosphere_api.runtime import CompositionOverrides
from neurosphere_api.runtime.builders import AUDIT_REPOSITORY, BuildContext, BuilderSpec
from neurosphere_api.runtime.builders import authz as authz_builder
from neurosphere_core.audit import AuditRepository, InMemoryAuditStore
from neurosphere_core.auth.revocation import InMemoryRevocationStore
from neurosphere_core.auth.scope import (
    InMemoryPolicyRepository,
    PolicyHead,
    PrincipalPolicy,
    Role,
    customer_control_domain_id,
    principal_document_id,
)
from neurosphere_core.interactions import InMemoryCapturePolicyStore, parse_capture_policy
from runtime_api.runtime_helpers import (  # pyright: ignore[reportMissingImports]
    Composed,
    compose,
    composed_principal_id,
)

from .edge_helpers import policy_doc

BASE: Final = "/api/v1/admin/interactions"
POLICIES: Final = f"{BASE}/capture-policies"
STATUS: Final = f"{BASE}/capture-status"
CONTROL: Final = customer_control_domain_id("commercial", CUSTOMER)


def _oid(n: int) -> str:
    return str(uuid.UUID(int=(0xC4F7 << 64) | n, version=4))


CUSTOMER_ADMIN: Final = _oid(1)
FIN_ADMIN: Final = _oid(2)
OPS_ADMIN: Final = _oid(3)
ANALYST: Final = _oid(4)

_UNSET: Final = object()


def contoso_policy(policy_id: str, domain_id: str = FINANCE, **over: Any) -> dict[str, Any]:
    """A capture policy document of customer ``contoso`` in ``domain_id``."""
    doc = policy_doc(capture_policy_id=policy_id, customer_id=CUSTOMER, domain_id=domain_id, **over)
    return doc


def _principal(object_id: str, memberships: tuple[str, ...], who: Role) -> PrincipalPolicy:
    principal = str(composed_principal_id(object_id))
    return PrincipalPolicy(
        id=principal_document_id(principal),
        customer_id=CUSTOMER,
        principal_id=principal,
        domain_memberships=memberships,
        role_assignments=(role(who, *memberships),),
    )


def seeded_principals() -> InMemoryPolicyRepository:
    repo = InMemoryPolicyRepository()
    repo.put_head(PolicyHead(customer_id=CUSTOMER, policy_version=POLICY_VERSION))
    repo.put_principal(_principal(CUSTOMER_ADMIN, (FINANCE, CONTROL), Role.ADMIN))
    repo.put_principal(_principal(FIN_ADMIN, (FINANCE,), Role.ADMIN))
    repo.put_principal(_principal(OPS_ADMIN, (OPERATIONS,), Role.ADMIN))
    repo.put_principal(_principal(ANALYST, (FINANCE,), Role.ANALYST))
    return repo


@dataclass
class AdminWorld:
    composed: Composed
    policy_store: InMemoryCapturePolicyStore | None
    audit_store: InMemoryAuditStore

    @property
    def client(self) -> TestClient:
        return self.composed.client()

    def get(self, path: str, who: str, **params: Any) -> Any:
        return self.client.get(path, headers=self.composed.auth(who), params=params or None)


def build_world(
    *,
    policies: Iterable[dict[str, Any]] = (),
    configured: bool = True,
    off_reason: object = _UNSET,
    edge: object = None,
    stats: object = None,
) -> AdminWorld:
    """Compose the app. ``configured=False`` leaves the capture attributes absent."""
    clock = FakeClock()
    overrides = CompositionOverrides(
        authenticator=make_validator(clock),
        policy_repository=seeded_principals(),
        revocation_store=InMemoryRevocationStore(clock=clock),
        clock=clock,
    )
    audit_store = InMemoryAuditStore()
    audit = AuditRepository(audit_store)
    store: InMemoryCapturePolicyStore | None = None
    if configured:
        store = InMemoryCapturePolicyStore()
        for doc in policies:
            asyncio.run(store.create(parse_capture_policy(doc)))

    def build_data(ctx: BuildContext) -> None:
        ctx.publish(AUDIT_REPOSITORY, audit)
        ctx.ok("audit")

    def build_capture(ctx: BuildContext) -> None:
        if not configured:
            return
        state = ctx.app.state
        state.interaction_capture = edge
        state.interaction_capture_stats = stats
        state.interaction_capture_policy_store = store
        state.interaction_capture_off_reason = "setting_off" if off_reason is _UNSET else off_reason

    chain = (
        authz_builder.BUILDER,
        BuilderSpec("stub-data", ("audit",), build_data),
        BuilderSpec("stub-capture", (), build_capture),
    )
    return AdminWorld(compose(overrides, builders=chain, clock=clock), store, audit_store)
