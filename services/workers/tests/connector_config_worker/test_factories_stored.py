"""PRP-42 item 4: the real role builders read the stored config (fakes, no network)."""

from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any, ClassVar

import pytest
from neurosphere_core.admin import InMemoryAdminConfigRepository
from neurosphere_core.clients import ClientLifetime
from neurosphere_core.cloud import CloudName, Settings
from neurosphere_workers.connector_config import (
    ConnectorCredentialUnavailableError,
    loader,
    resolve,
)
from neurosphere_workers.runtime import RoleConfigError
from neurosphere_workers.runtime import factories as f
from neurosphere_workers.runtime.settings import AuthSettings, StoreSettings, WorkerSettings

from .support import (
    ACTOR,
    CLIENT_ID,
    CUSTOMER,
    ENV_NAMES,
    SECRET_VALUE,
    FakeReader,
    billing,
    config,
    foundry,
    gateway,
    repo,
    store,
)

_APP_ID = "6c1d2e3f-4a5b-4c6d-8e7f-90a1b2c3d4e5"


class Capture:
    """Records constructor keyword arguments of a stubbed collaborator."""

    kwargs: ClassVar[dict[str, Any]] = {}
    own: dict[str, Any]

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        type(self).kwargs = kwargs
        self.own = kwargs

    async def tick(self) -> None:
        return None


class _Store:
    @staticmethod
    def from_client(*_: Any, **__: Any) -> object:
        return object()


def _cfg(cloud: CloudName | None = None) -> f.RuntimeConfig:
    return f.RuntimeConfig(
        Settings(env="local", cloud=cloud), WorkerSettings(), StoreSettings(), AuthSettings()
    )


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ENV_NAMES:
        monkeypatch.delenv(name, raising=False)

    async def _cosmos(*_: Any) -> object:
        return object()

    async def _create(*_: Any) -> None:
        return None

    monkeypatch.setattr(f, "_cosmos", _cosmos)
    monkeypatch.setattr(f, "_database", lambda *_: object())
    monkeypatch.setattr(f, "create_gateway_container", _create)
    monkeypatch.setattr(f, "CosmosGatewayStore", _Store)
    monkeypatch.setattr(f, "GatewayPoller", Capture)
    monkeypatch.setattr(f, "IngestClient", Capture)


def _use(
    monkeypatch: pytest.MonkeyPatch,
    repository: InMemoryAdminConfigRepository,
    reader: FakeReader | None = None,
) -> FakeReader:
    fake = reader or FakeReader()
    monkeypatch.setattr(loader, "open_repository", lambda cfg, lifetime: repository)
    monkeypatch.setattr(resolve, "build_reader", lambda cloud, *, client_id, timeout: fake)
    return fake


async def test_gateway_poll_runs_from_the_stored_config_and_ignores_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NS_GATEWAY_POLL_DOMAIN_IDS", "env-domain")
    monkeypatch.setenv("NS_GATEWAY_POLL_PRODUCER_SECRET", "env-secret")
    monkeypatch.setenv("NS_API_BASE_URL", "http://env-leak.invalid")
    repository = repo()
    await store(repository, gateway(interval_seconds=600, producer_id="stored-producer"))
    reader = _use(monkeypatch, repository)
    async with ClientLifetime() as lifetime:
        await f.build_gateway_poll(_cfg(), lifetime)
    assert reader.calls == 1
    ingest = Capture.kwargs
    # the last Capture construction is the poller; read the ingest one through its own capture
    assert ingest["domain_ids"] == ("commercial:synthco:neurosphere:domain:d1",)
    assert ingest["settings"].interval_seconds == 600
    assert ingest["settings"].api_base_url == "http://api.invalid"
    assert ingest["settings"].producer_secret.get_secret_value() == SECRET_VALUE
    assert ingest["ingest"].own["secret"] == SECRET_VALUE
    assert ingest["ingest"].own["base_url"] == "http://api.invalid"
    assert ingest["ingest"].own["producer_id"] == "stored-producer"


async def test_disabled_gateway_config_idles_and_does_not_use_env(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("NS_GATEWAY_POLL_DOMAIN_IDS", "env-domain")
    monkeypatch.setenv("NS_GATEWAY_POLL_PRODUCER_SECRET", "env-secret")
    monkeypatch.setenv("NS_API_BASE_URL", "http://env.invalid")
    Capture.kwargs = {}
    repository = repo()
    await store(
        repository, config("gateway_poll", enabled=False, settings={"api_base_url": "http://x"})
    )
    _use(monkeypatch, repository)
    with caplog.at_level(logging.INFO):
        async with ClientLifetime() as lifetime:
            await f.build_gateway_poll(_cfg(), lifetime)
    assert Capture.kwargs == {}
    events = [getattr(r, "event", None) for r in caplog.records]
    assert "worker.connector_config_disabled" in events


async def test_vault_failure_fails_the_role_without_uri(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    repository = repo()
    await store(repository, gateway())
    _use(monkeypatch, repository, FakeReader(ConnectorCredentialUnavailableError()))
    with caplog.at_level(logging.DEBUG):
        async with ClientLifetime() as lifetime:
            with pytest.raises(RoleConfigError) as caught:
                await f.build_gateway_poll(_cfg(), lifetime)
    assert caught.value.reason == "connector_credential_unavailable"
    assert "ns-kv" not in caplog.text and "ns-kv" not in str(caught.value)


async def test_store_failure_behaves_exactly_like_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NS_GATEWAY_POLL_DOMAIN_IDS", "env-domain")
    monkeypatch.setenv("NS_GATEWAY_POLL_PRODUCER_SECRET", "env-secret")
    monkeypatch.setenv("NS_API_BASE_URL", "http://env.invalid")
    repository = repo()
    repository.fail_with(RuntimeError("down"))
    _use(monkeypatch, repository)
    async with ClientLifetime() as lifetime:
        await f.build_gateway_poll(_cfg(), lifetime)
    assert Capture.kwargs["domain_ids"] == ("env-domain",)
    assert Capture.kwargs["ingest"].own["secret"] == "env-secret"  # noqa: S105


async def test_env_source_switch_ignores_a_stored_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NS_WORKER_CONNECTOR_CONFIG_SOURCE", "env")
    monkeypatch.setenv("NS_GATEWAY_POLL_DOMAIN_IDS", "env-domain")
    monkeypatch.setenv("NS_GATEWAY_POLL_PRODUCER_SECRET", "env-secret")
    monkeypatch.setenv("NS_API_BASE_URL", "http://env.invalid")
    repository = repo()
    await store(repository, gateway())
    reader = _use(monkeypatch, repository)
    async with ClientLifetime() as lifetime:
        await f.build_gateway_poll(_cfg(), lifetime)
    assert reader.calls == 0 and Capture.kwargs["domain_ids"] == ("env-domain",)


async def test_government_still_skips_gateway_metrics_with_a_stored_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gov = InMemoryAdminConfigRepository(cloud="government")
    body = config(
        "gateway_poll",
        domain_ids=["government:synthco:neurosphere:domain:d1"],
        settings={"api_base_url": "http://api.invalid", "metrics_app_id": _APP_ID},
        credential={
            "kind": "key_vault_secret",
            "secret_uri": "https://ns-kv.vault.usgovcloudapi.net/secrets/producer-key",
        },
    )
    await gov.create(
        CUSTOMER,
        "connector_config",
        body["connector_id"],
        body,
        updated_by=ACTOR.replace("commercial", "government"),
    )
    _use(monkeypatch, gov)
    async with ClientLifetime() as lifetime:
        await f.build_gateway_poll(_cfg(CloudName.GOVERNMENT), lifetime)
    assert Capture.kwargs["metrics_app_id"] is None


async def test_billing_export_in_government_still_fails_with_a_stored_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gov = InMemoryAdminConfigRepository(cloud="government")
    body = billing(manifest_blob="r/manifest.json")
    body["domain_ids"] = ["government:synthco:neurosphere:domain:d1"]
    body["credential"] = {
        "kind": "key_vault_secret",
        "secret_uri": "https://ns-kv.vault.usgovcloudapi.net/secrets/producer-key",
    }
    await gov.create(
        CUSTOMER,
        "connector_config",
        body["connector_id"],
        body,
        updated_by=ACTOR.replace("commercial", "government"),
    )
    _use(monkeypatch, gov)
    async with ClientLifetime() as lifetime:
        with pytest.raises(RoleConfigError) as caught:
            await f.build_billing_export(_cfg(CloudName.GOVERNMENT), lifetime)
    assert caught.value.reason == "billing_export_cloud_unsupported"


async def test_billing_export_runs_from_the_stored_config_with_the_pinned_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, Any] = {}

    def fake_credential(**kwargs: Any) -> object:
        seen["credential"] = kwargs
        return object()

    class _Source:
        def __init__(self, **kwargs: Any) -> None:
            seen["source"] = kwargs

    monkeypatch.setattr(f, "DefaultAzureCredential", fake_credential)
    monkeypatch.setattr(f, "AzureBlobExportSource", _Source)
    monkeypatch.setattr(f, "AzureBillingConnector", Capture)
    monkeypatch.setattr(f, "BillingExportPoller", Capture)
    monkeypatch.setattr(ClientLifetime, "register", lambda self, obj: obj)
    repository = repo()
    await store(
        repository, billing(manifest_blob="r/manifest.json", managed_identity_client_id=CLIENT_ID)
    )
    _use(monkeypatch, repository)
    async with ClientLifetime() as lifetime:
        await f.build_billing_export(_cfg(), lifetime)
    assert seen["credential"]["managed_identity_client_id"] == CLIENT_ID
    assert seen["source"]["container"] == "exports"
    assert Capture.kwargs["ingest"].own["secret"] == SECRET_VALUE
    assert Capture.kwargs["domain_id"] == "commercial:synthco:neurosphere:domain:d1"


async def test_foundry_discovery_runs_from_the_stored_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Reader:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs

    class _Connector:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs

    monkeypatch.setattr(f, "RestProjectReader", _Reader)
    monkeypatch.setattr(f, "FoundryDiscoveryConnector", _Connector)
    monkeypatch.setattr(f, "build_policy_stack", lambda *a, **k: object())
    monkeypatch.setattr(
        f, "build_identity", lambda *a, **k: type("I", (), {"scope_provider": None})()
    )
    monkeypatch.setattr(
        f, "_database", lambda *_: SimpleNamespace(get_container_client=lambda name: object())
    )
    monkeypatch.setattr(f, "CosmosCatalogRepository", lambda *a, **k: object())
    monkeypatch.setattr(f, "FoundryDiscoveryPoller", Capture)
    repository = repo()
    await store(repository, foundry(interval_seconds=120))
    _use(monkeypatch, repository)
    async with ClientLifetime() as lifetime:
        await f.build_foundry_discovery(_cfg(), lifetime)
    assert Capture.kwargs["domain_id"] == "commercial:synthco:neurosphere:domain:d1"
    assert [t.project for t in Capture.kwargs["targets"]] == ["res/proj"]
