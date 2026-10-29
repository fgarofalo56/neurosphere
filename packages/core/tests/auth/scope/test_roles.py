"""Fixed five roles, documented permission sets, no bypass, privileged roles scoped and timed."""

from __future__ import annotations

import typing

import pytest
from neurosphere_contracts.scope.v1.identity_scope import RoleAssignment
from neurosphere_core.auth.scope import (
    GRANT_PERMISSIONS,
    PRIVILEGED_ROLES,
    ROLE_PERMISSIONS,
    Permission,
    PolicyRoleAssignment,
    Role,
    domains_with_permission,
    permits,
    role_permissions,
)
from pydantic import ValidationError

from .scope_helpers import (
    FINANCE,
    GOV_FINANCE,
    HR,
    OPERATIONS,
    OTHER_CUSTOMER_FINANCE,
    FakeClock,
    at,
    make_claims,
    make_deriver,
    make_repo,
    principal_policy,
    role,
)

P = Permission

EXPECTED = {
    Role.VIEWER: {P.DATA_READ, P.GRANT_READ},
    Role.ANALYST: {P.DATA_READ, P.GRANT_READ, P.DATA_EXPORT, P.REPORT_CREATE, P.ACTION_PROPOSE},
    Role.DOMAIN_STEWARD: {
        P.DATA_READ,
        P.GRANT_READ,
        P.DATA_EXPORT,
        P.REPORT_CREATE,
        P.ACTION_PROPOSE,
        P.CATALOG_CURATE,
        P.ACTION_APPROVE,
        P.ACTION_EXECUTE,
        P.GRANT_WRITE,
    },
    Role.ADMIN: {
        P.DATA_READ,
        P.CONFIG_MANAGE,
        P.POLICY_MANAGE,
        P.REVOCATION_MANAGE,
        P.GRANT_READ,
        P.GRANT_WRITE,
    },
    Role.SECURITY_AUDITOR: {P.AUDIT_READ, P.EVIDENCE_READ},
}
# Held by Admin and Domain Steward alike (PRP-33 item 5), so not an admin-only permission.
SHARED_ADMIN_STEWARD = {P.GRANT_WRITE}


@pytest.mark.parametrize("role_", list(Role))
def test_each_role_has_exactly_the_documented_permissions(role_: Role) -> None:
    assert role_permissions(role_) == EXPECTED[role_]
    assert ROLE_PERMISSIONS[role_] == EXPECTED[role_]


def test_role_set_is_closed_and_matches_contract() -> None:
    contract_roles = set(
        typing.get_args(RoleAssignment.model_fields["role"].annotation)  # Literal members
    )
    assert {r.value for r in Role} == contract_roles
    assert len(Role) == 5
    for not_a_role in ("pro", "analyst_pro", "superuser", "owner", "god"):
        with pytest.raises(ValueError):
            role_permissions(not_a_role)


def test_analyst_pro_never_implies_admin() -> None:
    admin_only = EXPECTED[Role.ADMIN] - EXPECTED[Role.VIEWER] - SHARED_ADMIN_STEWARD
    assert admin_only == {P.CONFIG_MANAGE, P.POLICY_MANAGE, P.REVOCATION_MANAGE}
    assert not role_permissions(Role.ANALYST) & admin_only
    assert not role_permissions(Role.ANALYST) & SHARED_ADMIN_STEWARD
    assert not role_permissions(Role.DOMAIN_STEWARD) & admin_only


def test_grant_permissions_follow_the_catalog_grant_mapping() -> None:
    """grant.read for every data-reading role; grant.write only for Steward and Admin."""
    readers = {r for r in Role if P.GRANT_READ in role_permissions(r)}
    writers = {r for r in Role if P.GRANT_WRITE in role_permissions(r)}
    assert readers == {Role.VIEWER, Role.ANALYST, Role.DOMAIN_STEWARD, Role.ADMIN}
    assert writers == {Role.DOMAIN_STEWARD, Role.ADMIN}
    assert not {P.GRANT_READ, P.GRANT_WRITE} & role_permissions(Role.SECURITY_AUDITOR)
    assert (P.GRANT_READ.value, P.GRANT_WRITE.value) == ("grant.read", "grant.write")
    # Unrelated to resource-scoped grants: no GRANT_PERMISSIONS entry maps to grant.*.
    assert not {P.GRANT_READ, P.GRANT_WRITE} & set(GRANT_PERMISSIONS.values())


async def test_grant_write_is_scoped_to_the_steward_domains() -> None:
    policy = principal_policy(
        memberships=(FINANCE, OPERATIONS),
        roles=(role(Role.DOMAIN_STEWARD, FINANCE), role(Role.VIEWER, OPERATIONS)),
    )
    scope = await make_deriver(make_repo(policy)).from_verified_claims(make_claims())
    now = at(0)
    assert permits(scope, P.GRANT_WRITE, domain_id=FINANCE, now=now)
    assert permits(scope, P.GRANT_READ, domain_id=OPERATIONS, now=now)
    assert not permits(scope, P.GRANT_WRITE, domain_id=OPERATIONS, now=now)
    for other in (HR, OTHER_CUSTOMER_FINANCE, GOV_FINANCE):
        assert not permits(scope, P.GRANT_READ, domain_id=other, now=now)
        assert not permits(scope, P.GRANT_WRITE, domain_id=other, now=now)


def test_auditor_has_no_data_permissions() -> None:
    auditor = role_permissions(Role.SECURITY_AUDITOR)
    assert not {p for p in auditor if p.value.startswith(("data.", "action.", "report."))}
    assert P.DATA_READ not in auditor


def test_no_bypass_permission_or_all_powerful_role_exists() -> None:
    every = set(Permission)
    for value in (p.value for p in Permission):
        assert not any(tok in value for tok in ("*", "all", "bypass", "super", "god", "root"))
    for role_ in Role:
        assert role_permissions(role_) != every
    assert not {P.AUDIT_READ, P.EVIDENCE_READ} & role_permissions(Role.ADMIN)
    assert not {P.ACTION_APPROVE, P.ACTION_EXECUTE} & role_permissions(Role.ADMIN)


@pytest.mark.parametrize("role_", sorted(PRIVILEGED_ROLES))
def test_privileged_assignment_without_expiry_is_rejected(role_: Role) -> None:
    with pytest.raises(ValidationError):
        PolicyRoleAssignment(assignment_id="ra-1", role=role_, domain_ids=(FINANCE,))


def test_role_assignment_requires_a_domain() -> None:
    with pytest.raises(ValidationError):
        PolicyRoleAssignment(assignment_id="ra-1", role=Role.VIEWER, domain_ids=())


async def test_auditor_scope_reads_audit_but_no_domain_data() -> None:
    policy = principal_policy(roles=(role(Role.SECURITY_AUDITOR, FINANCE, expires_in=900),))
    scope = await make_deriver(make_repo(policy)).from_verified_claims(make_claims())
    now = at(0)
    assert scope.allowed_domains == ()
    assert permits(scope, P.AUDIT_READ, domain_id=FINANCE, now=now)
    assert not permits(scope, P.DATA_READ, domain_id=FINANCE, now=now)
    assert domains_with_permission(scope, P.DATA_READ, now=now) == frozenset()


async def test_admin_is_scoped_to_its_domains() -> None:
    policy = principal_policy(
        memberships=(FINANCE, OPERATIONS), roles=(role(Role.ADMIN, OPERATIONS, expires_in=900),)
    )
    scope = await make_deriver(make_repo(policy)).from_verified_claims(make_claims())
    now = at(0)
    assert permits(scope, P.CONFIG_MANAGE, domain_id=OPERATIONS, now=now)
    for other in (FINANCE, HR, OTHER_CUSTOMER_FINANCE, GOV_FINANCE):
        assert not permits(scope, P.CONFIG_MANAGE, domain_id=other, now=now)
        assert not permits(scope, P.DATA_READ, domain_id=other, now=now)
    contract = scope.to_contract()
    assert contract.roles[0].expires_at is not None


async def test_role_assignment_is_clipped_to_domain_membership() -> None:
    policy = principal_policy(
        memberships=(FINANCE,),
        roles=(role(Role.DOMAIN_STEWARD, FINANCE, HR, OTHER_CUSTOMER_FINANCE, GOV_FINANCE),),
    )
    scope = await make_deriver(make_repo(policy)).from_verified_claims(make_claims())
    assert scope.allowed_domains == (FINANCE,)
    assert [d.root for d in scope.to_contract().roles[0].domain_ids] == [FINANCE]


async def test_foreign_membership_never_widens() -> None:
    policy = principal_policy(
        memberships=(FINANCE, OTHER_CUSTOMER_FINANCE, GOV_FINANCE),
        roles=(role(Role.VIEWER, OTHER_CUSTOMER_FINANCE, GOV_FINANCE),),
    )
    scope = await make_deriver(make_repo(policy)).from_verified_claims(make_claims())
    assert scope.allowed_domains == ()
    assert scope.to_contract().roles == []


async def test_expired_role_contributes_nothing() -> None:
    clock = FakeClock()
    policy = principal_policy(
        roles=(
            role(Role.VIEWER, FINANCE, assignment_id="ra-viewer"),
            role(Role.ADMIN, OPERATIONS, expires_in=60, assignment_id="ra-admin"),
        )
    )
    deriver = make_deriver(make_repo(policy), clock=clock, policy_cache_ttl_seconds=5)
    before = await deriver.derive(make_claims())
    assert before.assignment_ids == ("ra-admin", "ra-viewer")
    assert permits(before.scope, P.CONFIG_MANAGE, domain_id=OPERATIONS, now=clock.datetime())

    clock.advance(60)
    after = await deriver.derive(make_claims())
    assert after.assignment_ids == ("ra-viewer",)
    assert after.scope.allowed_domains == (FINANCE,)
    assert not permits(after.scope, P.CONFIG_MANAGE, domain_id=OPERATIONS, now=clock.datetime())
    # A scope derived earlier stops conferring the role once its expiry passes.
    assert not permits(before.scope, P.CONFIG_MANAGE, domain_id=OPERATIONS, now=clock.datetime())


async def test_roles_union_across_assignments() -> None:
    policy = principal_policy(
        roles=(role(Role.VIEWER, FINANCE), role(Role.DOMAIN_STEWARD, OPERATIONS)),
    )
    scope = await make_deriver(make_repo(policy)).from_verified_claims(make_claims())
    now = at(0)
    assert permits(scope, P.ACTION_APPROVE, domain_id=OPERATIONS, now=now)
    assert not permits(scope, P.ACTION_APPROVE, domain_id=FINANCE, now=now)
    assert domains_with_permission(scope, P.DATA_READ, now=now) == {FINANCE, OPERATIONS}


async def test_permits_requires_a_target() -> None:
    policy = principal_policy(roles=(role(Role.VIEWER, FINANCE),))
    scope = await make_deriver(make_repo(policy)).from_verified_claims(make_claims())
    with pytest.raises(ValueError):
        permits(scope, P.DATA_READ, now=at(0))


def test_permits_refuses_non_scope_objects() -> None:
    with pytest.raises(TypeError):
        permits({"allowed_domains": [FINANCE]}, P.DATA_READ, domain_id=FINANCE, now=at(0))  # type: ignore[arg-type]
