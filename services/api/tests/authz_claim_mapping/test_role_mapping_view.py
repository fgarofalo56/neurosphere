"""PRP-138 item 5: ``GET /api/v1/admin/identity/role-mapping``, the effective mapping, read only.

Deployment-scoped ``policy.manage`` (the customer control domain); a domain admin gets 403
``customer_scope_required``, a caller without ``policy.manage`` 403 ``permission_missing``. The
claim-mapped admin reads it through the same dependency as a stored admin.
"""

from __future__ import annotations

from typing import Any

import pytest
from authz.authz_helpers import (  # pyright: ignore[reportMissingImports]
    ALICE,
    AUDIENCE,
    BOB,
    CAROL,
    FINANCE,
    OPERATIONS,
    TENANT,
    make_app,
    policy,
    role,
)
from neurosphere_api.admin.identity.role_mapping import role_mapping_view
from neurosphere_api.authz import route_inventory
from neurosphere_core.auth.scope import Role

from .test_me_access import (
    ADMIN_VALUE,
    CONTROL,
    GROUP,
    VIEWER_VALUE,
    MappedHarness,
    mapped_harness,
    the_mapping,
)

PATH = "/api/v1/admin/identity/role-mapping"

EXPECTED_ENTRIES: list[dict[str, Any]] = [
    {
        "id": "ns-admins",
        "claim": "roles",
        "value": ADMIN_VALUE,
        "role": "admin",
        "domain_mode": "all",
        "domain_ids": [],
        "customer_control": True,
    },
    {
        "id": "finance-analysts",
        "claim": "groups",
        "value": GROUP,
        "role": "analyst",
        "domain_mode": "explicit",
        "domain_ids": [FINANCE],
        "customer_control": False,
    },
    {
        "id": "ops-viewers",
        "claim": "roles",
        "value": VIEWER_VALUE,
        "role": "viewer",
        "domain_mode": "explicit",
        "domain_ids": [OPERATIONS],
        "customer_control": False,
    },
]


def _deployment_admin() -> Any:
    return policy(ALICE, role(Role.ADMIN, CONTROL), memberships=(FINANCE, CONTROL))


def _get(h: MappedHarness, headers: dict[str, str]) -> Any:
    return h.client.get(PATH, headers=headers)


def test_active_mapping_is_returned() -> None:
    h = mapped_harness(_deployment_admin(), mapping=the_mapping())
    response = _get(h, h.token(ALICE))
    assert response.status_code == 200, response.text
    assert response.json() == {
        "active": True,
        "tenant_id": TENANT,
        "audience": AUDIENCE,
        "cloud": "commercial",
        "entries": EXPECTED_ENTRIES,
    }


def test_no_mapping_is_inactive_with_the_deployment_cloud() -> None:
    h = mapped_harness(_deployment_admin())
    response = _get(h, h.token(ALICE))
    assert response.status_code == 200, response.text
    assert response.json() == {
        "active": False,
        "tenant_id": None,
        "audience": None,
        "cloud": "commercial",
        "entries": [],
    }


def test_explicit_domains_are_listed_and_all_is_empty() -> None:
    body = role_mapping_view(the_mapping(), "government").model_dump()
    modes = {e["id"]: (e["domain_mode"], e["domain_ids"]) for e in body["entries"]}
    assert modes == {
        "ns-admins": ("all", []),
        "finance-analysts": ("explicit", [FINANCE]),
        "ops-viewers": ("explicit", [OPERATIONS]),
    }
    assert body["cloud"] == "government"


def test_domain_admin_without_the_control_domain_gets_customer_scope_required() -> None:
    h = mapped_harness(policy(BOB, role(Role.ADMIN, FINANCE)), mapping=the_mapping())
    response = _get(h, h.token(BOB))
    assert response.status_code == 403, response.text
    assert response.json()["reason"] == "customer_scope_required"
    assert ADMIN_VALUE not in response.text


def test_caller_without_policy_manage_gets_403() -> None:
    h = mapped_harness(policy(CAROL, role(Role.VIEWER, FINANCE)), mapping=the_mapping())
    response = _get(h, h.token(CAROL))
    assert response.status_code == 403, response.text
    assert response.json()["reason"] == "permission_missing"
    assert "policy.manage" in response.json()["detail"]


def test_mapped_group_analyst_cannot_read_it() -> None:
    h = mapped_harness(mapping=the_mapping())
    response = _get(h, h.token(BOB, groups=[GROUP]))
    assert response.status_code == 403
    assert response.json()["reason"] == "permission_missing"


def test_the_mapped_admin_can_read_it() -> None:
    """No stored policy at all: the admin role comes only from the Entra app role."""
    h = mapped_harness(mapping=the_mapping())
    response = _get(h, h.token(BOB, roles=(ADMIN_VALUE,)))
    assert response.status_code == 200, response.text
    assert response.json()["active"] is True


def test_unauthenticated_caller_gets_401() -> None:
    h = mapped_harness(mapping=the_mapping())
    assert h.client.get(PATH).status_code == 401


def test_configured_mapping_that_is_not_reachable_is_503_not_inactive() -> None:
    """Counters say a mapping is configured but the parsed mapping is not installed: fail closed."""
    h = mapped_harness(_deployment_admin(), mapping=the_mapping(), install="stats")
    response = _get(h, h.token(ALICE))
    assert response.status_code == 503, response.text
    assert response.json()["reason"] == "role_mapping_unavailable"


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_no_write_method_is_served(method: str) -> None:
    h = mapped_harness(_deployment_admin(), mapping=the_mapping())
    assert h.client.request(method, PATH, headers=h.token(ALICE)).status_code == 405


def test_the_route_is_get_only_and_needs_policy_manage() -> None:
    app = make_app(routers={})
    entries = [e for e in route_inventory(app) if e.path == PATH]
    assert [(e.methods, e.permissions) for e in entries] == [(("GET",), ("policy.manage",))]
