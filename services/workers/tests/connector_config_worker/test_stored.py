"""PRP-141 item 6: the stored azure_monitor_ai settings (init arguments only, no environment)."""

from __future__ import annotations

import pytest
from neurosphere_contracts.admin.v1.connector_config import ConnectorConfig
from neurosphere_core.cloud import CloudName
from neurosphere_core.errors import InvalidSchemaError
from neurosphere_workers.connector_config import stored
from pydantic import SecretStr

from .support import ENV_NAMES, SECRET_VALUE, WORKSPACE, monitor


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


def _build(**settings: object) -> stored.StoredAzureMonitorAiSettings:
    return stored.build_azure_monitor_ai(ConnectorConfig.model_validate(monitor(**settings)))


def test_allowed_settings_match_the_documented_list() -> None:
    assert stored.ALLOWED_SETTINGS["azure_monitor_ai"] == frozenset(
        {
            "workspace_ids",
            "interval_seconds",
            "window_seconds",
            "lookback_seconds",
            "overlap_seconds",
            "max_queries_per_tick",
            "max_events_per_tick",
            "app_role_names",
            "allow_unverified_government",
            "producer_id",
            "source_id",
            "batch_size",
            "api_base_url",
            "managed_identity_client_id",
        }
    )


def test_stored_values_win_and_environment_does_not_leak(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NS_AZURE_MONITOR_AI_WORKSPACE_IDS", "22222222-2222-4333-8444-555555555555")
    monkeypatch.setenv("NS_AZURE_MONITOR_AI_PRODUCER_SECRET", "env-secret")
    monkeypatch.setenv("NS_API_BASE_URL", "http://env-leak.invalid")
    settings = _build(interval_seconds=600)
    assert settings.workspaces == (WORKSPACE,)
    assert settings.interval_seconds == 600
    assert settings.api_base_url == "http://api.invalid"
    assert settings.producer_secret is None
    with_secret = stored.build_azure_monitor_ai(
        ConnectorConfig.model_validate(monitor()), secret=SecretStr(SECRET_VALUE)
    )
    assert with_secret.producer_secret is not None
    assert with_secret.producer_secret.get_secret_value() == SECRET_VALUE


def test_problem_reports_the_first_refusal() -> None:
    assert stored.azure_monitor_ai_problem(_build(), CloudName.COMMERCIAL) is None
    assert stored.azure_monitor_ai_problem(_build(), CloudName.GOVERNMENT) == (
        "/domain_ids",
        "cloud_mismatch",
    )
    no_api = ConnectorConfig.model_validate(monitor())
    del no_api.settings["api_base_url"]
    problem = stored.azure_monitor_ai_problem(
        stored.build_azure_monitor_ai(no_api), CloudName.COMMERCIAL
    )
    assert problem == ("/settings/api_base_url", "azure_monitor_ai_api_base_url_missing")


def test_unknown_setting_and_two_domains_are_refused() -> None:
    with pytest.raises(InvalidSchemaError) as unknown:
        _build(bogus=1)
    assert unknown.value.reason == "connector_setting_unknown"
    body = monitor()
    body["domain_ids"].append("commercial:synthco:neurosphere:domain:d2")
    with pytest.raises(InvalidSchemaError) as two:
        stored.build_azure_monitor_ai(ConnectorConfig.model_validate(body))
    assert two.value.reason == "azure_monitor_ai_single_domain_required"
