"""The ``actions`` role wires the deploy connector with durable approvals and provisioners
(PRP-55 item 4, criteria 3 and 5). No network: the Cosmos client is a stand-in that only hands
out container proxies, and no request is made while composing."""

from __future__ import annotations

import logging
from typing import Any

import pytest
from neurosphere_connector.write import WriteTargetRegistry
from neurosphere_core.clients import ClientLifetime
from neurosphere_core.cloud import CloudName, Settings
from neurosphere_core.deploy.register import CustomerScopedRegister
from neurosphere_core.deploy.register.cosmos_store import CosmosRegisterStore
from neurosphere_workers.actions.deploy import DeployConnector
from neurosphere_workers.actions.deploy_approvals import RepositoryPlanApprovals
from neurosphere_workers.actions.deploy_arm import HttpArmProvisioner
from neurosphere_workers.actions.deploy_wiring import (
    build_deploy_collaborators,
    worker_fabric_endpoints,
)
from neurosphere_workers.runtime import factories
from neurosphere_workers.runtime.factories import (
    DeployWriteSettings,
    RuntimeConfig,
    load_deploy_write_settings,
)
from neurosphere_workers.runtime.settings import AuthSettings, StoreSettings, WorkerSettings

ENV = ("NS_DEPLOY_APPLY_ENABLED", "NS_DEPLOY_APPLY_REGISTER_CONTAINER")


class _Database:
    def __init__(self, name: str, opened: list[tuple[str, str]]) -> None:
        self._name = name
        self._opened = opened

    def get_container_client(self, container: str) -> object:
        self._opened.append((self._name, container))
        return object()


class FakeCosmos:
    """Hands out container proxies only; any I/O would fail loudly."""

    def __init__(self) -> None:
        self.opened: list[tuple[str, str]] = []

    def get_database_client(self, database: str) -> _Database:
        return _Database(database, self.opened)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ENV:
        monkeypatch.delenv(name, raising=False)


def _cfg(cloud: CloudName = CloudName.COMMERCIAL) -> RuntimeConfig:
    return RuntimeConfig(
        Settings(env="local", cloud=cloud),
        WorkerSettings(),
        StoreSettings(),
        AuthSettings(customer_id="synthco"),  # type: ignore[arg-type]
    )


async def _compose(
    cfg: RuntimeConfig, cosmos: FakeCosmos
) -> tuple[WriteTargetRegistry, ClientLifetime]:
    lifetime = ClientLifetime()
    registry, _ = await factories._action_write_targets(  # pyright: ignore[reportPrivateUsage]
        cfg,
        lifetime,
        cosmos,  # type: ignore[arg-type]
    )
    return registry, lifetime


def test_the_worker_reads_the_same_register_container_setting_as_the_api(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert load_deploy_write_settings() == DeployWriteSettings()
    monkeypatch.setenv("NS_DEPLOY_APPLY_ENABLED", "true")
    monkeypatch.setenv("NS_DEPLOY_APPLY_REGISTER_CONTAINER", "deploy_register")
    loaded = load_deploy_write_settings()
    assert loaded.enabled is True and loaded.register_container == "deploy_register"
    monkeypatch.setenv("NS_DEPLOY_APPLY_REGISTER_CONTAINER", "")
    with pytest.raises(ValueError):
        load_deploy_write_settings()


async def test_unset_keeps_deploy_unregistered() -> None:
    cosmos = FakeCosmos()
    registry, lifetime = await _compose(_cfg(), cosmos)
    await lifetime.aclose()
    assert "deploy-orchestrator" not in registry.names()
    assert cosmos.opened == []


async def test_enabled_without_a_register_container_is_skipped(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("NS_DEPLOY_APPLY_ENABLED", "true")
    with caplog.at_level(logging.INFO):
        registry, lifetime = await _compose(_cfg(), FakeCosmos())
    await lifetime.aclose()
    assert "deploy-orchestrator" not in registry.names()
    assert "deploy_sources_unconfigured" in caplog.text


async def test_enabled_and_configured_registers_the_wired_connector(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NS_DEPLOY_APPLY_ENABLED", "true")
    monkeypatch.setenv("NS_DEPLOY_APPLY_REGISTER_CONTAINER", "deploy_register")
    cosmos = FakeCosmos()
    registry, lifetime = await _compose(_cfg(), cosmos)
    try:
        assert "deploy-orchestrator" in registry.names()
        connector = registry.get("deploy-orchestrator")
        assert isinstance(connector, DeployConnector) and connector.advisory is False
        inner: Any = connector
        assert inner._customer_id == "synthco"
        assert isinstance(inner._approvals, RepositoryPlanApprovals)
        assert isinstance(inner._register, CustomerScopedRegister)
        assert isinstance(inner._arm, HttpArmProvisioner)
        assert inner._fabric is not None and inner._observer is not None
        assert set(cosmos.opened) == {
            ("neurosphere", "deploy_plan_approvals"),
            ("neurosphere", "deploy_register"),
        }
    finally:
        await lifetime.aclose()


async def test_government_keeps_fabric_unwired(monkeypatch: pytest.MonkeyPatch) -> None:
    """Decision 5: no verified Government Fabric token scope (#39), so no Fabric collaborators;
    Fabric items stay capability_unavailable while ARM items use the Government host."""
    assert worker_fabric_endpoints(CloudName.GOVERNMENT) is None
    monkeypatch.setenv("NS_DEPLOY_APPLY_ENABLED", "true")
    monkeypatch.setenv("NS_DEPLOY_APPLY_REGISTER_CONTAINER", "deploy_register")
    registry, lifetime = await _compose(_cfg(CloudName.GOVERNMENT), FakeCosmos())
    try:
        inner: Any = registry.get("deploy-orchestrator")
        assert inner._fabric is None and inner._observer is None
        assert isinstance(inner._arm, HttpArmProvisioner)
        assert inner._arm._host == "management.usgovcloudapi.net"
    finally:
        await lifetime.aclose()


def test_collaborators_use_the_registry_container_and_the_given_register() -> None:
    import httpx

    cosmos = FakeCosmos()
    built = build_deploy_collaborators(
        profile=Settings(env="local").cloud_profile,
        cosmos=cosmos,  # type: ignore[arg-type]
        database="db",
        register_container="reg",
        http_client=httpx.AsyncClient(),
        credential=lambda: (_ for _ in ()).throw(AssertionError("no credential while composing")),
    )
    assert isinstance(built.register, CosmosRegisterStore)
    assert isinstance(built.approvals, RepositoryPlanApprovals)
    assert cosmos.opened == [("db", "deploy_plan_approvals"), ("db", "reg")]
