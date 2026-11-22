"""Shared fixtures for the connector_config worker tests (synthetic data, no network)."""

from __future__ import annotations

from typing import Any

from neurosphere_core.admin import InMemoryAdminConfigRepository
from neurosphere_core.cloud import Settings
from neurosphere_workers.runtime.factories import RuntimeConfig
from neurosphere_workers.runtime.settings import AuthSettings, StoreSettings, WorkerSettings
from pydantic import SecretStr

CUSTOMER = "synthco"
ACTOR = "commercial:synthco:entra:person:p-" + "0c" * 32
DOMAIN = "commercial:synthco:neurosphere:domain:d1"
VAULT_URI = "https://ns-kv.vault.azure.net/secrets/producer-key"
SECRET_VALUE = "stored-secret-value-9f3a"  # noqa: S105
CLIENT_ID = "6c1d2e3f-4a5b-4c6d-8e7f-90a1b2c3d4e5"
KEY_VAULT = {"kind": "key_vault_secret", "secret_uri": VAULT_URI}
IDENTITY = {"kind": "managed_identity", "managed_identity_client_id": CLIENT_ID}

ENV_NAMES = (
    "NS_GATEWAY_POLL_DOMAIN_IDS",
    "NS_GATEWAY_POLL_PRODUCER_SECRET",
    "NS_GATEWAY_POLL_API_BASE_URL",
    "NS_GATEWAY_POLL_INTERVAL_SECONDS",
    "NS_API_BASE_URL",
    "NS_FOUNDRY_DISCOVERY_PROJECTS",
    "NS_FOUNDRY_DISCOVERY_DOMAIN_ID",
    "NS_BILLING_EXPORT_STORAGE_ACCOUNT_URL",
    "NS_BILLING_EXPORT_CONTAINER",
    "NS_BILLING_EXPORT_MANIFEST_BLOB",
    "NS_BILLING_EXPORT_DOMAIN_ID",
    "NS_BILLING_EXPORT_PRODUCER_SECRET",
    "NS_BILLING_EXPORT_API_BASE_URL",
    "NS_AZURE_MONITOR_AI_WORKSPACE_IDS",
    "NS_AZURE_MONITOR_AI_DOMAIN_ID",
    "NS_AZURE_MONITOR_AI_PRODUCER_SECRET",
    "NS_AZURE_MONITOR_AI_API_BASE_URL",
    "NS_WORKER_CONNECTOR_CONFIG_SOURCE",
    "NS_WORKER_CONNECTOR_CONFIG_TIMEOUT_SECONDS",
)


def runtime_config() -> RuntimeConfig:
    return RuntimeConfig(Settings(env="local"), WorkerSettings(), StoreSettings(), AuthSettings())


def repo() -> InMemoryAdminConfigRepository:
    return InMemoryAdminConfigRepository(cloud="commercial")


def config(kind: str, **over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "schema_version": "1.0.0",
        "connector_id": f"{kind.replace('_', '-')}-main",
        "connector_kind": kind,
        "domain_ids": [DOMAIN],
        "settings": {},
        "credential": KEY_VAULT,
        "enabled": True,
    }
    base.update(over)
    return base


def gateway(**settings: Any) -> dict[str, Any]:
    merged = {"api_base_url": "http://api.invalid", **settings}
    return config("gateway_poll", settings=merged)


def billing(**settings: Any) -> dict[str, Any]:
    merged = {
        "storage_account_url": "https://syntheticacct.blob.core.windows.net",
        "container": "exports",
        "manifest_blob": "r/manifest.json",
        "api_base_url": "http://api.invalid",
        **settings,
    }
    return config("billing_export", settings=merged)


WORKSPACE = "11111111-2222-4333-8444-555555555555"


def monitor(**settings: Any) -> dict[str, Any]:
    merged = {"workspace_ids": WORKSPACE, "api_base_url": "http://api.invalid", **settings}
    return config("azure_monitor_ai", settings=merged)


def foundry(**settings: Any) -> dict[str, Any]:
    merged = {"projects": "res/proj", **settings}
    return config("foundry_discovery", settings=merged, credential=IDENTITY)


async def store(repository: InMemoryAdminConfigRepository, body: dict[str, Any]) -> None:
    await repository.create(
        CUSTOMER, "connector_config", body["connector_id"], body, updated_by=ACTOR
    )


class FakeReader:
    """Stands in for the Key Vault reader; records how it was built and called."""

    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls = 0

    async def read(self, reference: Any) -> SecretStr:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return SecretStr(SECRET_VALUE)
