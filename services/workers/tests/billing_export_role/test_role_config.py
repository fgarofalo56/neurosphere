"""billing_export is part of ``all``, idles when unconfigured and refuses half-configuration."""

from __future__ import annotations

import logging
import uuid

import pytest
from neurosphere_core.clients import ClientLifetime
from neurosphere_core.cloud import Settings
from neurosphere_workers.ingestion.billing_export import BillingExportSettings
from neurosphere_workers.runtime import RoleConfigError, parse_roles
from neurosphere_workers.runtime.adapters import WorkerRole
from neurosphere_workers.runtime.factories import BUILDERS, RuntimeConfig, build_billing_export
from neurosphere_workers.runtime.settings import AuthSettings, StoreSettings, WorkerSettings

_ENV = (
    "NS_BILLING_EXPORT_STORAGE_ACCOUNT_URL",
    "NS_BILLING_EXPORT_CONTAINER",
    "NS_BILLING_EXPORT_MANIFEST_BLOB",
    "NS_BILLING_EXPORT_DOMAIN_ID",
    "NS_BILLING_EXPORT_INTERVAL_SECONDS",
    "NS_BILLING_EXPORT_PRODUCER_SECRET",
    "NS_BILLING_EXPORT_API_BASE_URL",
    "NS_API_BASE_URL",
)
_URL = "https://syntheticacct.blob.core.windows.net"
_DOMAIN = "commercial:synthco:neurosphere:domain:d1"


def _config() -> RuntimeConfig:
    return RuntimeConfig(Settings(env="local"), WorkerSettings(), StoreSettings(), AuthSettings())


def _full(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("NS_BILLING_EXPORT_STORAGE_ACCOUNT_URL", _URL)
    monkeypatch.setenv("NS_BILLING_EXPORT_CONTAINER", "exports")
    monkeypatch.setenv("NS_BILLING_EXPORT_MANIFEST_BLOB", "r/manifest.json")
    monkeypatch.setenv("NS_BILLING_EXPORT_DOMAIN_ID", _DOMAIN)
    monkeypatch.setenv("NS_BILLING_EXPORT_PRODUCER_SECRET", "s-" + uuid.uuid4().hex)
    monkeypatch.setenv("NS_API_BASE_URL", "http://api.invalid")


async def _reason(monkeypatch: pytest.MonkeyPatch) -> str:
    async with ClientLifetime() as lifetime:
        with pytest.raises(RoleConfigError) as caught:
            await build_billing_export(_config(), lifetime)
    return caught.value.reason


def test_role_is_in_all_and_registered() -> None:
    assert "billing_export" in parse_roles("all")
    assert BUILDERS["billing_export"] is build_billing_export


async def test_unconfigured_role_idles_with_one_info_log(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    for name in _ENV:
        monkeypatch.delenv(name, raising=False)
    with caplog.at_level(logging.INFO):
        async with ClientLifetime() as lifetime:
            role = await build_billing_export(_config(), lifetime)
    assert isinstance(role, WorkerRole)
    events = [getattr(r, "event", None) for r in caplog.records]
    assert events.count("worker.billing_export_unconfigured") == 1


@pytest.mark.parametrize(
    ("missing", "reason"),
    [
        ("NS_BILLING_EXPORT_STORAGE_ACCOUNT_URL", "billing_export_storage_account_url_missing"),
        ("NS_BILLING_EXPORT_CONTAINER", "billing_export_container_missing"),
        ("NS_BILLING_EXPORT_MANIFEST_BLOB", "billing_export_manifest_blob_missing"),
        ("NS_BILLING_EXPORT_DOMAIN_ID", "billing_export_domain_id_missing"),
        ("NS_BILLING_EXPORT_PRODUCER_SECRET", "billing_export_producer_secret_missing"),
        ("NS_API_BASE_URL", "billing_export_api_base_url_missing"),
    ],
)
async def test_each_missing_setting_is_refused(
    monkeypatch: pytest.MonkeyPatch, missing: str, reason: str
) -> None:
    _full(monkeypatch)
    monkeypatch.delenv(missing)
    assert await _reason(monkeypatch) == reason


async def test_non_canonical_domain_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    _full(monkeypatch)
    monkeypatch.setenv("NS_BILLING_EXPORT_DOMAIN_ID", "d1")
    assert await _reason(monkeypatch) == "billing_export_domain_id_invalid"


@pytest.mark.parametrize(
    "url",
    [
        "http://syntheticacct.blob.core.windows.net",
        "https://evil.example/syntheticacct.blob.core.windows.net",
        "https://syntheticacct.blob.core.usgovcloudapi.net",
        "https://x.syntheticacct.blob.core.windows.net",
        "not a url",
    ],
)
async def test_non_commercial_or_malformed_storage_url_is_refused(
    monkeypatch: pytest.MonkeyPatch, url: str
) -> None:
    _full(monkeypatch)
    monkeypatch.setenv("NS_BILLING_EXPORT_STORAGE_ACCOUNT_URL", url)
    assert await _reason(monkeypatch) == "billing_export_storage_account_url_invalid"


def test_interval_is_bounded_below_one_hour(monkeypatch: pytest.MonkeyPatch) -> None:
    _full(monkeypatch)
    monkeypatch.setenv("NS_BILLING_EXPORT_INTERVAL_SECONDS", "60")
    with pytest.raises(ValueError):
        BillingExportSettings()


def test_secret_is_not_printed(monkeypatch: pytest.MonkeyPatch) -> None:
    _full(monkeypatch)
    settings = BillingExportSettings()
    secret = settings.producer_secret
    assert secret is not None
    assert secret.get_secret_value() not in repr(settings)
