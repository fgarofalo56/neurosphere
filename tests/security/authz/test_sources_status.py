"""ABAC negative suite for the source status routes (PRP-139 item 3).

The suite world serves the real router table, so both routes are mounted; this module installs the
source status plane on each deployment.

==================================  ==========================================================
Dimension                           Expected result
==================================  ==========================================================
viewer of one domain                200 on ``/api/v1/sources/status`` (four sources, no reason)
member of a domain, no role         403 ``permission_missing`` on both, denial recorded
expired role                        403 on both, denial recorded
ordinary domain admin               200 on the user route, 403 ``customer_scope_required`` on
                                    the admin route, denial recorded
viewer / analyst / auditor          403 on the admin route (holds no ``config.manage``)
customer-level config.manage        200 on the admin route: reasons and per-connector counts
expired control-domain admin        403 on the admin route
other customer                      sees only its own statuses (the customer comes from the scope)
==================================  ==========================================================
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any

import pytest
from neurosphere_api.sources_status import SourceStatusPlane, configure_source_status
from neurosphere_core.auth.scope import (
    PolicyRoleAssignment,
    PrincipalPolicy,
    Role,
    principal_document_id,
)
from neurosphere_core.sources_status import (
    ConfiguredConnector,
    ConnectorRunStatus,
    InMemorySourceStatusRepository,
)

from .test_admin_connectors import (  # pyright: ignore[reportPrivateUsage]
    ADMIN,
    CONTROL_ADMIN_OID,
    EXPIRED_CONTROL_OID,
    _bearer,
    _seed,
)
from .test_admin_identity import pid_of
from .world import Deployment, Who, World, at, domain_id, run

USER = "/api/v1/sources/status"
ADMIN_PATH = "/api/v1/admin/sources/status"
NO_ROLE_OID = "a1b2c3d4-0000-4000-8000-00000000f139"
EXPIRED_VIEWER_OID = "a1b2c3d4-0000-4000-8000-00000000f140"
VIEWER = Who("contoso", "finance", Role.VIEWER)
DENIED_ADMIN_ROLES = (Role.VIEWER, Role.ANALYST, Role.DOMAIN_STEWARD, Role.SECURITY_AUDITOR)
NOW = datetime(2026, 11, 21, 10, 0, tzinfo=UTC)
FOUR = ["foundry", "apim_gateway", "billing", "azure_monitor_telemetry"]


def _plane(repo: InMemorySourceStatusRepository) -> SourceStatusPlane:
    async def configs(customer_id: str) -> list[ConfiguredConnector]:
        return [ConfiguredConnector("foundry_discovery", True)]

    return SourceStatusPlane(statuses=repo, configs=configs)


def _seed_member(dep: Deployment, object_id: str, roles: tuple[PolicyRoleAssignment, ...]) -> None:
    fin = domain_id(dep.customer, "finance")
    principal = pid_of(object_id, dep.customer)
    dep.repo.put_principal(
        PrincipalPolicy(
            id=principal_document_id(principal),
            customer_id=dep.customer,
            principal_id=principal,
            domain_memberships=(fin,),
            role_assignments=roles,
        )
    )


@pytest.fixture
def sworld(world: World) -> tuple[World, dict[str, InMemorySourceStatusRepository]]:
    repos: dict[str, InMemorySourceStatusRepository] = {}
    for name, dep in world.deployments.items():
        repos[name] = InMemorySourceStatusRepository()
        configure_source_status(dep.app, _plane(repos[name]))
        _seed(dep, CONTROL_ADMIN_OID, expires_in=7 * 24 * 3600)
        _seed(dep, EXPIRED_CONTROL_OID, expires_in=10)
        _seed_member(dep, NO_ROLE_OID, ())
        fin = domain_id(dep.customer, "finance")
        viewer = PolicyRoleAssignment(
            assignment_id="ra-expiring", role=Role.VIEWER, domain_ids=(fin,), expires_at=at(10)
        )
        _seed_member(dep, EXPIRED_VIEWER_OID, (viewer,))
    return world, repos


def _audit_count(dep: Deployment) -> int:
    return sum(1 for (_c, d) in dep.audit_store._docs if d != "tail")  # pyright: ignore[reportPrivateUsage]


def _assert_denied(
    dep: Deployment, path: str, headers: dict[str, str], *, reason: str | None = None
) -> None:
    attempts, audited = len(dep.recorder.attempts), _audit_count(dep)
    response = dep.client.get(path, headers=headers)
    assert response.status_code == 403, f"{path}: {response.status_code} {response.text}"
    if reason is not None:
        assert response.json()["reason"] == reason, response.text
    assert len(dep.recorder.attempts) == attempts + 1, "no denial was recorded"
    assert _audit_count(dep) == audited + 1, "the denial record was not persisted"


def _record(repo: InMemorySourceStatusRepository, **over: Any) -> None:
    body: dict[str, Any] = {
        "kind": "foundry_discovery",
        "state": "failed",
        "reason": "source_access_denied",
        "last_attempt_at": NOW,
        "last_success_at": NOW,
        "counts": {"projects_failed": 1},
    }
    body.update(over)
    run(repo.record("contoso", ConnectorRunStatus.model_validate(body)))


def test_a_viewer_of_one_domain_reads_the_summary(
    sworld: tuple[World, dict[str, InMemorySourceStatusRepository]],
) -> None:
    world, repos = sworld
    _record(repos["contoso"])
    dep = world["contoso"]
    response = dep.client.get(USER, headers=dep.bearer(VIEWER))
    assert response.status_code == 200, response.text
    body = response.json()
    assert [s["source"] for s in body["sources"]] == FOUR
    assert body["sources"][0] == {
        "source": "foundry",
        "state": "failing",
        "last_success_at": "2026-11-21T10:00:00Z",
        "available": True,
    }
    assert body["sources"][3]["state"] == "not_connected"
    assert body["sources"][3]["available"] is False
    text = response.text
    assert "reason" not in text and "counts" not in text and "connectors" not in text


@pytest.mark.parametrize("path", [USER, ADMIN_PATH])
def test_a_member_with_no_role_is_denied_and_recorded(
    sworld: tuple[World, dict[str, InMemorySourceStatusRepository]], path: str
) -> None:
    dep = sworld[0]["contoso"]
    _assert_denied(dep, path, _bearer(dep, NO_ROLE_OID), reason="permission_missing")


@pytest.mark.parametrize("path", [USER, ADMIN_PATH])
def test_an_expired_role_is_denied_and_recorded(
    sworld: tuple[World, dict[str, InMemorySourceStatusRepository]], path: str
) -> None:
    world, _ = sworld
    dep = world["contoso"]
    assert dep.client.get(USER, headers=_bearer(dep, EXPIRED_VIEWER_OID)).status_code == 200
    world.clock.advance(11)
    _assert_denied(dep, path, _bearer(dep, EXPIRED_VIEWER_OID))


def test_no_token_is_401(sworld: tuple[World, dict[str, InMemorySourceStatusRepository]]) -> None:
    dep = sworld[0]["contoso"]
    assert dep.client.get(USER).status_code == 401
    assert dep.client.get(ADMIN_PATH).status_code == 401


def test_a_domain_admin_reads_the_user_route_but_not_the_admin_route(
    sworld: tuple[World, dict[str, InMemorySourceStatusRepository]],
) -> None:
    dep = sworld[0]["contoso"]
    assert dep.client.get(USER, headers=dep.bearer(ADMIN)).status_code == 200
    _assert_denied(dep, ADMIN_PATH, dep.bearer(ADMIN), reason="customer_scope_required")


@pytest.mark.parametrize("role", DENIED_ADMIN_ROLES, ids=lambda r: r.value)
def test_roles_without_config_manage_are_denied_on_the_admin_route(
    sworld: tuple[World, dict[str, InMemorySourceStatusRepository]], role: Role
) -> None:
    dep = sworld[0]["contoso"]
    _assert_denied(dep, ADMIN_PATH, dep.bearer(Who("contoso", "finance", role)))


def test_an_expired_control_admin_is_denied(
    sworld: tuple[World, dict[str, InMemorySourceStatusRepository]],
) -> None:
    world, _ = sworld
    dep = world["contoso"]
    world.clock.advance(11)
    _assert_denied(dep, ADMIN_PATH, _bearer(dep, EXPIRED_CONTROL_OID))


def test_a_customer_level_admin_reads_reasons_and_counts(
    sworld: tuple[World, dict[str, InMemorySourceStatusRepository]],
) -> None:
    world, repos = sworld
    _record(repos["contoso"])
    dep = world["contoso"]
    response = dep.client.get(ADMIN_PATH, headers=_bearer(dep, CONTROL_ADMIN_OID))
    assert response.status_code == 200, response.text
    body = response.json()
    assert [s["source"] for s in body["sources"]] == FOUR
    assert body["sources"][0]["reason"] == "source_access_denied"
    assert body["sources"][3]["reason"] == "not_available_in_release"
    assert [c["kind"] for c in body["connectors"]] == [
        "foundry_discovery",
        "gateway_poll",
        "billing_export",
    ]
    assert body["connectors"][0] == {
        "kind": "foundry_discovery",
        "state": "failed",
        "reason": "source_access_denied",
        "last_success_at": "2026-11-21T10:00:00Z",
        "last_attempt_at": "2026-11-21T10:00:00Z",
        "counts": {"projects_failed": 1},
    }


def test_the_customer_comes_from_the_scope_not_the_request(
    sworld: tuple[World, dict[str, InMemorySourceStatusRepository]],
) -> None:
    world, repos = sworld
    _record(repos["contoso"])
    fab = world["fabrikam"]
    viewer = Who("fabrikam", "finance", Role.VIEWER)
    response = fab.client.get(USER, headers=fab.bearer(viewer), params={"customer_id": "contoso"})
    assert response.status_code == 200
    assert response.json()["sources"][0]["state"] == "not_connected"


def test_neither_response_carries_a_guid_or_a_url(
    sworld: tuple[World, dict[str, InMemorySourceStatusRepository]],
) -> None:
    world, repos = sworld
    _record(repos["contoso"])
    dep = world["contoso"]
    texts = [
        dep.client.get(USER, headers=dep.bearer(VIEWER)).text,
        dep.client.get(ADMIN_PATH, headers=_bearer(dep, CONTROL_ADMIN_OID)).text,
    ]
    for text in texts:
        json.loads(text)
        assert not re.search(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-", text)
        assert "http" not in text and "://" not in text


def test_an_unconfigured_plane_is_503_after_authorization(
    sworld: tuple[World, dict[str, InMemorySourceStatusRepository]],
) -> None:
    world, _ = sworld
    dep = world["contoso"]
    configure_source_status(dep.app, None)
    assert dep.client.get(USER, headers=dep.bearer(VIEWER)).status_code == 503
    _assert_denied(dep, USER, _bearer(dep, NO_ROLE_OID))
