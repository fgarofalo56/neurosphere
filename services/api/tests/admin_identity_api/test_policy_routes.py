"""PRP-39 item 3: principal reads and audited policy writes under ``/api/v1/admin/identity``."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import quote

import pytest
from authz.authz_helpers import T0, role  # pyright: ignore[reportMissingImports]
from fastapi.testclient import TestClient
from identity_harness import (  # pyright: ignore[reportMissingImports]
    AGENT,
    BASE,
    CONTROL,
    CUSTOMER,
    CUSTOMER_ADMIN,
    DOMAIN_ADMIN,
    FINANCE,
    HR,
    HR_AGENT,
    HR_ONLY,
    OPERATIONS,
    TARGET,
    IdentityWorld,
    configure_env,
    pid,
)
from neurosphere_core.auth.scope import (
    PrincipalPolicy,
    Role,
    principal_document_id,
)
from neurosphere_core.errors import DependencyTransientError

STEWARD = "5e6f7a8b-9c0d-4e1f-8a3b-4c5d6e7f8091"
OBJECT_IDS = (DOMAIN_ADMIN, CUSTOMER_ADMIN, TARGET, HR_ONLY, STEWARD)


@pytest.fixture(autouse=True)
def _auth(monkeypatch: pytest.MonkeyPatch) -> None:
    configure_env(monkeypatch)


@pytest.fixture
def world() -> IdentityWorld:
    w = IdentityWorld.build()
    steward = pid(STEWARD)
    w.policies.put_principal(
        PrincipalPolicy(
            id=principal_document_id(steward),
            customer_id=CUSTOMER,
            principal_id=steward,
            domain_memberships=(FINANCE,),
            role_assignments=(role(Role.DOMAIN_STEWARD, FINANCE),),
        )
    )
    return w


def _ts(offset: float) -> str:
    return (datetime.fromtimestamp(T0, UTC) + timedelta(seconds=offset)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _role_body(target: str, assignment_id: str, role_name: str, *domains: str, **extra: Any):
    body: dict[str, Any] = {
        "schema_version": "1.0.0",
        "op": "assign",
        "principal_id": pid(target),
        "assignment_id": assignment_id,
        "role": role_name,
        "domain_ids": list(domains),
        "reason": "access_request",
    }
    body.update(extra)
    return body


def _grant_body(target: str, grant_id: str, resource_id: str, **extra: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "schema_version": "1.0.0",
        "principal_id": pid(target),
        "grant_id": grant_id,
        "resource_id": resource_id,
        "permissions": ["read"],
        "expires_at": _ts(3600),
        "reason": "incident_review",
    }
    body.update(extra)
    return body


def _etag(client: TestClient, world: IdentityWorld, actor: str, target: str) -> str:
    response = client.get(f"{BASE}/principals/{pid(target)}", headers=world.auth(actor))
    assert response.status_code == 200, response.text
    return response.headers["ETag"]


def _no_raw_ids(text: str) -> None:
    for object_id in OBJECT_IDS:
        assert object_id not in text


def _ops(records: list[dict[str, Any]]) -> list[tuple[str, str]]:
    return [(r["kind"], r["operation"]) for r in records]


# ------------------------------------------------------------------ happy path


def test_assign_role_changes_policy_head_next_scope_and_audits_the_domain_chain(
    world: IdentityWorld,
) -> None:
    head_before = world.head()
    with world.composed.client() as client:
        before = client.get("/api/v1/me/domains", headers=world.auth(TARGET))
        assert OPERATIONS not in {d["domain_id"] for d in before.json()["items"]}
        etag = _etag(client, world, CUSTOMER_ADMIN, TARGET)
        body = _role_body(TARGET, "ra-ops-viewer", "viewer", OPERATIONS, expires_at=_ts(7200))
        response = client.put(
            f"{BASE}/principals/{pid(TARGET)}/role-assignments/ra-ops-viewer",
            json=body,
            headers=world.auth(CUSTOMER_ADMIN, **{"If-Match": etag}),
        )
        assert response.status_code == 200, response.text
        assert response.headers["ETag"] != etag
        summary = response.json()
        assert any(a["assignment_id"] == "ra-ops-viewer" for a in summary["assignments"])
        after = client.get("/api/v1/me/domains", headers=world.auth(TARGET))
    stored = world.stored(TARGET)
    assert stored is not None
    assert any(a.assignment_id == "ra-ops-viewer" for a in stored.role_assignments)
    assert world.head() != head_before
    assert summary["policy_version"] == world.head()
    # The target's next request derives the new scope (cache keyed by the head version).
    assert OPERATIONS in {d["domain_id"] for d in after.json()["items"]}
    assert _ops(world.chain(f"{CUSTOMER}.operations")) == [
        ("before", "policy.role_assign"),
        ("after", "policy.role_assign"),
    ]
    _no_raw_ids(response.text)
    _no_raw_ids(repr(world.all_records()))


def test_remove_role_assignment_is_audited(world: IdentityWorld) -> None:
    with world.composed.client() as client:
        etag = _etag(client, world, DOMAIN_ADMIN, TARGET)
        response = client.delete(
            f"{BASE}/principals/{pid(TARGET)}/role-assignments/ra-analyst-1",
            params={"reason": "left_team"},
            headers=world.auth(DOMAIN_ADMIN, **{"If-Match": etag}),
        )
    assert response.status_code == 200, response.text
    stored = world.stored(TARGET)
    assert stored is not None and stored.role_assignments == ()
    assert _ops(world.chain(f"{CUSTOMER}.finance"))[-2:] == [
        ("before", "policy.role_remove"),
        ("after", "policy.role_remove"),
    ]


def test_membership_remove_and_add_back(world: IdentityWorld) -> None:
    path = f"{BASE}/principals/{pid(TARGET)}/domain-memberships/{FINANCE}"
    with world.composed.client() as client:
        etag = _etag(client, world, DOMAIN_ADMIN, TARGET)
        removed = client.delete(path, headers=world.auth(DOMAIN_ADMIN, **{"If-Match": etag}))
        assert removed.status_code == 200, removed.text
        stored = world.stored(TARGET)
        assert stored is not None and FINANCE not in stored.domain_memberships
        body = {
            "schema_version": "1.0.0",
            "op": "add",
            "principal_id": pid(TARGET),
            "domain_id": FINANCE,
            "reason": "rejoined",
        }
        added = client.put(
            path,
            json=body,
            headers=world.auth(DOMAIN_ADMIN, **{"If-Match": removed.headers["ETag"]}),
        )
    assert added.status_code == 200, added.text
    stored = world.stored(TARGET)
    assert stored is not None and FINANCE in stored.domain_memberships
    ops = _ops(world.chain(f"{CUSTOMER}.finance"))
    assert ("after", "policy.membership_remove") in ops and (
        "after",
        "policy.membership_add",
    ) in ops


def test_grant_needs_policy_manage_on_the_owning_domain(world: IdentityWorld) -> None:
    with world.composed.client() as client:
        etag = _etag(client, world, DOMAIN_ADMIN, TARGET)
        ok = client.put(
            f"{BASE}/principals/{pid(TARGET)}/grants/g-agent",
            json=_grant_body(TARGET, "g-agent", AGENT),
            headers=world.auth(DOMAIN_ADMIN, **{"If-Match": etag}),
        )
        assert ok.status_code == 200, ok.text
        assert [g["grant_id"] for g in ok.json()["grants"]] == ["g-agent"]
        hr = client.put(
            f"{BASE}/principals/{pid(TARGET)}/grants/g-hr",
            json=_grant_body(TARGET, "g-hr", HR_AGENT),
            headers=world.auth(DOMAIN_ADMIN, **{"If-Match": ok.headers["ETag"]}),
        )
        unknown = client.put(
            f"{BASE}/principals/{pid(TARGET)}/grants/g-x",
            json=_grant_body(TARGET, "g-x", "commercial:contoso:foundry:agent:unknown"),
            headers=world.auth(DOMAIN_ADMIN, **{"If-Match": ok.headers["ETag"]}),
        )
        removed = client.delete(
            f"{BASE}/principals/{pid(TARGET)}/grants/g-agent",
            headers=world.auth(DOMAIN_ADMIN, **{"If-Match": ok.headers["ETag"]}),
        )
    assert hr.status_code == 403 and hr.json()["reason"] == "target_out_of_scope"
    assert unknown.status_code == 403 and unknown.json()["reason"] == "target_out_of_scope"
    assert removed.status_code == 200, removed.text
    ops = _ops(world.chain(f"{CUSTOMER}.finance"))
    assert ("after", "policy.grant_put") in ops and ("after", "policy.grant_remove") in ops


def test_grant_write_alone_is_not_enough_for_resource_grants(world: IdentityWorld) -> None:
    with world.composed.client() as client:
        response = client.put(
            f"{BASE}/principals/{pid(TARGET)}/grants/g-agent",
            json=_grant_body(TARGET, "g-agent", AGENT),
            headers=world.auth(STEWARD),
        )
    assert response.status_code == 403
    assert response.json()["reason"] == "permission_missing"


def test_grant_without_expiry_is_rejected(world: IdentityWorld) -> None:
    body = _grant_body(TARGET, "g-agent", AGENT)
    del body["expires_at"]
    with world.composed.client() as client:
        response = client.put(
            f"{BASE}/principals/{pid(TARGET)}/grants/g-agent",
            json=body,
            headers=world.auth(DOMAIN_ADMIN),
        )
    assert response.status_code == 422


# ------------------------------------------------------------------ refusals


def test_change_naming_an_unmanaged_domain_is_403_audited_and_writes_nothing(
    world: IdentityWorld,
) -> None:
    before = world.stored(TARGET)
    head = world.head()
    with world.composed.client() as client:
        etag = _etag(client, world, DOMAIN_ADMIN, TARGET)
        response = client.put(
            f"{BASE}/principals/{pid(TARGET)}/role-assignments/ra-x",
            json=_role_body(TARGET, "ra-x", "viewer", FINANCE, OPERATIONS),
            headers=world.auth(DOMAIN_ADMIN, **{"If-Match": etag}),
        )
    assert response.status_code == 403
    assert response.json()["reason"] == "target_out_of_scope"
    assert world.stored(TARGET) == before and world.head() == head
    denials = [r for r in world.all_records() if r["kind"] == "denied"]
    assert [d["denial"]["reason"] for d in denials] == ["target_out_of_scope"]
    assert world.chain(f"{CUSTOMER}.operations") == []


def test_self_modification_is_forbidden(world: IdentityWorld) -> None:
    with world.composed.client() as client:
        etag = _etag(client, world, CUSTOMER_ADMIN, CUSTOMER_ADMIN)
        response = client.put(
            f"{BASE}/principals/{pid(CUSTOMER_ADMIN)}/role-assignments/ra-mine",
            json=_role_body(CUSTOMER_ADMIN, "ra-mine", "viewer", FINANCE),
            headers=world.auth(CUSTOMER_ADMIN, **{"If-Match": etag}),
        )
    assert response.status_code == 403
    assert response.json()["reason"] == "self_modification_forbidden"
    assert any(
        r["kind"] == "denied" and r["denial"]["reason"] == "self_modification_forbidden"
        for r in world.all_records()
    )


def test_privileged_roles_need_customer_wide_authority_and_an_expiry(world: IdentityWorld) -> None:
    url = f"{BASE}/principals/{pid(TARGET)}/role-assignments/ra-admin"
    with world.composed.client() as client:
        etag = _etag(client, world, DOMAIN_ADMIN, TARGET)
        domain_only = client.put(
            url,
            json=_role_body(TARGET, "ra-admin", "admin", FINANCE, expires_at=_ts(3600)),
            headers=world.auth(DOMAIN_ADMIN, **{"If-Match": etag}),
        )
        auditor = client.put(
            url,
            json=_role_body(TARGET, "ra-admin", "security_auditor", FINANCE, expires_at=_ts(3600)),
            headers=world.auth(DOMAIN_ADMIN, **{"If-Match": etag}),
        )
        no_expiry = client.put(
            url,
            json=_role_body(TARGET, "ra-admin", "admin", FINANCE),
            headers=world.auth(CUSTOMER_ADMIN, **{"If-Match": etag}),
        )
        past = client.put(
            url,
            json=_role_body(TARGET, "ra-admin", "admin", FINANCE, expires_at=_ts(-10)),
            headers=world.auth(CUSTOMER_ADMIN, **{"If-Match": etag}),
        )
        allowed = client.put(
            url,
            json=_role_body(TARGET, "ra-admin", "admin", FINANCE, expires_at=_ts(3600)),
            headers=world.auth(CUSTOMER_ADMIN, **{"If-Match": etag}),
        )
    assert domain_only.status_code == 403
    assert domain_only.json()["reason"] == "customer_scope_required"
    assert auditor.status_code == 403
    assert auditor.json()["reason"] == "customer_scope_required"
    assert no_expiry.status_code == 422
    assert past.status_code == 422
    assert allowed.status_code == 200, allowed.text


def test_customer_control_domain_changes_need_customer_wide_authority(
    world: IdentityWorld,
) -> None:
    path = f"{BASE}/principals/{pid(TARGET)}/domain-memberships/{CONTROL}"
    body = {
        "schema_version": "1.0.0",
        "op": "add",
        "principal_id": pid(TARGET),
        "domain_id": CONTROL,
        "reason": "operator",
    }
    with world.composed.client() as client:
        etag = _etag(client, world, CUSTOMER_ADMIN, TARGET)
        domain_admin = client.put(
            path, json=body, headers=world.auth(DOMAIN_ADMIN, **{"If-Match": etag})
        )
        customer_admin = client.put(
            path, json=body, headers=world.auth(CUSTOMER_ADMIN, **{"If-Match": etag})
        )
    assert domain_admin.status_code == 403
    assert customer_admin.status_code == 200, customer_admin.text


def test_cross_customer_and_cross_cloud_targets_are_403(world: IdentityWorld) -> None:
    other_customer = pid(TARGET).replace(":contoso:", ":fabrikam:")
    other_cloud = pid(TARGET).replace("commercial:", "government:", 1)
    with world.composed.client() as client:
        responses = [
            client.get(f"{BASE}/principals/{target}", headers=world.auth(CUSTOMER_ADMIN))
            for target in (other_customer, other_cloud)
        ]
    for response in responses:
        assert response.status_code == 403
        assert response.json()["reason"] == "cross_scope_target"


def test_analyst_without_policy_manage_is_403(world: IdentityWorld) -> None:
    with world.composed.client() as client:
        response = client.get(f"{BASE}/principals", headers=world.auth(TARGET))
    assert response.status_code == 403
    assert response.json()["reason"] == "permission_missing"


def test_path_body_mismatch_is_422(world: IdentityWorld) -> None:
    with world.composed.client() as client:
        response = client.put(
            f"{BASE}/principals/{pid(TARGET)}/role-assignments/ra-other",
            json=_role_body(TARGET, "ra-x", "viewer", FINANCE),
            headers=world.auth(DOMAIN_ADMIN),
        )
    assert response.status_code == 422
    assert response.json()["reason"] == "path_body_mismatch"


def test_invalid_principal_id_is_refused_and_not_echoed_in_errors(world: IdentityWorld) -> None:
    upn = "alice.example@contoso.example"
    with world.composed.client() as client:
        response = client.get(f"{BASE}/principals/{quote(upn)}", headers=world.auth(DOMAIN_ADMIN))
    assert response.status_code == 422
    body = response.json()
    assert upn not in repr(body.get("errors")) and upn not in body.get("detail", "")


# ------------------------------------------------------------------ concurrency


def test_stale_and_missing_if_match(world: IdentityWorld) -> None:
    url = f"{BASE}/principals/{pid(TARGET)}/role-assignments/ra-v"
    body = _role_body(TARGET, "ra-v", "viewer", FINANCE)
    with world.composed.client() as client:
        missing = client.put(url, json=body, headers=world.auth(DOMAIN_ADMIN))
        stale = client.put(
            url, json=body, headers=world.auth(DOMAIN_ADMIN, **{"If-Match": '"old"'})
        )
        etag = _etag(client, world, DOMAIN_ADMIN, TARGET)
        first = client.put(url, json=body, headers=world.auth(DOMAIN_ADMIN, **{"If-Match": etag}))
        lost_update = client.put(
            url, json=body, headers=world.auth(DOMAIN_ADMIN, **{"If-Match": etag})
        )
        create_with_etag = client.put(
            f"{BASE}/principals/{pid(STEWARD)}/role-assignments/ra-v".replace(
                pid(STEWARD), pid("6f7a8b9c-0d1e-4f2a-9b4c-5d6e7f8091a2")
            ),
            json=_role_body("6f7a8b9c-0d1e-4f2a-9b4c-5d6e7f8091a2", "ra-v", "viewer", FINANCE),
            headers=world.auth(DOMAIN_ADMIN, **{"If-Match": etag}),
        )
    assert missing.status_code == 422
    assert missing.json()["reason"] == "precondition_required"
    assert stale.status_code == 409 and stale.json()["code"] == "stale_version"
    assert first.status_code == 200, first.text
    assert lost_update.status_code == 409
    assert create_with_etag.status_code == 409


def test_create_for_a_new_principal_needs_no_if_match(world: IdentityWorld) -> None:
    newcomer = "6f7a8b9c-0d1e-4f2a-9b4c-5d6e7f8091a2"
    path = f"{BASE}/principals/{pid(newcomer)}/domain-memberships/{FINANCE}"
    body = {
        "schema_version": "1.0.0",
        "op": "add",
        "principal_id": pid(newcomer),
        "domain_id": FINANCE,
        "reason": "onboarding",
    }
    with world.composed.client() as client:
        response = client.put(path, json=body, headers=world.auth(DOMAIN_ADMIN))
        listed = client.get(f"{BASE}/principals", headers=world.auth(DOMAIN_ADMIN))
    assert response.status_code == 200, response.text
    assert pid(newcomer) in {i["principal"]["principal_id"] for i in listed.json()["items"]}


# ------------------------------------------------------------------ reads


def test_list_shows_only_managed_principals_and_domains(world: IdentityWorld) -> None:
    with world.composed.client() as client:
        response = client.get(f"{BASE}/principals", headers=world.auth(DOMAIN_ADMIN))
    assert response.status_code == 200, response.text
    items = {i["principal"]["principal_id"]: i for i in response.json()["items"]}
    assert pid(HR_ONLY) not in items
    assert pid(TARGET) in items
    target = items[pid(TARGET)]
    assert target["memberships"] == [FINANCE]  # OPERATIONS is not the actor's to see
    for item in items.values():
        for assignment in item["assignments"]:
            assert set(assignment["domain_ids"]) <= {FINANCE}
    assert HR not in response.text
    _no_raw_ids(response.text)


def test_list_page_size_is_bounded_and_pages(world: IdentityWorld) -> None:
    with world.composed.client() as client:
        too_big = client.get(f"{BASE}/principals?limit=201", headers=world.auth(DOMAIN_ADMIN))
        zero = client.get(f"{BASE}/principals?limit=0", headers=world.auth(DOMAIN_ADMIN))
        first = client.get(f"{BASE}/principals?limit=1", headers=world.auth(DOMAIN_ADMIN))
        cursor = first.json()["next_cursor"]
        second = client.get(
            f"{BASE}/principals",
            params={"limit": 1, "cursor": cursor},
            headers=world.auth(DOMAIN_ADMIN),
        )
    assert too_big.status_code == 422 and zero.status_code == 422
    assert len(first.json()["items"]) == 1 and cursor is not None
    assert second.json()["items"][0]["principal"]["principal_id"] > cursor


def test_detail_of_an_unmanaged_principal_is_404(world: IdentityWorld) -> None:
    with world.composed.client() as client:
        response = client.get(f"{BASE}/principals/{pid(HR_ONLY)}", headers=world.auth(DOMAIN_ADMIN))
    assert response.status_code == 404
    assert response.json()["reason"] == "principal_not_found"


def test_detail_reports_revocation_state(world: IdentityWorld) -> None:
    with world.composed.client() as client:
        response = client.get(f"{BASE}/principals/{pid(TARGET)}", headers=world.auth(DOMAIN_ADMIN))
    revocation = response.json()["revocation"]
    assert revocation["revoked"] is False
    assert revocation["propagation_bound_seconds"] == 60


# ------------------------------------------------------------------ fail closed


def test_policy_store_outage_is_503(world: IdentityWorld) -> None:
    plane = world.composed.app.state.identity_admin
    with world.composed.client() as client:
        etag = _etag(client, world, DOMAIN_ADMIN, TARGET)
        plane.policy_admin.fail_with(
            DependencyTransientError("down", reason="policy_store_unavailable")
        )
        response = client.put(
            f"{BASE}/principals/{pid(TARGET)}/role-assignments/ra-v",
            json=_role_body(TARGET, "ra-v", "viewer", FINANCE),
            headers=world.auth(DOMAIN_ADMIN, **{"If-Match": etag}),
        )
    assert response.status_code == 503


def test_audit_outage_before_the_write_aborts_it(world: IdentityWorld) -> None:
    head = world.head()
    with world.composed.client() as client:
        etag = _etag(client, world, DOMAIN_ADMIN, TARGET)
        world.audit_store.fail_with = RuntimeError("audit down")
        response = client.put(
            f"{BASE}/principals/{pid(TARGET)}/role-assignments/ra-v",
            json=_role_body(TARGET, "ra-v", "viewer", FINANCE),
            headers=world.auth(DOMAIN_ADMIN, **{"If-Match": etag}),
        )
    assert response.status_code == 503
    assert world.head() == head
