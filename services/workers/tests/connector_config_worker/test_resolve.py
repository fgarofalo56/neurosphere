"""PRP-42 item 2: stored wins per kind, env fallback, idle markers, credential failures."""

from __future__ import annotations

import pytest
from neurosphere_core.clients import ClientLifetime
from neurosphere_core.cloud import CloudName, Settings
from neurosphere_workers.connector_config import (
    ConnectorCredentialUnavailableError,
    ConnectorIdle,
    resolve,
    resolve_azure_monitor_ai_settings,
    resolve_billing_export_settings,
    resolve_foundry_discovery_settings,
    resolve_gateway_poll_settings,
)
from neurosphere_workers.runtime import RoleConfigError
from neurosphere_workers.runtime.factories import RuntimeConfig
from neurosphere_workers.runtime.settings import AuthSettings, StoreSettings, WorkerSettings

from .support import (
    CLIENT_ID,
    ENV_NAMES,
    SECRET_VALUE,
    FakeReader,
    billing,
    config,
    foundry,
    gateway,
    monitor,
    repo,
    runtime_config,
    store,
)


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


def _reader(monkeypatch: pytest.MonkeyPatch, reader: FakeReader) -> FakeReader:
    monkeypatch.setattr(resolve, "build_reader", lambda cloud, *, client_id, timeout: reader)
    return reader


async def test_no_record_returns_the_env_built_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NS_GATEWAY_POLL_DOMAIN_IDS", "d1,d2")
    async with ClientLifetime() as lifetime:
        settings = await resolve_gateway_poll_settings(
            runtime_config(), lifetime, repository=repo()
        )
    assert not isinstance(settings, ConnectorIdle)
    assert settings.domains == ("d1", "d2")


async def test_stored_gateway_config_beats_env_and_env_api_base_url_does_not_leak(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NS_GATEWAY_POLL_DOMAIN_IDS", "env-domain")
    monkeypatch.setenv("NS_GATEWAY_POLL_INTERVAL_SECONDS", "77")
    monkeypatch.setenv("NS_API_BASE_URL", "http://env-leak.invalid")
    monkeypatch.setenv("NS_GATEWAY_POLL_PRODUCER_SECRET", "env-secret")
    reader = _reader(monkeypatch, FakeReader())
    repository = repo()
    body = config("gateway_poll", settings={"interval_seconds": 600})
    await store(repository, body)
    async with ClientLifetime() as lifetime:
        settings = await resolve_gateway_poll_settings(
            runtime_config(), lifetime, repository=repository
        )
    assert not isinstance(settings, ConnectorIdle)
    assert settings.domains == (body["domain_ids"][0],)
    assert settings.interval_seconds == 600
    assert settings.api_base_url is None  # env NS_API_BASE_URL did not leak in
    assert settings.producer_secret is not None
    assert settings.producer_secret.get_secret_value() == SECRET_VALUE  # not the env secret
    assert reader.calls == 1


async def test_stored_billing_config_reads_secret_and_carries_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NS_BILLING_EXPORT_CONTAINER", "env-container")
    _reader(monkeypatch, FakeReader())
    repository = repo()
    await store(repository, billing(managed_identity_client_id=CLIENT_ID))
    async with ClientLifetime() as lifetime:
        settings = await resolve_billing_export_settings(
            runtime_config(), lifetime, repository=repository
        )
    assert not isinstance(settings, ConnectorIdle)
    assert settings.container == "exports"
    assert settings.domain_id is not None and settings.storage_url_valid
    assert settings.managed_identity_client_id == CLIENT_ID  # type: ignore[attr-defined]


async def test_stored_foundry_config_builds_projects_without_secret() -> None:
    repository = repo()
    await store(repository, foundry())
    async with ClientLifetime() as lifetime:
        settings = await resolve_foundry_discovery_settings(
            runtime_config(), lifetime, repository=repository
        )
    assert not isinstance(settings, ConnectorIdle)
    assert settings.parse_projects() == (("res", "proj"),)
    assert settings.domain_id_valid


async def test_disabled_config_idles_and_does_not_fall_back_to_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NS_GATEWAY_POLL_DOMAIN_IDS", "env-domain")
    repository = repo()
    await store(
        repository,
        config("gateway_poll", enabled=False, settings={"api_base_url": "http://x.invalid"}),
    )
    async with ClientLifetime() as lifetime:
        marker = await resolve_gateway_poll_settings(
            runtime_config(), lifetime, repository=repository
        )
    assert isinstance(marker, ConnectorIdle) and marker.reason == "disabled"


async def test_env_source_ignores_the_store(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NS_WORKER_CONNECTOR_CONFIG_SOURCE", "env")
    monkeypatch.setenv("NS_GATEWAY_POLL_DOMAIN_IDS", "env-domain")
    repository = repo()
    await store(repository, gateway())
    async with ClientLifetime() as lifetime:
        settings = await resolve_gateway_poll_settings(
            runtime_config(), lifetime, repository=repository
        )
    assert not isinstance(settings, ConnectorIdle) and settings.domains == ("env-domain",)


async def test_store_source_without_record_idles(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NS_WORKER_CONNECTOR_CONFIG_SOURCE", "store")
    async with ClientLifetime() as lifetime:
        marker = await resolve_foundry_discovery_settings(
            runtime_config(), lifetime, repository=repo()
        )
    assert isinstance(marker, ConnectorIdle)


async def test_store_failure_falls_back_to_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NS_GATEWAY_POLL_DOMAIN_IDS", "env-domain")
    repository = repo()
    repository.fail_with(RuntimeError("down"))
    async with ClientLifetime() as lifetime:
        settings = await resolve_gateway_poll_settings(
            runtime_config(), lifetime, repository=repository
        )
    assert not isinstance(settings, ConnectorIdle) and settings.domains == ("env-domain",)


async def test_unopenable_store_falls_back_to_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NS_GATEWAY_POLL_DOMAIN_IDS", "env-domain")
    monkeypatch.delenv("NS_COSMOS_KEY", raising=False)
    async with ClientLifetime() as lifetime:
        settings = await resolve_gateway_poll_settings(runtime_config(), lifetime)
    assert not isinstance(settings, ConnectorIdle) and settings.domains == ("env-domain",)


async def test_vault_failure_is_connector_credential_unavailable_without_uri(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reader(monkeypatch, FakeReader(ConnectorCredentialUnavailableError()))
    repository = repo()
    await store(repository, gateway())
    async with ClientLifetime() as lifetime:
        with pytest.raises(RoleConfigError) as caught:
            await resolve_gateway_poll_settings(runtime_config(), lifetime, repository=repository)
    assert caught.value.reason == "connector_credential_unavailable"
    assert "vault" not in str(caught.value)


async def test_stored_azure_monitor_ai_config_reads_secret_and_ignores_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NS_AZURE_MONITOR_AI_WORKSPACE_IDS", "22222222-2222-4333-8444-555555555555")
    monkeypatch.setenv("NS_AZURE_MONITOR_AI_PRODUCER_SECRET", "env-secret")
    reader = _reader(monkeypatch, FakeReader())
    repository = repo()
    await store(repository, monitor(interval_seconds=600))
    async with ClientLifetime() as lifetime:
        settings = await resolve_azure_monitor_ai_settings(
            runtime_config(), lifetime, repository=repository
        )
    assert not isinstance(settings, ConnectorIdle)
    assert settings.interval_seconds == 600
    assert settings.workspaces == ("11111111-2222-4333-8444-555555555555",)
    assert settings.producer_secret is not None
    assert settings.producer_secret.get_secret_value() == SECRET_VALUE
    assert reader.calls == 1


async def test_disabled_azure_monitor_ai_config_idles_without_env_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NS_AZURE_MONITOR_AI_WORKSPACE_IDS", "22222222-2222-4333-8444-555555555555")
    repository = repo()
    body = monitor()
    body["enabled"] = False
    await store(repository, body)
    async with ClientLifetime() as lifetime:
        marker = await resolve_azure_monitor_ai_settings(
            runtime_config(), lifetime, repository=repository
        )
    assert isinstance(marker, ConnectorIdle) and marker.reason == "disabled"


async def test_azure_monitor_ai_without_record_uses_env_and_store_source_idles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with ClientLifetime() as lifetime:
        settings = await resolve_azure_monitor_ai_settings(
            runtime_config(), lifetime, repository=repo()
        )
    assert not isinstance(settings, ConnectorIdle) and settings.unconfigured
    monkeypatch.setenv("NS_WORKER_CONNECTOR_CONFIG_SOURCE", "store")
    async with ClientLifetime() as lifetime:
        marker = await resolve_azure_monitor_ai_settings(
            runtime_config(), lifetime, repository=repo()
        )
    assert isinstance(marker, ConnectorIdle) and marker.reason == "no_stored_config"


async def test_azure_monitor_ai_cloud_mismatch_and_vault_failure_fail_the_role(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = repo()
    await store(repository, monitor())
    _reader(monkeypatch, FakeReader(ConnectorCredentialUnavailableError()))
    async with ClientLifetime() as lifetime:
        with pytest.raises(RoleConfigError) as vault:
            await resolve_azure_monitor_ai_settings(
                runtime_config(), lifetime, repository=repository
            )
    assert vault.value.reason == "connector_credential_unavailable"
    gov = RuntimeConfig(
        Settings(env="local", cloud=CloudName.GOVERNMENT),
        WorkerSettings(),
        StoreSettings(),
        AuthSettings(),
    )
    async with ClientLifetime() as lifetime:
        with pytest.raises(RoleConfigError) as mismatch:
            await resolve_azure_monitor_ai_settings(gov, lifetime, repository=repository)
    assert mismatch.value.reason == "cloud_mismatch"
