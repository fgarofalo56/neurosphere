"""PRP-42 item 1: ConnectorConfigAdmin over the in-memory admin_config store."""

from __future__ import annotations

from typing import Any

import pytest
from neurosphere_core.admin import InMemoryAdminConfigRepository
from neurosphere_core.admin.connectors import (
    ConnectorConfigAdmin,
    ConnectorKindValidator,
    KindCheck,
)
from neurosphere_core.errors import InvalidSchemaError, NotFoundError, StaleVersionError

CUSTOMER = "contoso"
ACTOR = "commercial:contoso:entra:person:p-" + "0c" * 32
DOMAIN = "commercial:contoso:neurosphere:domain:finance"
MI = {
    "kind": "managed_identity",
    "managed_identity_client_id": "6c1d2e3f-4a5b-4c6d-8e7f-90a1b2c3d4e5",
}
VAULT = "https://ns-kv.vault.azure.net/secrets/producer-key"


def _producer(
    cloud: str = "commercial", kind: str = "gateway", source: str = "apim"
) -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "producer_id": "apim-gateway-poll",
        "customer_id": CUSTOMER,
        "cloud": cloud,
        "sources": [{"source_id": source, "observation_kind": kind}],
        "secret_sha256": "a" * 64,
        "status": "active",
        "rotated_at": None,
    }


def _body(**over: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "schema_version": "1.0.0",
        "connector_id": "poll-main",
        "connector_kind": "gateway_poll",
        "domain_ids": [DOMAIN],
        "settings": {"interval_seconds": 600},
        "credential": {"kind": "key_vault_secret", "secret_uri": VAULT},
        "enabled": True,
    }
    body.update(over)
    return body


def _validator(check: KindCheck | None = None) -> ConnectorKindValidator:
    def validate(config: Any, *, cloud: str) -> KindCheck:
        return check or KindCheck(producer_id="apim-gateway-poll", source_id="apim")

    return validate


def _admin(
    repo: InMemoryAdminConfigRepository | None = None, **checks: Any
) -> tuple[ConnectorConfigAdmin, InMemoryAdminConfigRepository]:
    repo = repo or InMemoryAdminConfigRepository(cloud="commercial")
    validators = {
        k: _validator(checks.get(k))
        for k in ("gateway_poll", "foundry_discovery", "billing_export", "otel", "azure_monitor_ai")
    }
    return ConnectorConfigAdmin(repo, cloud="commercial", validators=validators), repo


async def test_create_stores_an_active_document_and_get_returns_it() -> None:
    admin, _ = _admin()
    write = await admin.create(CUSTOMER, _body(), updated_by=ACTOR)
    assert write.document.version.root == 1 and write.document.id.root == "poll-main"
    assert (await admin.get(CUSTOMER, "poll-main")).etag == write.document.etag


@pytest.mark.parametrize(
    "over",
    [
        {"settings": {"api_token": "x"}},
        {"settings": {"nested": {"a": 1}}},
        {"settings": {"list": [1]}},
        {"settings": {"api_base_url": "https://u:p@api.example/"}},
        {"settings": {"api_base_url": "https://api.example/?sig=1"}},
        {
            "credential": {
                "kind": "key_vault_secret",
                "secret_uri": "https://ns-kv.vault.usgovcloudapi.net/secrets/x",
            }
        },
        {
            "credential": {
                "kind": "key_vault_secret",
                "secret_uri": "https://evil-vault.azure.net/secrets/x",
            }
        },
        {"domain_ids": ["commercial:fabrikam:neurosphere:domain:finance"]},
        {"domain_ids": ["government:contoso:neurosphere:domain:finance"]},
        {"password": "x"},
        {"credential": None},
    ],
)
async def test_refused_bodies_store_nothing(over: dict[str, Any]) -> None:
    admin, repo = _admin()
    with pytest.raises(InvalidSchemaError):
        await admin.create(CUSTOMER, _body(**over), updated_by=ACTOR)
    assert await repo.list_by_kind(CUSTOMER, "connector_config", include_retired=True) == []


async def test_kind_validator_refusal_propagates() -> None:
    def refuse(config: Any, *, cloud: str) -> KindCheck:
        raise InvalidSchemaError("bad", reason="gateway_poll_domain_ids_missing")

    repo = InMemoryAdminConfigRepository(cloud="commercial")
    admin = ConnectorConfigAdmin(repo, cloud="commercial", validators={"gateway_poll": refuse})
    with pytest.raises(InvalidSchemaError):
        await admin.create(CUSTOMER, _body(), updated_by=ACTOR)


async def test_one_active_config_per_kind() -> None:
    admin, _ = _admin()
    await admin.create(CUSTOMER, _body(), updated_by=ACTOR)
    with pytest.raises(StaleVersionError) as caught:
        await admin.create(CUSTOMER, _body(connector_id="poll-two"), updated_by=ACTOR)
    assert caught.value.reason == "connector_kind_exists"


async def test_replace_needs_a_fresh_etag_and_keeps_kind() -> None:
    admin, _ = _admin()
    first = (await admin.create(CUSTOMER, _body(), updated_by=ACTOR)).document
    second = await admin.replace(
        CUSTOMER,
        "poll-main",
        _body(settings={"interval_seconds": 900}),
        if_match=first.etag.root,
        updated_by=ACTOR,
    )
    assert second.document.version.root == 2
    with pytest.raises(StaleVersionError) as stale:
        await admin.replace(
            CUSTOMER, "poll-main", _body(), if_match=first.etag.root, updated_by=ACTOR
        )
    assert stale.value.reason == "admin_config_modified"
    with pytest.raises(InvalidSchemaError) as kind:
        await admin.replace(
            CUSTOMER,
            "poll-main",
            _body(connector_kind="otel"),
            if_match=second.document.etag.root,
            updated_by=ACTOR,
        )
    assert kind.value.reason == "connector_kind_immutable"


async def test_disable_enable_and_retire_keeps_document_readable() -> None:
    admin, _ = _admin()
    doc = (await admin.create(CUSTOMER, _body(), updated_by=ACTOR)).document
    off = (
        await admin.set_enabled(
            CUSTOMER, "poll-main", False, if_match=doc.etag.root, updated_by=ACTOR
        )
    ).document
    assert off.body.enabled is False  # type: ignore[union-attr]
    on = (
        await admin.set_enabled(
            CUSTOMER, "poll-main", True, if_match=off.etag.root, updated_by=ACTOR
        )
    ).document
    retired = await admin.retire(CUSTOMER, "poll-main", if_match=on.etag.root, updated_by=ACTOR)
    assert retired.status == "retired"
    assert (await admin.get(CUSTOMER, "poll-main")).status == "retired"
    assert await admin.list(CUSTOMER) == []
    # retiring frees the kind
    await admin.create(CUSTOMER, _body(connector_id="poll-two"), updated_by=ACTOR)


async def test_get_missing_is_not_found() -> None:
    admin, _ = _admin()
    with pytest.raises(NotFoundError):
        await admin.get(CUSTOMER, "nope")


async def test_list_filters_by_kind() -> None:
    admin, _ = _admin()
    await admin.create(CUSTOMER, _body(), updated_by=ACTOR)
    await admin.create(
        CUSTOMER,
        _body(connector_id="otel-1", connector_kind="otel", credential=MI),
        updated_by=ACTOR,
    )
    assert [d.id.root for d in await admin.list(CUSTOMER, connector_kind="otel")] == ["otel-1"]
    assert len(await admin.list(CUSTOMER)) == 2


async def test_producer_in_store_is_checked_and_absent_is_a_warning() -> None:
    repo = InMemoryAdminConfigRepository(cloud="commercial")
    admin, _ = _admin(repo)
    body = _body(settings={"producer_id": "apim-gateway-poll"})
    absent = await admin.create(CUSTOMER, body, updated_by=ACTOR)
    assert absent.warnings == ("producer_not_in_store",)
    await admin.retire(CUSTOMER, "poll-main", if_match=absent.document.etag.root, updated_by=ACTOR)

    await repo.create(CUSTOMER, "producer", "apim-gateway-poll", _producer(), updated_by=ACTOR)
    ok = await admin.create(
        CUSTOMER,
        _body(connector_id="p2", settings={"producer_id": "apim-gateway-poll"}),
        updated_by=ACTOR,
    )
    assert ok.warnings == ()


@pytest.mark.parametrize(
    ("producer", "reason"),
    [
        (_producer(kind="billing"), "producer_source_kind_mismatch"),
        (_producer(source="other"), "producer_source_missing"),
    ],
)
async def test_producer_mismatches_are_422(producer: dict[str, Any], reason: str) -> None:
    repo = InMemoryAdminConfigRepository(cloud="commercial")
    await repo.create(CUSTOMER, "producer", "apim-gateway-poll", producer, updated_by=ACTOR)
    admin, _ = _admin(repo)
    with pytest.raises(InvalidSchemaError) as caught:
        await admin.create(
            CUSTOMER, _body(settings={"producer_id": "apim-gateway-poll"}), updated_by=ACTOR
        )
    assert caught.value.reason == reason


_AMA = KindCheck(producer_id="apim-gateway-poll", source_id="ama")


def _ama_body() -> dict[str, Any]:
    return _body(
        connector_id="ama-main",
        connector_kind="azure_monitor_ai",
        settings={"producer_id": "apim-gateway-poll"},
    )


@pytest.mark.parametrize(
    ("producer", "reason"),
    [
        (_producer(cloud="government", kind="application", source="ama"), "cross_cloud"),
        (_producer(kind="gateway", source="ama"), "producer_source_kind_mismatch"),
        (_producer(kind="billing", source="ama"), "producer_source_kind_mismatch"),
    ],
)
async def test_azure_monitor_ai_producer_must_be_an_application_source_on_this_cloud(
    producer: dict[str, Any], reason: str
) -> None:
    # A producer record of another cloud cannot be written through a commercial store, so the
    # record sits in a store of its own cloud while the admin serves the commercial deployment.
    repo = InMemoryAdminConfigRepository(cloud=producer["cloud"])
    await repo.create(CUSTOMER, "producer", "apim-gateway-poll", producer, updated_by=ACTOR)
    admin, _ = _admin(repo, azure_monitor_ai=_AMA)
    with pytest.raises(InvalidSchemaError) as caught:
        await admin.create(CUSTOMER, _ama_body(), updated_by=ACTOR)
    assert caught.value.reason == reason


async def test_azure_monitor_ai_with_an_application_producer_is_accepted() -> None:
    repo = InMemoryAdminConfigRepository(cloud="commercial")
    await repo.create(
        CUSTOMER,
        "producer",
        "apim-gateway-poll",
        _producer(kind="application", source="ama"),
        updated_by=ACTOR,
    )
    admin, _ = _admin(repo, azure_monitor_ai=_AMA)
    write = await admin.create(CUSTOMER, _ama_body(), updated_by=ACTOR)
    assert write.warnings == ()
