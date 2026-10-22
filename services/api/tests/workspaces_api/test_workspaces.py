"""``GET /api/v1/workspaces/{role}`` (PRP-28 item 1): explicit role map, 404/403/200 semantics."""

from __future__ import annotations

import pytest
from authz.authz_helpers import (  # pyright: ignore[reportMissingImports]
    ALICE,
    BOB,
    CAROL,
    FINANCE,
    NOBODY,
    Harness,
    harness,
    policy,
    role,
)
from neurosphere_api.workspaces import ROLE_MAP
from neurosphere_core.auth.scope import Role

STEWARD = "a1b2c3d4-0000-4000-8000-000000000002"
ADMIN = "a1b2c3d4-0000-4000-8000-000000000003"
AUDITOR = "a1b2c3d4-0000-4000-8000-000000000004"
EXPIRED = "a1b2c3d4-0000-4000-8000-000000000005"


def _make() -> Harness:
    return harness(
        policy(ALICE, role(Role.VIEWER, FINANCE)),
        policy(BOB, role(Role.ANALYST, FINANCE)),
        policy(STEWARD, role(Role.DOMAIN_STEWARD, FINANCE)),
        policy(ADMIN, role(Role.ADMIN, FINANCE)),
        policy(AUDITOR, role(Role.SECURITY_AUDITOR, FINANCE)),
        policy(CAROL, role(Role.VIEWER, FINANCE)),
        # A viewer role that expired before "now" must not open the workspace.
        policy(EXPIRED, role(Role.VIEWER, FINANCE, expires_in=-60)),
    )


def test_role_map_is_explicit() -> None:
    assert dict(ROLE_MAP) == {
        "viewer": Role.VIEWER,
        "analyst": Role.ANALYST,
        "steward": Role.DOMAIN_STEWARD,
        "admin": Role.ADMIN,
        "auditor": Role.SECURITY_AUDITOR,
    }


@pytest.mark.parametrize(
    ("who", "persona"),
    [
        (ALICE, "viewer"),
        (BOB, "analyst"),
        (STEWARD, "steward"),
        (ADMIN, "admin"),
        (AUDITOR, "auditor"),
    ],
)
def test_held_role_returns_200_with_mock_shape(who: str, persona: str) -> None:
    h = _make()
    response = h.client.get(f"/api/v1/workspaces/{persona}", headers=h.auth(who))
    assert response.status_code == 200, response.text
    assert response.json() == {"workspace": persona, "items": []}


@pytest.mark.parametrize("persona", ["analyst", "steward", "admin", "auditor"])
def test_role_not_held_is_403_forbidden(persona: str) -> None:
    h = _make()
    response = h.client.get(f"/api/v1/workspaces/{persona}", headers=h.auth(ALICE))
    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"


def test_backend_role_names_are_not_frontend_names() -> None:
    h = _make()
    for name in ("domain_steward", "security_auditor", "Viewer", "owner"):
        response = h.client.get(f"/api/v1/workspaces/{name}", headers=h.auth(STEWARD))
        assert response.status_code == 404, name


def test_unknown_role_is_404() -> None:
    h = _make()
    assert h.client.get("/api/v1/workspaces/nope", headers=h.auth(ALICE)).status_code == 404


def test_unauthenticated_is_401() -> None:
    h = _make()
    assert h.client.get("/api/v1/workspaces/viewer").status_code == 401
    assert h.client.get("/api/v1/workspaces/nope").status_code == 401


def test_principal_without_policy_holds_no_role() -> None:
    h = _make()
    response = h.client.get("/api/v1/workspaces/viewer", headers=h.auth(NOBODY))
    assert response.status_code == 403


def test_expired_assignment_does_not_hold_the_role() -> None:
    h = _make()
    response = h.client.get("/api/v1/workspaces/viewer", headers=h.auth(EXPIRED))
    assert response.status_code == 403


def test_request_cannot_name_a_role() -> None:
    h = _make()
    headers = {**h.auth(ALICE), "X-Role": "admin", "X-Roles": "admin"}
    response = h.client.get(
        "/api/v1/workspaces/admin", headers=headers, params={"role": "admin", "roles": "admin"}
    )
    assert response.status_code == 403


def test_hidden_route_semantics_viewer_session_gets_403_forbidden_on_admin() -> None:
    """frontend/tests/e2e/hidden-route.spec.ts: the stub session is a viewer; /workspaces/admin
    still reaches the API, which answers 403 with code ``forbidden`` (not a hidden 404)."""
    h = _make()
    admin = h.client.get("/api/v1/workspaces/admin", headers=h.auth(ALICE))
    assert admin.status_code == 403
    assert admin.json()["code"] == "forbidden"
    own = h.client.get("/api/v1/workspaces/viewer", headers=h.auth(ALICE))
    assert own.status_code == 200
