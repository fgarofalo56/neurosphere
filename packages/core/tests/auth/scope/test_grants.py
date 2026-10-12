"""Resource-scoped grants: one named resource, time-bound, reason-bearing; narrow, never widen."""

from __future__ import annotations

import pytest
from neurosphere_core.auth.scope import Permission, PolicyGrant, Role, permits
from pydantic import ValidationError

from .scope_helpers import (
    AGENT,
    FINANCE,
    OPERATIONS,
    OTHER_AGENT,
    FakeClock,
    at,
    grant,
    make_claims,
    make_deriver,
    make_repo,
    principal_policy,
    role,
)

P = Permission


async def test_grant_applies_to_exactly_the_named_resource() -> None:
    policy = principal_policy(roles=(), grants=(grant(AGENT, "read"),))
    scope = await make_deriver(make_repo(policy)).from_verified_claims(make_claims())
    now = at(0)
    assert permits(scope, P.DATA_READ, resource_id=AGENT, now=now)
    assert not permits(scope, P.DATA_EXPORT, resource_id=AGENT, now=now)
    assert not permits(scope, P.DATA_READ, resource_id=OTHER_AGENT, now=now)
    assert not permits(scope, P.DATA_READ, domain_id=FINANCE, now=now)


async def test_grant_never_adds_roles_or_domains() -> None:
    policy = principal_policy(
        roles=(role(Role.VIEWER, FINANCE),),
        grants=(grant(AGENT, "read", "export", "propose_action", "approve", "execute"),),
    )
    scope = await make_deriver(make_repo(policy)).from_verified_claims(make_claims())
    contract = scope.to_contract()
    assert scope.allowed_domains == (FINANCE,)
    assert [r.role for r in contract.roles] == ["viewer"]
    assert not permits(scope, P.ACTION_APPROVE, domain_id=FINANCE, now=at(0))
    assert permits(scope, P.ACTION_APPROVE, resource_id=AGENT, now=at(0))


@pytest.mark.parametrize(
    "resource",
    [
        FINANCE,  # a domain-typed grant would widen to a whole domain
        "commercial:fabrikam:foundry:agent:support-bot",  # other customer
        "government:contoso:foundry:agent:support-bot",  # other cloud
    ],
)
async def test_widening_or_foreign_grants_are_dropped(resource: str) -> None:
    policy = principal_policy(grants=(grant(resource, "read"),))
    derivation = await make_deriver(make_repo(policy)).derive(make_claims())
    assert derivation.scope.to_contract().allowed_resources == []
    assert derivation.grant_ids == ()
    assert not permits(derivation.scope, P.DATA_READ, resource_id=resource, now=at(0))


async def test_grant_expires_with_fake_clock() -> None:
    clock = FakeClock()
    policy = principal_policy(
        roles=(role(Role.VIEWER, FINANCE),), grants=(grant(AGENT, "read", expires_in=120),)
    )
    deriver = make_deriver(make_repo(policy), clock=clock, policy_cache_ttl_seconds=10)

    active = await deriver.derive(make_claims())
    assert active.grant_ids == ("g-1",)
    expires_at = active.scope.to_contract().expires_at
    assert expires_at is not None
    assert expires_at.root == "2027-01-15T08:02:00Z"  # scope never outlives its shortest grant

    clock.advance(119.999)
    assert permits(active.scope, P.DATA_READ, resource_id=AGENT, now=clock.datetime())
    still = await deriver.derive(make_claims())
    assert still.grant_ids == ("g-1",)

    clock.advance(0.001)  # exactly at expiry: expired
    assert not permits(active.scope, P.DATA_READ, resource_id=AGENT, now=clock.datetime())
    expired = await deriver.derive(make_claims())
    assert expired.grant_ids == ()
    assert expired.scope.to_contract().allowed_resources == []
    assert expired.scope.allowed_domains == (FINANCE,)


async def test_privileged_role_reads_only_the_granted_resource() -> None:
    policy = principal_policy(
        memberships=(FINANCE,),
        roles=(role(Role.SECURITY_AUDITOR, FINANCE, expires_in=900),),
        grants=(grant(AGENT, "read", grant_id="g-elevated"),),
    )
    scope = await make_deriver(make_repo(policy)).from_verified_claims(make_claims())
    now = at(0)
    assert permits(scope, P.DATA_READ, resource_id=AGENT, now=now)
    assert not permits(scope, P.DATA_READ, resource_id=OTHER_AGENT, now=now)
    assert not permits(scope, P.DATA_READ, domain_id=FINANCE, now=now)
    assert not permits(scope, P.DATA_READ, domain_id=OPERATIONS, now=now)


def test_grant_requires_expiry_and_reason() -> None:
    base = {"grant_id": "g-1", "resource_id": AGENT, "permissions": ["read"]}
    with pytest.raises(ValidationError):
        PolicyGrant.model_validate({**base, "reason": "x"})
    with pytest.raises(ValidationError):
        PolicyGrant.model_validate({**base, "expires_at": at(60)})
    with pytest.raises(ValidationError):
        PolicyGrant.model_validate({**base, "expires_at": at(60), "reason": ""})


@pytest.mark.parametrize("perm", ["admin", "*", "bypass", "data.read"])
def test_grant_permissions_are_the_closed_contract_set(perm: str) -> None:
    with pytest.raises(ValidationError):
        PolicyGrant.model_validate(
            {
                "grant_id": "g-1",
                "resource_id": AGENT,
                "permissions": [perm],
                "expires_at": at(60),
                "reason": "x",
            }
        )


def test_grant_resource_must_be_a_canonical_id() -> None:
    with pytest.raises(ValidationError):
        grant("commercial:contoso:catalog:domain:*", "read")
