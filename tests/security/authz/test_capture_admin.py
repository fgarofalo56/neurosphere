"""ABAC negative suite for the read-only capture admin routes (PRP-103 item 5).

The suite world serves the real router table, so ``/api/v1/admin/interactions/...`` is mounted;
this module installs a capture policy store on each deployment's ``app.state`` the way the
``interactions`` builder does.

=====================================  ===========================================================
Dimension                              Expected result
=====================================  ===========================================================
no config.manage (viewer, analyst,     403 on the list and status (denial recorded); the detail
steward, auditor)                      route is 403 too (config.manage held nowhere)
config.manage in another domain        403 ``target_out_of_scope`` naming that domain (recorded);
                                       the detail of a policy there is 404 like an unknown id
domain admin, every domain             403 ``customer_scope_required`` (recorded)
customer-level config.manage           200 with this customer's policies only
any write method                       405 or 404, the store unchanged
=====================================  ===========================================================
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from neurosphere_core.auth.scope import Role
from neurosphere_core.classification import DEFAULT_SET_VERSION
from neurosphere_core.interactions import InMemoryCapturePolicyStore, parse_capture_policy

from .test_admin_connectors import (  # pyright: ignore[reportPrivateUsage]
    CONTROL_ADMIN_OID,
    _bearer,
    _seed,
)
from .world import Deployment, Who, World, domain_id, run

BASE = "/api/v1/admin/interactions"
POLICIES = f"{BASE}/capture-policies"
STATUS = f"{BASE}/capture-status"
DETAIL = f"{POLICIES}/fin-capture"
NO_CONFIG_MANAGE = (Role.VIEWER, Role.ANALYST, Role.DOMAIN_STEWARD, Role.SECURITY_AUDITOR)
FIN_ADMIN = Who("contoso", "finance", Role.ADMIN)
OPS_ADMIN = Who("contoso", "operations", Role.ADMIN)
FIN = domain_id("contoso", "finance")


def _policy(customer: str, policy_id: str, domain: str) -> dict[str, Any]:
    # Approval ids are generated per run (no GUID-shaped literal in the source).
    return {
        "schema_version": "1.2.0",
        "capture_policy_id": policy_id,
        "version": 1,
        "previous_version": None,
        "display_name": "Synthetic capture",
        "cloud": "commercial",
        "customer_id": customer,
        "domain_id": domain_id(customer, domain),
        "source_ids": ["src-synthetic"],
        "parts": ["prompt"],
        "detector_set_version": DEFAULT_SET_VERSION,
        "sampling": {"rate": 0.5, "max_per_minute": 60},
        "retention_class": "interaction_default",
        "state": "active",
        "approved_intent_id": str(uuid.uuid4()),
        "approved_audit_id": str(uuid.uuid4()),
        "effective_from": "2026-11-21T08:00:00Z",
    }


@pytest.fixture
def cworld(world: World) -> World:
    for dep in world.deployments.values():
        store = InMemoryCapturePolicyStore()
        for customer in ("contoso", "fabrikam"):
            for name, domain in (("fin-capture", "finance"), ("ops-capture", "operations")):
                run(store.create(parse_capture_policy(_policy(customer, name, domain))))
        state = dep.app.state
        state.interaction_capture = None
        state.interaction_capture_stats = None
        state.interaction_capture_policy_store = store
        state.interaction_capture_off_reason = "setting_off"
        _seed(dep, CONTROL_ADMIN_OID, expires_in=7 * 24 * 3600)
    return world


def _audit_count(dep: Deployment) -> int:
    return sum(1 for (_c, d) in dep.audit_store._docs if d != "tail")  # pyright: ignore[reportPrivateUsage]


def _assert_refused(
    dep: Deployment,
    path: str,
    headers: dict[str, str],
    *,
    status: int = 403,
    reason: str | None = None,
    params: dict[str, str] | None = None,
) -> None:
    attempts, audited = len(dep.recorder.attempts), _audit_count(dep)
    response = dep.client.get(path, headers=headers, params=params)
    assert response.status_code == status, f"{path}: {response.status_code} {response.text}"
    if reason is not None:
        assert response.json()["reason"] == reason, response.text
    # The problem body names the request path (``instance``) but never a policy's data.
    assert '"policy_id"' not in response.text
    assert '"source_ids"' not in response.text
    assert len(dep.recorder.attempts) == attempts + 1, "no denial was recorded"
    assert _audit_count(dep) == audited + 1, "the denial record was not persisted"


@pytest.mark.parametrize("role", NO_CONFIG_MANAGE, ids=lambda r: r.value)
def test_no_config_manage_is_403_everywhere(cworld: World, role: Role) -> None:
    dep = cworld["contoso"]
    headers = dep.bearer(Who("contoso", "finance", role))
    _assert_refused(dep, POLICIES, headers, params={"domain_id": FIN})
    _assert_refused(dep, POLICIES, headers)
    _assert_refused(dep, STATUS, headers, params={"domain_id": FIN})
    _assert_refused(dep, DETAIL, headers)


def test_config_manage_in_another_domain_is_403(cworld: World) -> None:
    dep = cworld["contoso"]
    headers = dep.bearer(OPS_ADMIN)
    for path in (POLICIES, STATUS):
        _assert_refused(dep, path, headers, reason="target_out_of_scope", params={"domain_id": FIN})
    assert dep.recorder.attempts[-1].domain_id == FIN
    # The detail of a policy in a domain the caller does not administer is 404, as unknown.
    _assert_refused(dep, DETAIL, headers, status=404, reason="capture_policy_not_found")


def test_a_domain_admin_cannot_list_every_domain(cworld: World) -> None:
    dep = cworld["contoso"]
    headers = dep.bearer(FIN_ADMIN)
    for path in (POLICIES, STATUS):
        _assert_refused(dep, path, headers, reason="customer_scope_required")
    # Its own domain is fine.
    response = dep.client.get(POLICIES, headers=headers, params={"domain_id": FIN})
    assert response.status_code == 200, response.text
    assert [p["policy_id"] for p in response.json()["items"]] == ["fin-capture"]


def test_customer_control_sees_its_own_customer_only(cworld: World) -> None:
    dep = cworld["contoso"]
    headers = _bearer(dep, CONTROL_ADMIN_OID)
    response = dep.client.get(POLICIES, headers=headers)
    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert [p["policy_id"] for p in items] == ["fin-capture", "ops-capture"]
    assert all(p["domain_id"].startswith("commercial:contoso:") for p in items)
    other = dep.client.get(
        POLICIES, headers=headers, params={"domain_id": domain_id("fabrikam", "finance")}
    )
    assert other.status_code == 200, other.text
    assert other.json()["items"] == []
    status = dep.client.get(STATUS, headers=headers)
    assert status.status_code == 200, status.text
    assert status.json()["policies"]["total"] == 2


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_no_write_method_exists(cworld: World, method: str) -> None:
    dep = cworld["contoso"]
    headers = _bearer(dep, CONTROL_ADMIN_OID)
    store = dep.app.state.interaction_capture_policy_store
    before = run(store.list(limit=100))
    for path in (POLICIES, DETAIL, STATUS, f"{POLICIES}/new-capture"):
        response = dep.client.request(
            method, path, headers=headers, json=_policy("contoso", "new-capture", "finance")
        )
        assert response.status_code in (404, 405), f"{method} {path}: {response.status_code}"
    assert run(store.list(limit=100)) == before
