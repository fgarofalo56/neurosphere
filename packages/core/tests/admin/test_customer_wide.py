"""Customer-wide authority on the reserved control domain (PRP-65 item 1, #114 schema half)."""

from __future__ import annotations

import pytest
from neurosphere_core.auth.scope import (
    CUSTOMER_CONTROL_DOMAIN_NAME,
    CUSTOMER_CONTROL_SOURCE,
    Permission,
    PolicyRoleAssignment,
    Role,
    customer_control_domain_id,
    permits,
    permits_customer_wide,
)
from neurosphere_core.scope import IdentityScope

from .admin_helpers import (
    CONTROL,
    FINANCE,
    GOV_CONTROL,
    OPERATIONS,
    OTHER_CUSTOMER_CONTROL,
    FakeClock,
    at,
    make_claims,
    make_deriver,
    make_repo,
    principal_policy,
    role,
)

P = Permission


def test_control_domain_id_matches_the_kill_switch_convention() -> None:
    assert (CUSTOMER_CONTROL_SOURCE, CUSTOMER_CONTROL_DOMAIN_NAME) == (
        "neurosphere",
        "customer-control",
    )
    assert customer_control_domain_id("commercial", "contoso") == CONTROL
    assert customer_control_domain_id("government", "contoso") == GOV_CONTROL


@pytest.mark.parametrize(
    ("cloud", "customer"),
    [("azure", "contoso"), ("", "contoso"), ("commercial", ""), ("commercial", "a:b")],
)
def test_control_domain_id_refuses_malformed_segments(cloud: str, customer: str) -> None:
    with pytest.raises(ValueError):
        customer_control_domain_id(cloud, customer)


async def _scope(
    *roles_: PolicyRoleAssignment,
    memberships: tuple[str, ...] = (FINANCE, CONTROL),
    clock: FakeClock | None = None,
) -> IdentityScope:
    policy = principal_policy(memberships=memberships, roles=tuple(roles_))
    deriver = make_deriver(make_repo(policy), clock=clock or FakeClock())
    return await deriver.from_verified_claims(make_claims())


async def test_admin_on_the_control_domain_is_customer_wide() -> None:
    scope = await _scope(role(Role.ADMIN, CONTROL, expires_in=900))
    now = at(0)
    assert permits_customer_wide(scope, P.CONFIG_MANAGE, now=now)
    assert permits_customer_wide(scope, P.LIFECYCLE_MANAGE, now=now)
    # Only the permissions the role confers: admin holds no audit export.
    assert not permits_customer_wide(scope, P.AUDIT_EXPORT, now=now)
    assert not permits_customer_wide(scope, P.ACTION_EXECUTE, now=now)


async def test_auditor_on_the_control_domain_exports_customer_wide() -> None:
    scope = await _scope(role(Role.SECURITY_AUDITOR, CONTROL, expires_in=900))
    assert permits_customer_wide(scope, P.AUDIT_EXPORT, now=at(0))
    assert not permits_customer_wide(scope, P.CONFIG_MANAGE, now=at(0))


async def test_ordinary_domains_never_satisfy_customer_wide() -> None:
    scope = await _scope(
        role(Role.ADMIN, FINANCE, OPERATIONS, expires_in=900),
        memberships=(FINANCE, OPERATIONS),
    )
    now = at(0)
    assert permits(scope, P.CONFIG_MANAGE, domain_id=FINANCE, now=now)
    assert not permits_customer_wide(scope, P.CONFIG_MANAGE, now=now)


async def test_expired_control_assignment_is_not_customer_wide() -> None:
    clock = FakeClock()
    scope = await _scope(role(Role.ADMIN, CONTROL, expires_in=60), clock=clock)
    assert permits_customer_wide(scope, P.CONFIG_MANAGE, now=clock.datetime())
    clock.advance(60)
    assert not permits_customer_wide(scope, P.CONFIG_MANAGE, now=clock.datetime())


async def test_cross_customer_and_cross_cloud_control_domains_never_match() -> None:
    scope = await _scope(
        role(Role.ADMIN, OTHER_CUSTOMER_CONTROL, GOV_CONTROL, expires_in=900),
        memberships=(FINANCE, OTHER_CUSTOMER_CONTROL, GOV_CONTROL),
    )
    now = at(0)
    assert not permits_customer_wide(scope, P.CONFIG_MANAGE, now=now)
    for foreign in (OTHER_CUSTOMER_CONTROL, GOV_CONTROL):
        assert not permits(scope, P.CONFIG_MANAGE, domain_id=foreign, now=now)


async def test_control_assignment_without_membership_is_clipped() -> None:
    scope = await _scope(role(Role.ADMIN, CONTROL, expires_in=900), memberships=(FINANCE,))
    assert not permits_customer_wide(scope, P.CONFIG_MANAGE, now=at(0))


def test_customer_wide_refuses_non_scope_objects() -> None:
    with pytest.raises(TypeError):
        permits_customer_wide({"customer_id": "contoso"}, P.CONFIG_MANAGE, now=at(0))  # type: ignore[arg-type]


def test_api_kill_switch_constants_are_unchanged() -> None:
    """customer_control.py keeps its own copy until PRP-48; core and API must agree."""
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[4]
        / "services/api/neurosphere_api/actions/customer_control.py"
    ).read_text(encoding="utf-8")
    assert f'CUSTOMER_CONTROL_SOURCE: Final = "{CUSTOMER_CONTROL_SOURCE}"' in source
    assert f'CUSTOMER_CONTROL_DOMAIN_NAME: Final = "{CUSTOMER_CONTROL_DOMAIN_NAME}"' in source
