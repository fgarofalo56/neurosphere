"""azure_monitor_ai is part of ``all`` and a safe no-op until configured; settings bounds."""

from __future__ import annotations

import logging

import pytest
from neurosphere_core.clients import ClientLifetime
from neurosphere_core.cloud import Settings
from neurosphere_workers.ingestion.azure_monitor_ai import AzureMonitorAiSettings
from neurosphere_workers.runtime import RoleConfigError, parse_roles
from neurosphere_workers.runtime.adapters import WorkerRole
from neurosphere_workers.runtime.factories import BUILDERS, RuntimeConfig
from neurosphere_workers.runtime.settings import AuthSettings, StoreSettings, WorkerSettings
from pydantic import ValidationError

from .support import DOMAIN, WS1, WS2

_ENV = (
    "NS_AZURE_MONITOR_AI_WORKSPACE_IDS",
    "NS_AZURE_MONITOR_AI_DOMAIN_ID",
    "NS_AZURE_MONITOR_AI_PRODUCER_SECRET",
    "NS_AZURE_MONITOR_AI_API_BASE_URL",
    "NS_API_BASE_URL",
)


def _config() -> RuntimeConfig:
    return RuntimeConfig(Settings(env="local"), WorkerSettings(), StoreSettings(), AuthSettings())


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _ENV:
        monkeypatch.delenv(name, raising=False)


def test_all_includes_the_role() -> None:
    # Membership, not position: later roles (PRP-105 policy_eval) append after this one.
    assert "azure_monitor_ai" in parse_roles("all")


async def test_unconfigured_role_idles_with_one_info_line(
    caplog: pytest.LogCaptureFixture,
) -> None:
    assert "azure_monitor_ai" in parse_roles("all")
    with caplog.at_level(logging.INFO):
        async with ClientLifetime() as lifetime:
            role = await BUILDERS["azure_monitor_ai"](_config(), lifetime)
    assert isinstance(role, WorkerRole)
    events = [getattr(r, "event", None) for r in caplog.records]
    assert events.count("worker.azure_monitor_ai_unconfigured") == 1


@pytest.mark.parametrize(
    ("env", "code"),
    [
        ({"WORKSPACE_IDS": WS1}, "azure_monitor_ai_domain_id_missing"),
        ({"PRODUCER_SECRET": "x"}, "azure_monitor_ai_domain_id_missing"),
        ({"WORKSPACE_IDS": WS1, "DOMAIN_ID": DOMAIN}, "azure_monitor_ai_api_base_url_missing"),
        (
            {"WORKSPACE_IDS": WS1, "DOMAIN_ID": DOMAIN, "API_BASE_URL": "http://127.0.0.1:8000"},
            "azure_monitor_ai_producer_secret_missing",
        ),
        (
            {
                "DOMAIN_ID": DOMAIN,
                "API_BASE_URL": "http://127.0.0.1:8000",
                "PRODUCER_SECRET": "x",
            },
            "azure_monitor_ai_workspace_ids_missing",
        ),
    ],
)
async def test_partial_config_is_refused(
    monkeypatch: pytest.MonkeyPatch, env: dict[str, str], code: str
) -> None:
    for name, value in env.items():
        monkeypatch.setenv(f"NS_AZURE_MONITOR_AI_{name}", value)
    async with ClientLifetime() as lifetime:
        with pytest.raises(RoleConfigError) as caught:
            await BUILDERS["azure_monitor_ai"](_config(), lifetime)
    assert caught.value.reason == code


def test_defaults_match_the_prp() -> None:
    s = AzureMonitorAiSettings()
    assert s.unconfigured and s.workspaces == ()
    assert (s.interval_seconds, s.window_seconds, s.lookback_seconds) == (300, 3600, 86400)
    assert (s.overlap_seconds, s.max_queries_per_tick, s.max_events_per_tick) == (600, 24, 20000)
    assert (s.producer_id, s.source_id, s.batch_size) == ("azure-monitor-ai",) * 2 + (100,)


def test_workspaces_are_lowercased_and_deduplicated() -> None:
    s = AzureMonitorAiSettings(workspace_ids=f"{WS1.replace('1', 'A', 2)}, {WS2} ,{WS2.upper()}")
    assert s.workspaces == (WS1.replace("1", "a", 2), WS2)


@pytest.mark.parametrize(
    "overrides",
    [
        {"workspace_ids": "not-a-guid"},
        {
            "workspace_ids": ",".join(
                str(n) * 8 + "-1111-1111-1111-" + str(n) * 12 for n in range(1, 6)
            )
        },
        {"domain_id": "a,b"},
        {"interval_seconds": 30},
        {"window_seconds": 30},
        {"window_seconds": 86401},
        {"lookback_seconds": 604801},
        {"overlap_seconds": 3600},
        {"max_queries_per_tick": 0},
        {"max_queries_per_tick": 201},
        {"max_events_per_tick": 100001},
        {"batch_size": 501},
        {"managed_identity_client_id": "nope"},
    ],
)
def test_bounds_are_enforced(overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        AzureMonitorAiSettings(**overrides)  # pyright: ignore[reportArgumentType]


def test_setting_names_hold_no_credential_words() -> None:
    names = [n for n in AzureMonitorAiSettings.model_fields if n != "producer_secret"]
    assert not [n for n in names if any(w in n for w in ("key", "token", "secret", "connection"))]
