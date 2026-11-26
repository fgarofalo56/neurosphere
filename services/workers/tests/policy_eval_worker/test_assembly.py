"""PRP-105 item 5: the ``policy_eval`` builder, its settings and the two binding points."""

from __future__ import annotations

import os
from typing import Any
from unittest.mock import MagicMock

import pytest
from neurosphere_core.clients import ClientLifetime
from neurosphere_core.cloud import Settings
from neurosphere_core.governance.policy import NoopViolationEventSink
from neurosphere_workers.policy_eval import assembly
from neurosphere_workers.policy_eval.assembly import (
    build_policy_eval,
    interaction_finding_reader,
    violation_event_sink,
)
from neurosphere_workers.policy_eval.settings import (
    KNOWN_SETTINGS,
    SETTING_INVALID,
    SETTING_UNKNOWN,
    load_policy_eval_settings,
)
from neurosphere_workers.runtime import RoleConfigError, parse_roles
from neurosphere_workers.runtime.adapters import WorkerRole
from neurosphere_workers.runtime.factories import BUILDERS, RuntimeConfig
from neurosphere_workers.runtime.settings import AuthSettings, StoreSettings, WorkerSettings

TENANT = "11111111-2222-4333-8444-555555555555"
OBJECT_ID = "66666666-7777-4888-9999-aaaaaaaaaaaa"


def _config(*, object_id: str | None = OBJECT_ID) -> RuntimeConfig:
    return RuntimeConfig(
        Settings(env="local"),
        WorkerSettings(tenant_id=TENANT, object_id=object_id),  # type: ignore[call-arg]
        StoreSettings(),
        AuthSettings(customer_id="synthco"),  # type: ignore[arg-type]
    )


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:

    for name in list(os.environ):
        if name.upper().startswith("NS_POLICY_EVAL_"):
            monkeypatch.delenv(name, raising=False)


@pytest.fixture
def fake_cosmos(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """No emulator: the builder gets a mock client (nothing is read at build time)."""
    client = MagicMock()

    async def cosmos(cfg: Any, lifetime: ClientLifetime) -> MagicMock:
        return client

    monkeypatch.setattr(assembly, "_cosmos_client", cosmos)
    return client


def test_role_is_registered_and_in_all() -> None:
    assert BUILDERS["policy_eval"] is build_policy_eval
    assert "policy_eval" in parse_roles("all")
    assert parse_roles("policy_eval") == ("policy_eval",)


def test_settings_defaults() -> None:
    settings = load_policy_eval_settings()
    assert settings.interval_seconds == 300
    assert settings.subject_budget == 5000
    assert settings.time_budget_seconds == 120
    assert KNOWN_SETTINGS == {
        "NS_POLICY_EVAL_INTERVAL_SECONDS",
        "NS_POLICY_EVAL_SUBJECT_BUDGET",
        "NS_POLICY_EVAL_TIME_BUDGET_SECONDS",
    }


def test_settings_read_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NS_POLICY_EVAL_INTERVAL_SECONDS", "600")
    monkeypatch.setenv("NS_POLICY_EVAL_SUBJECT_BUDGET", "250")
    monkeypatch.setenv("NS_POLICY_EVAL_TIME_BUDGET_SECONDS", "30")
    settings = load_policy_eval_settings()
    assert (settings.interval_seconds, settings.subject_budget) == (600, 250)
    assert settings.time_budget_seconds == 30


def test_settings_from_a_mapping() -> None:
    settings = load_policy_eval_settings({"NS_POLICY_EVAL_SUBJECT_BUDGET": "10", "OTHER": "x"})
    assert settings.subject_budget == 10
    with pytest.raises(RoleConfigError) as caught:
        load_policy_eval_settings({"NS_POLICY_EVAL_BUDGET": "10"})
    assert caught.value.reason == SETTING_UNKNOWN


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("NS_POLICY_EVAL_INTERVAL_SECONDS", "soon"),
        ("NS_POLICY_EVAL_INTERVAL_SECONDS", "5"),
        ("NS_POLICY_EVAL_SUBJECT_BUDGET", "0"),
        ("NS_POLICY_EVAL_TIME_BUDGET_SECONDS", "-1"),
    ],
)
async def test_invalid_setting_refuses_to_start(
    monkeypatch: pytest.MonkeyPatch, fake_cosmos: MagicMock, name: str, value: str
) -> None:
    monkeypatch.setenv(name, value)
    async with ClientLifetime() as lifetime:
        with pytest.raises(RoleConfigError) as caught:
            await build_policy_eval(_config(), lifetime)
    assert caught.value.reason == SETTING_INVALID


async def test_unknown_setting_refuses_to_start(
    monkeypatch: pytest.MonkeyPatch, fake_cosmos: MagicMock
) -> None:
    monkeypatch.setenv("NS_POLICY_EVAL_INTERVAL", "300")  # typo of ..._INTERVAL_SECONDS
    async with ClientLifetime() as lifetime:
        with pytest.raises(RoleConfigError) as caught:
            await build_policy_eval(_config(), lifetime)
    assert caught.value.reason == SETTING_UNKNOWN
    fake_cosmos.get_database_client.assert_not_called()  # refused before any client use


async def test_builds_a_tick_role_over_cosmos(fake_cosmos: MagicMock) -> None:
    async with ClientLifetime() as lifetime:
        role = await build_policy_eval(_config(), lifetime)
    assert isinstance(role, WorkerRole)
    containers = {
        call.args[0]
        for call in fake_cosmos.get_database_client.return_value.get_container_client.mock_calls
        if call.args
    }
    assert {
        "policy_definitions",
        "policy_violations",
        "policy_exceptions",
        "catalog",
        "aggregates",
    } <= containers


async def test_the_worker_needs_its_own_identity(fake_cosmos: MagicMock) -> None:
    async with ClientLifetime() as lifetime:
        with pytest.raises(RoleConfigError) as caught:
            await build_policy_eval(_config(object_id=None), lifetime)
    assert caught.value.reason == "worker_object_id_missing"


async def test_binding_points_are_unbound_in_this_prp() -> None:
    async with ClientLifetime() as lifetime:
        sink = violation_event_sink(_config(), lifetime)
        reader = interaction_finding_reader(_config(), lifetime)
    assert isinstance(sink, NoopViolationEventSink)
    assert reader is None
