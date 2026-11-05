"""Kill switch needs CUSTOMER-level ``config.manage`` (PRP-17 audit close-out, Lane B).

``PUT /api/v1/actions/emergency-disable`` acts on every domain of the customer, so a
``config.manage`` holder in one domain (DAVE) must not flip it; only ``config.manage`` on the
customer's reserved control domain (FRANK) does. Disable and re-enable are checked identically
and both are audited (before + after).
"""

from __future__ import annotations

import asyncio
from typing import Any

import authz.authz_helpers as helpers  # pyright: ignore[reportMissingImports]
import pytest
from action_plane_harness import (  # pyright: ignore[reportMissingImports]
    ALICE,
    CAROL,
    CONTROL,
    CUSTOMER,
    DAVE,
    FRANK,
    GRACE,
    make_api,
    problem,
)
from neurosphere_api.actions import (
    CUSTOMER_SCOPE_REQUIRED,
    customer_control_domain,
    require_customer_control,
)
from neurosphere_api.authz import PERMISSION_MARKER, route_inventory
from neurosphere_core.auth.scope import Permission, Role

DISABLE: dict[str, Any] = {"disabled": True, "reason": "incident_inc_42"}
ENABLE: dict[str, Any] = {"disabled": False, "reason": None}
CHAIN = f"{CUSTOMER}.execution-control"


def _records(api: Any) -> list[Any]:
    return asyncio.run(api.audit.read_range(CHAIN, start=0))


def test_control_domain_is_bound_to_cloud_and_customer() -> None:
    assert CONTROL == "commercial:contoso:neurosphere:domain:customer-control"
    assert customer_control_domain("government", CUSTOMER) != CONTROL
    assert customer_control_domain("commercial", "fabrikam") != CONTROL


def test_domain_scoped_config_manage_cannot_flip_the_kill_switch() -> None:
    api = make_api()
    for body in (DISABLE, ENABLE):
        denied = api.call("PUT", DAVE, "/emergency-disable", json=body)
        assert denied.status_code == 403, denied.text
        payload = problem(denied)
        assert payload["code"] == "forbidden"
        assert payload["reason"] == CUSTOMER_SCOPE_REQUIRED
    assert api.call("GET", CAROL, "/emergency-disable").json()["disabled"] is False
    assert _records(api) == []  # nothing changed, nothing audited as a change


def test_customer_level_holder_disables_and_re_enables_with_audit() -> None:
    api = make_api()
    off = api.call("PUT", FRANK, "/emergency-disable", json=DISABLE)
    assert off.status_code == 200, off.text
    assert off.json()["disabled"] is True
    # Re-enabling is the dangerous direction; it is checked at the same customer level.
    assert api.call("PUT", DAVE, "/emergency-disable", json=ENABLE).status_code == 403
    assert api.call("GET", CAROL, "/emergency-disable").json()["disabled"] is True
    on = api.call("PUT", FRANK, "/emergency-disable", json=ENABLE)
    assert on.status_code == 200, on.text
    assert on.json()["disabled"] is False
    records = _records(api)
    assert [r.kind for r in records] == ["before", "after", "before", "after"]
    operations = [r.operation for r in records]
    assert operations == [
        "action.emergency_disable",
        "action.emergency_disable",
        "action.emergency_enable",
        "action.emergency_enable",
    ]


@pytest.mark.parametrize("who", [CAROL, ALICE])
def test_holders_without_config_manage_are_denied_first(who: str) -> None:
    # CAROL is a Viewer, ALICE a Domain Steward: neither holds config.manage anywhere.
    api = make_api()
    denied = api.call("PUT", who, "/emergency-disable", json=DISABLE)
    assert denied.status_code == 403
    assert problem(denied)["reason"] == "permission_missing"


def test_other_customer_control_domain_never_authorizes() -> None:
    # GRACE's policy names fabrikam's control domain; derivation clips it, so she is only a
    # FINANCE admin in contoso and is refused like DAVE.
    api = make_api()
    denied = api.call("PUT", GRACE, "/emergency-disable", json=DISABLE)
    assert denied.status_code == 403
    assert problem(denied)["reason"] == CUSTOMER_SCOPE_REQUIRED


def test_policy_store_outage_is_503_not_allow() -> None:
    api = make_api()
    api.h.repo.fail_with(RuntimeError("cosmos down"))
    down = api.call("PUT", FRANK, "/emergency-disable", json=DISABLE)
    assert down.status_code == 503
    assert problem(down)["code"] == "dependency_transient"
    api.h.repo.fail_with(None)
    assert api.call("GET", CAROL, "/emergency-disable").json()["disabled"] is False


def test_expired_control_role_is_denied() -> None:
    api = make_api()
    api.h.repo.put_principal(
        helpers.policy(
            FRANK,
            helpers.role(Role.ADMIN, CONTROL, expires_in=-60),
            helpers.role(Role.ADMIN, helpers.FINANCE),
            memberships=(helpers.FINANCE, CONTROL),
        )
    )
    api.h.deriver.invalidate_all()
    denied = api.call("PUT", FRANK, "/emergency-disable", json=DISABLE)
    assert denied.status_code == 403
    assert problem(denied)["reason"] == CUSTOMER_SCOPE_REQUIRED


def test_customer_scope_denial_is_recorded() -> None:
    denials = helpers.RecordingDenials()
    api = make_api(denials=denials)
    assert api.call("PUT", DAVE, "/emergency-disable", json=DISABLE).status_code == 403
    [attempt] = denials.attempts
    assert attempt.reason == CUSTOMER_SCOPE_REQUIRED
    assert attempt.permission == "config.manage"
    assert attempt.method == "PUT" and attempt.domain_id == CONTROL


def test_denial_audit_failure_fails_closed() -> None:
    denials = helpers.RecordingDenials(error=RuntimeError("audit store down"))
    api = make_api(denials=denials)
    down = api.call("PUT", DAVE, "/emergency-disable", json=DISABLE)
    assert down.status_code == 503
    assert problem(down)["reason"] == "audit_write_failed"
    assert api.call("GET", CAROL, "/emergency-disable").json()["disabled"] is False


def test_dependency_still_declares_config_manage_for_the_route_inventory() -> None:
    dependency = require_customer_control(Permission.CONFIG_MANAGE)
    assert getattr(dependency, PERMISSION_MARKER, None) is None  # declared by the inner require
    api = make_api()
    entries = {(e.path, e.methods): e.permissions for e in route_inventory(api.h.app)}
    assert entries[("/api/v1/actions/emergency-disable", ("PUT",))] == ("config.manage",)
    assert entries[("/api/v1/actions/emergency-disable", ("GET",))] == ("data.read",)
