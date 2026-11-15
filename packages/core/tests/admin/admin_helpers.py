"""Shared builders for the PRP-65 admin tests: clock, claims, deriver and policy documents.

Self-contained (no import from another test package) so the directory cannot shadow or be
shadowed by a same-named helper elsewhere in one pytest session.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from neurosphere_core.auth.jwt import VerifiedClaims
from neurosphere_core.auth.scope import (
    InMemoryPolicyRepository,
    NoRevocationCheck,
    PolicyRepository,
    PolicyRoleAssignment,
    PrincipalPolicy,
    PrincipalPseudonymizer,
    PseudonymKey,
    Role,
    ScopeDerivationConfig,
    ScopeDeriver,
    principal_document_id,
)
from neurosphere_core.cloud import CloudName

TENANT = "0f1e2d3c-4b5a-4968-8776-a5b4c3d2e1f0"
OBJECT_ID = "6c1d2e3f-4a5b-4c6d-8e7f-90a1b2c3d4e5"
OTHER_OBJECT_ID = "1a2b3c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d"
CUSTOMER = "contoso"
T0 = 1_800_000_000.0
KEY_MATERIAL = bytes(range(32))
KEY_REFERENCE = "https://ns-test-kv.vault.azure.net/secrets/principal-pseudonym-key"

FINANCE = "commercial:contoso:catalog:domain:finance"
OPERATIONS = "commercial:contoso:catalog:domain:operations"
CONTROL = "commercial:contoso:neurosphere:domain:customer-control"
OTHER_CUSTOMER_CONTROL = "commercial:fabrikam:neurosphere:domain:customer-control"
GOV_CONTROL = "government:contoso:neurosphere:domain:customer-control"


class FakeClock:
    def __init__(self, now: float = T0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds

    def datetime(self) -> datetime:
        return datetime.fromtimestamp(self.now, UTC)


def at(offset_seconds: float) -> datetime:
    return datetime.fromtimestamp(T0, UTC) + timedelta(seconds=offset_seconds)


def make_claims(*, object_id: str = OBJECT_ID) -> VerifiedClaims:
    fields: dict[str, Any] = {
        "issuer_kind": "entra",
        "cloud": CloudName.COMMERCIAL,
        "issuer": f"https://login.microsoftonline.com/{TENANT}/v2.0",
        "audience": "api://neurosphere-test-api",
        "tenant_id": TENANT,
        "object_id": object_id,
        "subject": "subject-" + object_id[:8],
        "token_version": "2.0",
        "issued_at": at(-60),
        "not_before": at(-60),
        "expires_at": at(3600),
        "identity_type": "user",
    }
    return VerifiedClaims(**fields)


def pseudonymizer() -> PrincipalPseudonymizer:
    return PrincipalPseudonymizer(PseudonymKey(KEY_MATERIAL, reference=KEY_REFERENCE))


def principal_id_for(object_id: str = OBJECT_ID) -> str:
    return f"commercial:{CUSTOMER}:entra:person:{pseudonymizer().pseudonym(TENANT, object_id)}"


def role(
    role_: Role, *domains: str, expires_in: float | None = None, assignment_id: str | None = None
) -> PolicyRoleAssignment:
    return PolicyRoleAssignment(
        assignment_id=assignment_id or f"ra-{role_.value}-{len(domains)}",
        role=role_,
        domain_ids=domains,
        expires_at=None if expires_in is None else at(expires_in),
    )


def principal_policy(
    *,
    memberships: tuple[str, ...] = (FINANCE, OPERATIONS),
    roles: tuple[PolicyRoleAssignment, ...] = (),
    object_id: str = OBJECT_ID,
    customer_id: str = CUSTOMER,
) -> PrincipalPolicy:
    pid = principal_id_for(object_id)
    return PrincipalPolicy(
        id=principal_document_id(pid),
        customer_id=customer_id,
        principal_id=pid,
        domain_memberships=memberships,
        role_assignments=roles,
    )


def make_repo(policy: PrincipalPolicy | None = None) -> InMemoryPolicyRepository:
    from neurosphere_core.auth.scope import PolicyHead

    repo = InMemoryPolicyRepository()
    repo.put_head(PolicyHead(customer_id=CUSTOMER, policy_version="local-1"))
    if policy is not None:
        repo.put_principal(policy)
    return repo


def make_deriver(
    repo: PolicyRepository, *, clock: FakeClock | None = None, **config: Any
) -> ScopeDeriver:
    cfg = ScopeDerivationConfig(
        cloud=CloudName.COMMERCIAL, tenant_id=TENANT, customer_id=CUSTOMER, **config
    )
    return ScopeDeriver(
        cfg,
        policy_repository=repo,
        pseudonymizer=pseudonymizer(),
        revocation_checker=NoRevocationCheck(),
        clock=clock or FakeClock(),
    )
