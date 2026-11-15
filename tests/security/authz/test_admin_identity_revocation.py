"""ABAC negative suite for the identity admin REVOCATION routes (PRP-39 item 5).

Revocation is customer-scoped by design (Clarification 5: ``revocation.manage`` in any domain,
target in the actor's own cloud and customer), so the dimensions map as follows:

=================================  ==========================================================
Dimension                          Expected refusal
=================================  ==========================================================
cross-customer target              403 ``cross_scope_target`` (a ``denied`` revocation event)
cross-cloud target                 403 ``cross_scope_target`` (a ``denied`` revocation event)
cross-domain actor                 403 ``permission_missing``: holding only non-admin roles in
                                   another domain grants no revocation authority
self (blocked actor lifting)       403 ``principal_revoked``: a blocked admin cannot lift their
                                   own block, every token is refused
privileged without customer scope  403 ``permission_missing`` for a security auditor (audit
                                   authority never implies revocation authority)
expired assignment                 403 ``permission_missing``
revoked actor                      403 ``principal_revoked``
=================================  ==========================================================

Nothing is written to the revocation store on any refusal.
"""

from __future__ import annotations

from typing import Any

import pytest
from neurosphere_core.auth.scope import Role

from .test_admin_identity import (
    ADMIN,
    ANALYST,
    BASE,
    CUSTOMER_ADMIN_OID,
    EXPIRED_ADMIN_OID,
    FABRIKAM_ANALYST,
    FIN,
    OPS,
    bearer_for,
    install,
    principal_id_for,
)
from .world import Deployment, Who, World, run

ROUTES = ("POST", "GET", "DELETE")


@pytest.fixture
def iworld(world: World) -> World:
    return install(world)


def _call(dep: Deployment, method: str, target: str, headers: dict[str, str]) -> Any:
    body = (
        {"schema_version": "1.0.0", "reason": "compromised", "mode": "until_lifted"}
        if method == "POST"
        else None
    )
    return dep.client.request(method, f"{BASE}/{target}/revocation", headers=headers, json=body)


def _stored(dep: Deployment, target: str) -> Any:
    if target.split(":")[1] != dep.customer or not target.startswith("commercial:"):
        return None
    return run(dep.revocation_store.get(target))


@pytest.mark.parametrize("method", ROUTES)
@pytest.mark.parametrize("dimension", ["customer", "cloud"])
def test_cross_customer_and_cross_cloud(iworld: World, method: str, dimension: str) -> None:
    dep = iworld["contoso"]
    target = principal_id_for(FABRIKAM_ANALYST)
    if dimension == "cloud":
        target = principal_id_for(ANALYST).replace("commercial:", "government:", 1)
    response = _call(dep, method, target, dep.bearer(ADMIN))
    assert response.status_code == 403, response.text
    assert response.json()["reason"] == "cross_scope_target"
    denied = [e for e in dep.revocation_auditor.events if e.phase == "denied"]
    assert [e.deny_reason for e in denied] == ["cross_scope_target"]
    assert run(iworld["fabrikam"].revocation_store.get(principal_id_for(FABRIKAM_ANALYST))) is None


@pytest.mark.parametrize("method", ROUTES)
@pytest.mark.parametrize(
    "actor",
    [Who("contoso", OPS, Role.DOMAIN_STEWARD), Who("contoso", FIN, Role.SECURITY_AUDITOR)],
    ids=["cross_domain_steward", "auditor_not_admin"],
)
def test_actors_without_revocation_manage(iworld: World, method: str, actor: Who) -> None:
    dep = iworld["contoso"]
    target = principal_id_for(ANALYST)
    response = _call(dep, method, target, dep.bearer(actor))
    assert response.status_code == 403
    assert response.json()["reason"] == "permission_missing"
    assert "permission_missing" in [a.reason for a in dep.recorder.attempts]
    assert _stored(dep, target) is None


@pytest.mark.parametrize("method", ROUTES)
def test_expired_assignment(iworld: World, method: str) -> None:
    dep = iworld["contoso"]
    iworld.clock.advance(11)
    target = principal_id_for(ANALYST)
    response = _call(dep, method, target, bearer_for(dep, EXPIRED_ADMIN_OID))
    assert response.status_code == 403
    assert response.json()["reason"] == "permission_missing"
    assert _stored(dep, target) is None


@pytest.mark.parametrize("method", ROUTES)
def test_revoked_actor(iworld: World, method: str) -> None:
    dep = iworld["contoso"]
    token = dep.bearer(ADMIN)
    dep.revoke(ADMIN, ADMIN)
    target = principal_id_for(ANALYST)
    response = _call(dep, method, target, token)
    assert response.status_code == 403
    assert response.json()["reason"] == "principal_revoked"
    assert _stored(dep, target) is None


def test_blocked_admin_cannot_lift_their_own_block(iworld: World) -> None:
    dep = iworld["contoso"]
    other_admin = bearer_for(dep, CUSTOMER_ADMIN_OID)
    me = principal_id_for(ADMIN)
    blocked = _call(dep, "POST", me, other_admin)
    assert blocked.status_code == 200, blocked.text
    iworld.clock.advance(3600)
    lift = _call(dep, "DELETE", me, dep.bearer(ADMIN))  # a fresh token, after the block
    assert lift.status_code == 403
    assert lift.json()["reason"] == "principal_revoked"
    entry = run(dep.revocation_store.get(me))
    assert entry is not None and entry.blocking
