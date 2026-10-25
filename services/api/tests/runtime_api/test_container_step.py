"""The ``cosmos_containers`` startup step: create on the local emulator only, verify elsewhere."""

from __future__ import annotations

from typing import Any, Literal

import pytest
from neurosphere_api.runtime import compose as compose_module
from neurosphere_api.runtime.builders import BuildContext, BuilderSpec
from neurosphere_core.cloud import CloudName, Settings
from neurosphere_core.stores import CONTAINERS, TTL_PER_ITEM

from .runtime_helpers import FakeCosmosClient, authz_only, compose


def _patch_factory(monkeypatch: pytest.MonkeyPatch, fake: FakeCosmosClient) -> list[Any]:
    calls: list[Any] = []

    def factory(settings: Settings, **kwargs: Any) -> FakeCosmosClient:
        calls.append((settings.env, kwargs.get("account")))
        return fake

    monkeypatch.setattr(compose_module, "create_cosmos_client", factory)
    return calls


def _start(composed: Any) -> dict[str, str]:
    with composed.client() as client:
        return client.get("/readyz").json()["dependencies"]


def test_local_startup_creates_every_registry_container(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeCosmosClient()
    _patch_factory(monkeypatch, fake)
    monkeypatch.setenv("NS_STORE_DATABASE", "ns_local_db")
    composed = compose(builders=authz_only())
    assert fake.created_databases == []  # nothing happens before the lifespan starts
    deps = _start(composed)
    assert fake.created_databases == ["ns_local_db"]
    created = fake.databases["ns_local_db"].containers
    assert sorted(created) == sorted(spec.name for spec in CONTAINERS)
    assert created["revocations"]["default_ttl"] == TTL_PER_ITEM
    assert "default_ttl" not in created["policy"]
    assert not any(name.startswith("composition.cosmos_containers") for name in deps)


@pytest.mark.parametrize("env", ["dev", "prod"])
def test_outside_local_containers_are_verified_never_created(
    monkeypatch: pytest.MonkeyPatch, env: Literal["dev", "prod"]
) -> None:
    fake = FakeCosmosClient()
    database = fake.get_database_client("neurosphere")
    for spec in CONTAINERS:
        database.containers[spec.name] = {}
    database.missing.add("hitl_items")
    calls = _patch_factory(monkeypatch, fake)
    monkeypatch.setenv("NS_STORE_COSMOS_ACCOUNT", "nsacct")
    composed = compose(
        builders=authz_only(), settings=Settings(env=env, cloud=CloudName.COMMERCIAL)
    )
    deps = _start(composed)
    assert calls == [(env, "nsacct")]
    assert fake.created_databases == []
    assert deps["composition.cosmos_containers.container_missing"] == "unavailable"
    assert composed.registry.get("cosmos_containers").reason == "container_missing"


def test_outside_local_with_every_container_present_passes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeCosmosClient()
    database = fake.get_database_client("neurosphere")
    for spec in CONTAINERS:
        database.containers[spec.name] = {}
    _patch_factory(monkeypatch, fake)
    composed = compose(
        builders=authz_only(), settings=Settings(env="prod", cloud=CloudName.COMMERCIAL)
    )
    deps = _start(composed)
    assert fake.created_databases == []
    assert composed.registry.get("cosmos_containers").state == "ok"
    assert "composition.cosmos_containers.container_missing" not in deps


def test_an_overridden_client_is_neither_provisioned_nor_verified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from neurosphere_api.runtime import CompositionOverrides

    fake = FakeCosmosClient()
    composed = compose(
        CompositionOverrides(cosmos_client_factory=lambda: fake), builders=authz_only()
    )
    _start(composed)
    assert fake.created_databases == []
    assert composed.registry.get("policy_store").state == "ok"


def test_no_cosmos_client_means_no_container_step() -> None:
    composed = compose(builders=authz_only())  # NS_COSMOS_KEY unset -> no client
    deps = _start(composed)
    assert composed.registry.get("cosmos_containers").state == "ok"
    assert deps["composition.policy_store.cosmos_unconfigured"] == "unavailable"


def test_failing_bootstrap_is_reported_by_reason_code(monkeypatch: pytest.MonkeyPatch) -> None:
    class Refused(FakeCosmosClient):
        async def create_database_if_not_exists(self, id: str, **kw: Any) -> Any:
            raise ConnectionRefusedError("localhost:8081")

    _patch_factory(monkeypatch, Refused())
    composed = compose(builders=authz_only())
    deps = _start(composed)
    assert deps["composition.cosmos_containers.connection_refused"] == "unavailable"
    assert "8081" not in str(deps)


def test_startup_and_shutdown_hooks_run_and_a_failing_hook_fails_its_components() -> None:
    events: list[str] = []

    def build(ctx: BuildContext) -> None:
        async def start() -> None:
            events.append("start")
            raise RuntimeError("boom")

        async def stop() -> None:
            events.append("stop")

        ctx.on_startup(start)
        ctx.on_shutdown(stop)
        ctx.ok("catalog")
        ctx.ok("ledger")

    composed = compose(builders=(BuilderSpec("hooks", ("catalog", "ledger"), build),))
    assert composed.registry.get("catalog").state == "ok"
    deps = _start(composed)
    assert events == ["start", "stop"]
    assert deps["composition.catalog.startup_failed"] == "unavailable"
    assert composed.registry.get("ledger").reason == "startup_failed"
