"""PRP-104 item 1: assigning ``interaction_investigator`` through the identity admin API.

The role is privileged (customer-wide ``policy.manage``, an expiry is required), capped at 7 days
(GD-16, ``role_assignment_too_long``), never self-assignable, and its two permissions are held
by no other role: the assigning admin never gains ``interaction.read`` / ``interaction.export``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from authz.authz_helpers import T0  # pyright: ignore[reportMissingImports]
from fastapi.testclient import TestClient
from identity_harness import (  # pyright: ignore[reportMissingImports]
    BASE,
    CUSTOMER_ADMIN,
    DOMAIN_ADMIN,
    FINANCE,
    TARGET,
    IdentityWorld,
    configure_env,
    pid,
)
from neurosphere_core.auth.scope import Role

INVESTIGATOR = "interaction_investigator"
CONTENT_PERMISSIONS = {"interaction.read", "interaction.export"}
DAY = 24 * 3600


@pytest.fixture(autouse=True)
def _auth(monkeypatch: pytest.MonkeyPatch) -> None:
    configure_env(monkeypatch)


@pytest.fixture
def world() -> IdentityWorld:
    return IdentityWorld.build()


def _ts(offset: float) -> str:
    return (datetime.fromtimestamp(T0, UTC) + timedelta(seconds=offset)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _body(target: str, assignment_id: str, **extra: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "schema_version": "1.0.0",
        "op": "assign",
        "principal_id": pid(target),
        "assignment_id": assignment_id,
        "role": INVESTIGATOR,
        "domain_ids": [FINANCE],
        "reason": "access_request",
    }
    body.update(extra)
    return body


def _etag(client: TestClient, world: IdentityWorld, actor: str, target: str) -> str:
    response = client.get(f"{BASE}/principals/{pid(target)}", headers=world.auth(actor))
    assert response.status_code == 200, response.text
    return response.headers["ETag"]


def _put(client: TestClient, world: IdentityWorld, actor: str, target: str, **extra: Any) -> Any:
    url = f"{BASE}/principals/{pid(target)}/role-assignments/ra-investigator"
    etag = _etag(client, world, actor, target)
    return client.put(
        url,
        json=_body(target, "ra-investigator", **extra),
        headers=world.auth(actor, **{"If-Match": etag}),
    )


def _investigator_roles(world: IdentityWorld, object_id: str) -> list[Any]:
    stored = world.stored(object_id)
    assert stored is not None
    return [a for a in stored.role_assignments if a.role is Role.INTERACTION_INVESTIGATOR]


def _domain_permissions(client: TestClient, world: IdentityWorld, actor: str) -> set[str]:
    response = client.get("/api/v1/me/domains", headers=world.auth(actor))
    assert response.status_code == 200, response.text
    return {p for item in response.json()["items"] for p in item["permissions"]}


def test_admin_assigns_investigator_for_up_to_seven_days(world: IdentityWorld) -> None:
    with world.composed.client() as client:
        response = _put(client, world, CUSTOMER_ADMIN, TARGET, expires_at=_ts(7 * DAY))
        assert response.status_code == 200, response.text
        target_permissions = _domain_permissions(client, world, TARGET)
    [assignment] = _investigator_roles(world, TARGET)
    assert assignment.domain_ids == (FINANCE,)
    assert CONTENT_PERMISSIONS <= target_permissions


def test_assignment_longer_than_seven_days_is_refused(world: IdentityWorld) -> None:
    with world.composed.client() as client:
        response = _put(client, world, CUSTOMER_ADMIN, TARGET, expires_at=_ts(7 * DAY + 1))
    assert response.status_code == 422, response.text
    assert response.json()["reason"] == "role_assignment_too_long"
    assert _investigator_roles(world, TARGET) == []


def test_assignment_without_expiry_is_refused(world: IdentityWorld) -> None:
    with world.composed.client() as client:
        response = _put(client, world, CUSTOMER_ADMIN, TARGET)
    assert response.status_code == 422, response.text
    assert _investigator_roles(world, TARGET) == []


def test_domain_admin_needs_customer_wide_authority(world: IdentityWorld) -> None:
    with world.composed.client() as client:
        response = _put(client, world, DOMAIN_ADMIN, TARGET, expires_at=_ts(DAY))
    assert response.status_code == 403, response.text
    assert response.json()["reason"] == "customer_scope_required"
    assert _investigator_roles(world, TARGET) == []


def test_admin_cannot_assign_investigator_to_themselves(world: IdentityWorld) -> None:
    with world.composed.client() as client:
        url = f"{BASE}/principals/{pid(CUSTOMER_ADMIN)}/role-assignments/ra-investigator"
        response = client.put(
            url,
            json=_body(CUSTOMER_ADMIN, "ra-investigator", expires_at=_ts(DAY)),
            headers=world.auth(CUSTOMER_ADMIN),
        )
    assert response.status_code == 403, response.text
    assert response.json()["reason"] == "self_modification_forbidden"
    assert _investigator_roles(world, CUSTOMER_ADMIN) == []
    assert any(
        r["kind"] == "denied" and r["denial"]["reason"] == "self_modification_forbidden"
        for r in world.all_records()
    )


def test_admin_holds_neither_content_permission(world: IdentityWorld) -> None:
    with world.composed.client() as client:
        response = _put(client, world, CUSTOMER_ADMIN, TARGET, expires_at=_ts(DAY))
        assert response.status_code == 200, response.text
        admin_permissions = _domain_permissions(client, world, CUSTOMER_ADMIN)
    assert "policy.manage" in admin_permissions
    assert not admin_permissions & CONTENT_PERMISSIONS
