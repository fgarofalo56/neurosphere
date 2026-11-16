"""PRP-48 item 1 (#91): ``/workspaces/{role}`` is role-gated, tenancy-bound and denial-audited."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from authz.authz_helpers import (  # pyright: ignore[reportMissingImports]
    ALICE,
    BOB,
    FINANCE,
    OTHER_CUSTOMER_FINANCE,
    Harness,
    RecordingDenials,
    harness,
    policy,
    role,
)
from fastapi import APIRouter, Depends
from neurosphere_api.app import create_app
from neurosphere_api.authz import (
    PERMISSION_MARKER,
    ROLE_GATED_PATHS,
    ROLE_MARKER,
    holds_role,
    require_role,
    route_inventory,
    undeclared_routes,
)
from neurosphere_api.workspaces.router import PREFIX
from neurosphere_core.auth.scope import Role
from neurosphere_core.cloud import Settings
from neurosphere_core.errors import InvalidSchemaError
from neurosphere_core.scope import IdentityScope

PATH = f"{PREFIX}/{{role}}"


def test_workspace_route_is_role_gated_and_claims_no_permission() -> None:
    app = create_app(Settings(env="local"))
    entry = next(e for e in route_inventory(app) if e.path == PATH)
    assert PATH in ROLE_GATED_PATHS
    assert entry.role_gated
    assert entry.permissions == ()  # no longer claims data.read
    assert entry.compliant
    assert undeclared_routes(app) == ()


def test_viewer_naming_only_another_customers_domain_is_denied_and_recorded() -> None:
    denials = RecordingDenials()
    h = harness(
        policy(ALICE, role(Role.VIEWER, OTHER_CUSTOMER_FINANCE)),
        denials=denials,
    )
    response = h.client.get(f"{PREFIX}/viewer", headers=h.auth(ALICE))
    assert response.status_code == 403
    body = response.json()
    assert body["code"] == "forbidden"
    assert body["reason"] == "role_not_held"
    assert len(denials.attempts) == 1
    attempt = denials.attempts[0]
    assert attempt.reason == "role_not_held"
    assert attempt.permission == "role.viewer"
    assert attempt.domain_id is None
    assert attempt.resource_id is None


def test_held_role_is_not_recorded_as_a_denial() -> None:
    denials = RecordingDenials()
    h = harness(policy(ALICE, role(Role.VIEWER, FINANCE)), denials=denials)
    assert h.client.get(f"{PREFIX}/viewer", headers=h.auth(ALICE)).status_code == 200
    assert denials.attempts == []


def test_unknown_persona_is_404_and_not_a_denial() -> None:
    denials = RecordingDenials()
    h = harness(policy(ALICE, role(Role.VIEWER, FINANCE)), denials=denials)
    assert h.client.get(f"{PREFIX}/owner", headers=h.auth(ALICE)).status_code == 404
    assert denials.attempts == []


def test_recorder_failure_on_a_read_still_denies() -> None:
    denials = RecordingDenials(error=RuntimeError("audit down"))
    h = harness(policy(BOB, role(Role.ANALYST, FINANCE)), denials=denials)
    response = h.client.get(f"{PREFIX}/admin", headers=h.auth(BOB))
    assert response.status_code == 403
    assert len(denials.attempts) == 1


async def _derive(h: Harness, who: str) -> IdentityScope:
    claims = await h.validator.authenticate(f"Bearer {h.token(who)}")
    derivation = await h.deriver.derive(claims)
    return derivation.scope


async def test_holds_role_requires_a_domain_of_the_scopes_own_tenancy() -> None:
    h = harness(
        policy(ALICE, role(Role.VIEWER, OTHER_CUSTOMER_FINANCE)),
        policy(BOB, role(Role.VIEWER, FINANCE)),
    )
    now = datetime.fromtimestamp(h.clock.now, UTC)
    foreign = await _derive(h, ALICE)
    own = await _derive(h, BOB)
    assert holds_role(foreign, Role.VIEWER, now) is False
    assert holds_role(own, Role.VIEWER, now) is True
    assert holds_role(own, Role.ANALYST, now) is False


def test_require_role_rejects_unknown_role_names_at_declaration() -> None:
    with pytest.raises(InvalidSchemaError):
        require_role("owner")


def test_role_marker_outside_the_role_gated_paths_is_not_compliant() -> None:
    router = APIRouter()

    @router.get("/elsewhere")
    async def elsewhere(
        scope: IdentityScope = Depends(require_role(Role.VIEWER)),  # noqa: B008
    ) -> dict[str, str]:
        return {}

    app = create_app(Settings(env="local"), extra_routers={"/t": router})
    flagged = {e.path for e in undeclared_routes(app)}
    assert "/t/elsewhere" in flagged


def test_role_gate_dependency_carries_the_role_marker_only() -> None:
    dep = require_role(Role.VIEWER)
    assert getattr(dep, ROLE_MARKER, None) is True
    assert getattr(dep, PERMISSION_MARKER, None) is None
