"""PRP-42 item 3: connector admin routes (create, list, get, replace, enable, disable, retire)."""

from __future__ import annotations

import json
from typing import Any

import pytest
from connectors_harness import (  # pyright: ignore[reportMissingImports]
    ANALYST,
    BASE,
    CUSTOMER_ADMIN,
    DOMAIN_ADMIN,
    VAULT_URI,
    ConnectorsWorld,
    configure_env,
    gateway_body,
)


@pytest.fixture(autouse=True)
def _auth(monkeypatch: pytest.MonkeyPatch) -> None:
    configure_env(monkeypatch)


@pytest.fixture
def world() -> ConnectorsWorld:
    return ConnectorsWorld.build()


def _create(world: ConnectorsWorld, body: dict[str, Any] | None = None) -> Any:
    return world.composed.client().post(
        BASE, json=body or gateway_body(), headers=world.auth(CUSTOMER_ADMIN)
    )


def test_create_returns_201_etag_and_a_reference_only_view(world: ConnectorsWorld) -> None:
    response = _create(world)
    assert response.status_code == 201, response.text
    assert response.headers["etag"]
    body = response.json()
    assert body["connector_id"] == "gateway-main" and body["version"] == 1
    assert body["credential"] == {
        "kind": "key_vault_secret",
        "secret_uri": VAULT_URI,
        "managed_identity_client_id": None,
    }
    assert body["warnings"] == []


def test_create_is_audited_before_and_after_without_references(world: ConnectorsWorld) -> None:
    assert _create(world).status_code == 201
    records = world.records()
    assert len(records) == 2
    text = json.dumps(records)
    assert "connector.create" in text
    assert VAULT_URI not in text and "ns-kv" not in text and "api.example.test" not in text
    assert all(r["chain_id"] == "contoso.admin-config" for r in records)


def test_get_and_list_return_the_stored_config(world: ConnectorsWorld) -> None:
    etag = _create(world).headers["etag"]
    client = world.composed.client()
    got = client.get(f"{BASE}/gateway-main", headers=world.auth(CUSTOMER_ADMIN))
    assert got.status_code == 200 and got.headers["etag"] == etag
    listed = client.get(
        BASE, params={"connector_kind": "gateway_poll"}, headers=world.auth(CUSTOMER_ADMIN)
    )
    assert [i["connector_id"] for i in listed.json()["items"]] == ["gateway-main"]
    other = client.get(BASE, params={"connector_kind": "otel"}, headers=world.auth(CUSTOMER_ADMIN))
    assert other.json()["items"] == []
    missing = client.get(f"{BASE}/nope", headers=world.auth(CUSTOMER_ADMIN))
    assert missing.status_code == 404


def test_replace_needs_if_match_and_rejects_a_stale_one(world: ConnectorsWorld) -> None:
    etag = _create(world).headers["etag"]
    client = world.composed.client()
    headers = world.auth(CUSTOMER_ADMIN)
    body = gateway_body(settings={"api_base_url": "https://api.example.test", "batch_size": 50})
    assert client.put(f"{BASE}/gateway-main", json=body, headers=headers).status_code == 422
    ok = client.put(f"{BASE}/gateway-main", json=body, headers={**headers, "If-Match": etag})
    assert ok.status_code == 200 and ok.json()["version"] == 2
    stale = client.put(f"{BASE}/gateway-main", json=body, headers={**headers, "If-Match": etag})
    assert stale.status_code == 409


def test_disable_enable_and_retire_round_trip(world: ConnectorsWorld) -> None:
    etag = _create(world).headers["etag"]
    client = world.composed.client()
    headers = world.auth(CUSTOMER_ADMIN)
    off = client.post(f"{BASE}/gateway-main/disable", headers={**headers, "If-Match": etag})
    assert off.status_code == 200 and off.json()["enabled"] is False
    on = client.post(
        f"{BASE}/gateway-main/enable", headers={**headers, "If-Match": off.headers["etag"]}
    )
    assert on.json()["enabled"] is True
    gone = client.delete(
        f"{BASE}/gateway-main", headers={**headers, "If-Match": on.headers["etag"]}
    )
    assert gone.status_code == 200 and gone.json()["status"] == "retired"
    assert client.get(f"{BASE}/gateway-main", headers=headers).json()["status"] == "retired"
    assert client.get(BASE, headers=headers).json()["items"] == []


def test_absent_producer_is_a_warning_not_an_error(world: ConnectorsWorld) -> None:
    body = gateway_body(
        settings={"api_base_url": "https://api.example.test", "producer_id": "apim-gateway-poll"}
    )
    response = _create(world, body)
    assert response.status_code == 201
    assert response.json()["warnings"] == ["producer_not_in_store"]


@pytest.mark.parametrize("who", [DOMAIN_ADMIN, ANALYST])
def test_callers_without_customer_level_config_manage_get_403_on_every_route(
    world: ConnectorsWorld, who: str
) -> None:
    etag = _create(world).headers["etag"]
    client = world.composed.client()
    headers = {**world.auth(who), "If-Match": etag}
    calls = [
        client.post(BASE, json=gateway_body(connector_id="x"), headers=headers),
        client.get(BASE, headers=headers),
        client.get(f"{BASE}/gateway-main", headers=headers),
        client.put(f"{BASE}/gateway-main", json=gateway_body(), headers=headers),
        client.post(f"{BASE}/gateway-main/enable", headers=headers),
        client.post(f"{BASE}/gateway-main/disable", headers=headers),
        client.delete(f"{BASE}/gateway-main", headers=headers),
    ]
    assert [c.status_code for c in calls] == [403] * 7
    # nothing changed
    stored = world.composed.client().get(f"{BASE}/gateway-main", headers=world.auth(CUSTOMER_ADMIN))
    assert stored.json()["version"] == 1


def test_no_token_is_401(world: ConnectorsWorld) -> None:
    assert world.composed.client().get(BASE).status_code == 401


def test_a_second_active_config_of_the_kind_is_409(world: ConnectorsWorld) -> None:
    assert _create(world).status_code == 201
    assert _create(world, gateway_body(connector_id="gateway-two")).status_code == 409
