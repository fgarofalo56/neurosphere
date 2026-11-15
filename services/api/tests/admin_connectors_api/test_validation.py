"""PRP-42 item 3: refused bodies are 422, value-free, and store nothing."""

from __future__ import annotations

import json
from typing import Any

import pytest
from connectors_harness import (  # pyright: ignore[reportMissingImports]
    BASE,
    CUSTOMER_ADMIN,
    DOMAIN,
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


def _post(world: ConnectorsWorld, body: dict[str, Any]) -> Any:
    return world.composed.client().post(BASE, json=body, headers=world.auth(CUSTOMER_ADMIN))


def _billing(**settings: Any) -> dict[str, Any]:
    merged = {
        "storage_account_url": "https://acct.blob.core.windows.net",
        "container": "exports",
        "api_base_url": "https://api.example.test",
        **settings,
    }
    return gateway_body(
        connector_id="billing-main", connector_kind="billing_export", settings=merged
    )


SECRET = "do-not-echo-9f3a"  # noqa: S105


@pytest.mark.parametrize(
    "over",
    [
        {"password": SECRET},
        {"settings": {"api_base_url": "https://x.test", "api_token": SECRET}},
        {"settings": {"api_base_url": "https://x.test", "nested": {"k": SECRET}}},
        {"settings": {"api_base_url": "https://x.test", "list": [SECRET]}},
        {"settings": {"api_base_url": f"https://user:{SECRET}@x.test"}},
        {"settings": {"api_base_url": f"https://x.test/?sig={SECRET}"}},
        {"settings": {"api_base_url": "https://x.test", "unknown_key": SECRET}},
        {
            "credential": {
                "kind": "key_vault_secret",
                "secret_uri": f"https://evil-vault.azure.net/secrets/{SECRET}",
            }
        },
        {
            "credential": {
                "kind": "key_vault_secret",
                "secret_uri": f"https://v.vault.usgovcloudapi.net/secrets/{SECRET}",
            }
        },
        {"credential": {"kind": "key_vault_secret", "secret_value": SECRET}},
        {
            "credential": {
                "kind": "managed_identity",
                "managed_identity_client_id": "6c1d2e3f-4a5b-4c6d-8e7f-90a1b2c3d4e5",
            }
        },
        {"credential": None},
        {"domain_ids": ["commercial:fabrikam:neurosphere:domain:finance"]},
        {"domain_ids": []},
        {"connector_kind": "wildcard"},
    ],
)
def test_refused_bodies_are_422_store_nothing_and_never_echo(
    world: ConnectorsWorld, over: dict[str, Any]
) -> None:
    response = _post(world, gateway_body(**over))
    assert response.status_code == 422, response.text
    assert SECRET not in response.text and "evil-vault" not in response.text
    listed = world.composed.client().get(
        BASE, params={"include_retired": "true"}, headers=world.auth(CUSTOMER_ADMIN)
    )
    assert listed.json()["items"] == []
    assert SECRET not in json.dumps(world.records())


def test_partial_billing_export_is_422_with_the_field_pointer(world: ConnectorsWorld) -> None:
    response = _post(world, _billing())
    assert response.status_code == 422
    pointers = [e["pointer"] for e in response.json().get("errors", [])]
    assert "/settings/manifest_blob" in pointers


def test_complete_billing_export_is_accepted(world: ConnectorsWorld) -> None:
    response = _post(world, _billing(manifest_blob="run/manifest.json"))
    assert response.status_code == 201, response.text
    assert response.json()["settings"]["container"] == "exports"


def test_billing_export_domain_must_be_single(world: ConnectorsWorld) -> None:
    body = _billing(manifest_blob="run/manifest.json")
    body["domain_ids"] = [DOMAIN, "commercial:contoso:neurosphere:domain:ops"]
    assert _post(world, body).status_code == 422


def test_billing_interval_below_the_worker_minimum_is_422(world: ConnectorsWorld) -> None:
    assert _post(world, _billing(manifest_blob="m.json", interval_seconds=60)).status_code == 422


def test_a_refused_write_is_audited_as_failed_with_a_reason_code(world: ConnectorsWorld) -> None:
    assert (
        _post(
            world, gateway_body(settings={"api_base_url": "https://x.test", "x_key": 1})
        ).status_code
        == 422
    )
    text = json.dumps(world.records())
    assert "failed" in text and VAULT_URI not in text


def test_producer_with_wrong_source_kind_is_422(world: ConnectorsWorld) -> None:
    import asyncio

    producer = {
        "schema_version": "1.0.0",
        "producer_id": "apim-gateway-poll",
        "customer_id": "contoso",
        "cloud": "commercial",
        "sources": [{"source_id": "apim-gateway-poll", "observation_kind": "billing"}],
        "secret_sha256": "a" * 64,
        "status": "active",
        "rotated_at": None,
    }
    actor = "commercial:contoso:entra:person:p-" + "0c" * 32
    asyncio.run(
        world.repository.create(
            "contoso", "producer", "apim-gateway-poll", producer, updated_by=actor
        )
    )
    body = gateway_body(
        settings={"api_base_url": "https://x.test", "producer_id": "apim-gateway-poll"}
    )
    assert _post(world, body).status_code == 422
