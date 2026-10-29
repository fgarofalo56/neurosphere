"""Gateway registry API (PRP-33 item 6): routes, authz, audit, read-only, fail closed."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import Any

import pytest
from gateway_harness import (  # pyright: ignore[reportMissingImports]
    ADMIN,
    FINANCE,
    OPERATIONS,
    PREFIX,
    RID,
    SECRET_MARKER,
    STEWARD,
    VIEWER,
    XML_MARKER,
    FakeArm,
    make_env,
)
from neurosphere_api.authz import route_inventory, undeclared_routes
from neurosphere_core.errors import DependencyTransientError
from neurosphere_core.gateway import ApiEntry, GatewayInventory
from neurosphere_core.gateway import inventory as inv

AUDIT_CHAIN = "contoso.gateway"


def _sync_path(gateway_id: str, domain: str = FINANCE) -> str:
    return f"/domains/{domain}/gateways/{gateway_id}/sync"


def _audit(env: Any) -> list[Any]:
    return list(asyncio.run(env.audit.read_range(AUDIT_CHAIN, limit=200)))


def test_register_returns_201_with_preflight_facts() -> None:
    env = make_env(FakeArm(sku="StandardV2", llm_logs=True))
    response = env.register(workspace_id="aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee")
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["id"].startswith("gw-")
    assert body["tier"] == "standard_v2"
    assert body["sku_name_raw"] == "StandardV2"
    assert body["mode"] == "observe"
    assert body["cloud"] == "commercial"
    assert body["domain_id"] == FINANCE
    assert body["customer_id"] == "contoso"
    assert body["last_sync_status"] == "never"
    assert body["diagnostics"]["gateway_llm_logs"] is True
    assert body["diagnostics"]["gateway_mcp_logs"] is False
    assert set(body["capabilities"]) >= {"gateway_llm_logs", "llm_token_limit"}
    assert body["registered_by"]
    assert body["etag"]


def test_register_twice_conflicts() -> None:
    env = make_env()
    assert env.register().status_code == 201
    again = env.register()
    assert again.status_code == 409
    assert again.json()["reason"] == "gateway_already_registered"


def test_register_rejects_malformed_arm_id_and_extra_fields() -> None:
    env = make_env()
    bad = env.call(
        "POST", ADMIN, f"/domains/{FINANCE}/gateways", json={"arm_resource_id": "/subscriptions/x"}
    )
    assert bad.status_code == 422
    extra = env.call(
        "POST",
        ADMIN,
        f"/domains/{FINANCE}/gateways",
        json={"arm_resource_id": RID, "customer_id": "other"},
    )
    assert extra.status_code == 422
    assert env.arm.requests == []  # type: ignore[attr-defined]


def test_list_and_detail_for_a_reader() -> None:
    env = make_env()
    created = env.register().json()
    listing = env.call("GET", VIEWER, f"/domains/{FINANCE}/gateways")
    assert listing.status_code == 200
    assert [g["id"] for g in listing.json()["items"]] == [created["id"]]
    assert listing.json()["next_cursor"] is None
    detail = env.call("GET", VIEWER, f"/domains/{FINANCE}/gateways/{created['id']}")
    assert detail.status_code == 200
    assert detail.json()["inventory_counts"] is None


def test_sync_builds_inventory_and_updates_status() -> None:
    env = make_env()
    created = env.register().json()
    assert (
        env.call(
            "GET", VIEWER, f"/domains/{FINANCE}/gateways/{created['id']}/inventory"
        ).status_code
        == 404
    )
    synced = env.call("POST", ADMIN, _sync_path(created["id"]))
    assert synced.status_code == 200, synced.text
    body = synced.json()
    assert body["last_sync_status"] == "ok"
    assert body["last_sync_at"]
    assert body["freshness_seconds"] is not None
    assert body["inventory_counts"] == {
        "apis": 2,
        "operations": 1,
        "products": 1,
        "backends": 2,
        "policy_fragments": 1,
        "subscriptions": 1,
    }
    inventory = env.call("GET", VIEWER, f"/domains/{FINANCE}/gateways/{created['id']}/inventory")
    assert inventory.status_code == 200
    snapshot = inventory.json()
    assert snapshot["gateway_id"] == created["id"]
    assert [b["type"] for b in snapshot["backends"]] == ["Single", "Pool"]
    text = json.dumps(snapshot) + json.dumps(body)
    assert SECRET_MARKER not in text
    assert XML_MARKER not in text


def test_sync_replaces_never_merges() -> None:
    env = make_env()
    created = env.register().json()
    stale = GatewayInventory(
        gateway_id=created["id"],
        taken_at=datetime(2026, 1, 1, tzinfo=UTC),
        apis=[ApiEntry(id="legacy-api")],
    )
    asyncio.run(env.store.put_inventory("contoso", FINANCE, stale))
    assert env.call("POST", ADMIN, _sync_path(created["id"])).status_code == 200
    snapshot = env.call(
        "GET", ADMIN, f"/domains/{FINANCE}/gateways/{created['id']}/inventory"
    ).json()
    assert "legacy-api" not in [a["id"] for a in snapshot["apis"]]


def test_sync_refreshes_diagnostics_and_tier() -> None:
    arm = FakeArm(llm_logs=False)
    env = make_env(arm)
    created = env.register().json()
    assert created["diagnostics"]["gateway_llm_logs"] is False
    arm.llm_logs = True
    arm.sku = "PremiumV2"
    synced = env.call("POST", ADMIN, _sync_path(created["id"])).json()
    assert synced["diagnostics"]["gateway_llm_logs"] is True
    assert synced["tier"] == "premium_v2"


def test_failed_sync_is_recorded_and_surfaces_503() -> None:
    arm = FakeArm()
    env = make_env(arm)
    created = env.register().json()
    arm.throttle_forever = True

    async def no_sleep(_: float) -> None:
        return None

    original = inv._sleep
    inv._sleep = no_sleep
    try:
        failed = env.call("POST", ADMIN, _sync_path(created["id"]))
    finally:
        inv._sleep = original
    assert failed.status_code == 503
    assert failed.json()["reason"] == "arm_rate_limited"
    detail = env.call("GET", ADMIN, f"/domains/{FINANCE}/gateways/{created['id']}").json()
    assert detail["last_sync_status"] == "failed"
    assert inv.MAX_RETRIES == 3


def test_only_get_requests_reach_arm_across_register_and_sync() -> None:
    arm = FakeArm()
    env = make_env(arm)
    created = env.register().json()
    env.call("POST", ADMIN, _sync_path(created["id"]))
    assert arm.requests
    assert arm.methods == {"GET"}
    assert not any(
        word in path.lower()
        for path in arm.paths
        for word in ("listsecrets", "listkeys", "namedvalues")
    )


def test_register_and_sync_are_audited_without_secrets() -> None:
    env = make_env()
    created = env.register().json()
    env.call("POST", ADMIN, _sync_path(created["id"]))
    records = _audit(env)
    assert len(records) == 4
    dumped = json.dumps([r.model_dump(mode="json") for r in records])
    assert "gateway.register" in dumped
    assert "gateway.sync" in dumped
    assert created["id"] in dumped
    assert RID not in dumped
    assert "11111111-2222-4333-8444-555555555555" not in dumped
    assert SECRET_MARKER not in dumped


def test_denied_register_is_not_audited_and_calls_no_arm() -> None:
    arm = FakeArm()
    env = make_env(arm)
    denied = env.call("POST", VIEWER, f"/domains/{FINANCE}/gateways", json={"arm_resource_id": RID})
    assert denied.status_code == 403
    assert _audit(env) == []
    assert arm.requests == []


# -- authorization ----------------------------------------------------------------------------


def test_unauthenticated_is_401() -> None:
    env = make_env()
    assert env.call("GET", None, f"/domains/{FINANCE}/gateways").status_code == 401
    assert env.call("POST", None, f"/domains/{FINANCE}/gateways", json={}).status_code == 401


@pytest.mark.parametrize("who", [VIEWER, STEWARD])
def test_writes_need_config_manage(who: str) -> None:
    env = make_env()
    created = env.register().json()
    post = env.call("POST", who, f"/domains/{FINANCE}/gateways", json={"arm_resource_id": RID})
    assert post.status_code == 403
    assert env.call("POST", who, _sync_path(created["id"])).status_code == 403


def test_out_of_domain_is_403_for_every_route() -> None:
    env = make_env()
    created = env.register().json()
    gid = created["id"]
    calls = [
        ("GET", f"/domains/{OPERATIONS}/gateways"),
        ("GET", f"/domains/{OPERATIONS}/gateways/{gid}"),
        ("GET", f"/domains/{OPERATIONS}/gateways/{gid}/inventory"),
        ("POST", _sync_path(gid, OPERATIONS)),
    ]
    for method, path in calls:
        assert env.call(method, ADMIN, path).status_code == 403, (method, path)
    post = env.call("POST", ADMIN, f"/domains/{OPERATIONS}/gateways", json={"arm_resource_id": RID})
    assert post.status_code == 403


def test_gateway_of_another_domain_is_404_not_leaked() -> None:
    env = make_env()
    created = env.register().json()
    # Same caller, wrong partition key: a gateway id only resolves inside its own domain.
    assert env.store is not None
    other = env.call("GET", ADMIN, f"/domains/{FINANCE}/gateways/gw-{'0' * 32}")
    assert other.status_code == 404
    assert created["id"] != f"gw-{'0' * 32}"


# -- fail closed ------------------------------------------------------------------------------


def test_store_outage_is_503_never_empty() -> None:
    env = make_env()
    env.store.fail_with(DependencyTransientError("down", reason="gateway_store_unavailable"))
    listing = env.call("GET", ADMIN, f"/domains/{FINANCE}/gateways")
    assert listing.status_code == 503
    assert listing.json()["reason"] == "gateway_store_unavailable"
    assert env.call("GET", ADMIN, f"/domains/{FINANCE}/gateways/gw-{'0' * 32}").status_code == 503


def test_unconfigured_plane_is_503() -> None:
    env = make_env(configure=False)
    response = env.call("GET", ADMIN, f"/domains/{FINANCE}/gateways")
    assert response.status_code == 503
    assert response.json()["reason"] == "gateway_plane_unconfigured"


def test_arm_denied_maps_to_409_not_readable() -> None:
    env = make_env(FakeArm(service_status=403))
    response = env.register()
    assert response.status_code == 409
    assert response.json()["reason"] == "gateway_not_readable"
    assert asyncio.run(env.store.list("contoso", FINANCE)).items == ()


def test_malformed_gateway_id_is_422() -> None:
    env = make_env()
    assert env.call("GET", ADMIN, f"/domains/{FINANCE}/gateways/not-an-id").status_code == 422


# -- route inventory / OpenAPI ----------------------------------------------------------------


def test_every_gateway_route_declares_a_permission() -> None:
    env = make_env()
    assert undeclared_routes(env.auth.app) == ()
    declared = {
        (e.path, e.methods): e.permissions
        for e in route_inventory(env.auth.app)
        if e.path.startswith(PREFIX)
    }
    base = f"{PREFIX}/domains/{{domain}}/gateways"
    assert declared == {
        (base, ("POST",)): ("config.manage",),
        (base, ("GET",)): ("data.read",),
        (f"{base}/{{gateway_id}}", ("GET",)): ("data.read",),
        (f"{base}/{{gateway_id}}/inventory", ("GET",)): ("data.read",),
        (f"{base}/{{gateway_id}}/sync", ("POST",)): ("config.manage",),
        # PRP-34 item 2: the mode switch drafts an action intent.
        (f"{base}/{{gateway_id}}/mode", ("POST",)): ("action.propose", "config.manage"),
    }


def test_openapi_documents_the_gateway_routes() -> None:
    env = make_env()
    paths = env.auth.app.openapi()["paths"]
    base = f"{PREFIX}/domains/{{domain}}/gateways"
    assert set(paths[base]) == {"get", "post"}
    assert "post" in paths[f"{base}/{{gateway_id}}/sync"]
    assert "get" in paths[f"{base}/{{gateway_id}}/inventory"]
