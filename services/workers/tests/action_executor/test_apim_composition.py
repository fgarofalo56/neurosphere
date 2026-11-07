"""PRP-34 audit gap: the production ``actions`` composition uses the publication recorder.

``build_actions`` hands its pieces to ``compose_action_executor``: an APIM gateway connector in the
registry means a ``PublicationRecordingExecutor`` (with a catalog recorder), none means the plain
``ActionExecutor``. A succeeded, verified grant publish through the composed executor reaches the
recorder once and a recorder failure never changes the intent outcome. The APIM connector also
refuses to exist without its observe/manage mode handler (fail closed).
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from neurosphere_connector.write import WriteTargetRegistry
from neurosphere_connector_apim_gateway import ApimGatewayConnector
from neurosphere_core.cloud import Settings
from neurosphere_core.errors import DependencyTransientError
from neurosphere_workers.actions import DEFAULT_ACTION_CONNECTORS, ActionExecutor
from neurosphere_workers.actions.apim import (
    PUBLICATION_RECORD_FAILED,
    PublicationRecordingExecutor,
)
from neurosphere_workers.publication import CatalogPublicationRecorder
from neurosphere_workers.runtime import factories
from neurosphere_workers.runtime.factories import (
    RuntimeConfig,
    _publication_recorder,  # pyright: ignore[reportPrivateUsage]
    compose_action_executor,
)
from neurosphere_workers.runtime.roles import RoleConfigError
from neurosphere_workers.runtime.settings import AuthSettings, StoreSettings, WorkerSettings

from .executor_support import Harness
from .test_apim_publication import (
    FakeRecorder,
    _harness,  # pyright: ignore[reportPrivateUsage]
    grant_world,
    publish_draft,
)


def _options(h: Harness) -> dict[str, Any]:
    return {
        "execution_control": h.control,
        "worker_id": "exec-1",
        "action_connectors": dict(DEFAULT_ACTION_CONNECTORS),
        "clock": h.clock,
    }


async def test_with_an_apim_connector_the_built_executor_records_publications() -> None:
    world = await grant_world()
    h = _harness(world)
    recorder = FakeRecorder()
    executor = compose_action_executor(
        h.service,
        h.registry,
        auditor=h.auditor,
        recorder=recorder,
        gateways=world.store,
        **_options(h),
    )
    assert isinstance(executor, PublicationRecordingExecutor)

    key = await h.executing(await publish_draft(world))
    report = await executor.execute(key)
    assert (report.outcome, report.state) == ("succeeded", "succeeded")
    assert len(recorder.calls) == 1
    assert recorder.calls[0].intent_id == key.intent_id


async def test_a_recorder_failure_through_the_built_executor_keeps_the_outcome() -> None:
    world = await grant_world()
    h = _harness(world)
    recorder = FakeRecorder(DependencyTransientError("down", reason="catalog_store_unavailable"))
    executor = compose_action_executor(
        h.service,
        h.registry,
        auditor=h.auditor,
        recorder=recorder,
        gateways=world.store,
        **_options(h),
    )
    key = await h.executing(await publish_draft(world))
    report = await executor.execute(key)
    assert (report.outcome, report.state) == ("succeeded", "succeeded")
    assert report.reason == PUBLICATION_RECORD_FAILED
    assert len(recorder.calls) == 1
    assert (await h.service.get(key)).state == "succeeded"


async def test_without_an_apim_connector_the_executor_is_plain() -> None:
    h = Harness()
    executor = compose_action_executor(
        h.service, h.registry, auditor=h.auditor, recorder=None, **_options(h)
    )
    assert type(executor) is ActionExecutor


def _cfg(object_id: str | None) -> RuntimeConfig:
    return RuntimeConfig(
        Settings(env="local"),
        WorkerSettings(object_id=object_id),
        StoreSettings(),
        AuthSettings(customer_id="synthco"),  # type: ignore[arg-type]
    )


def test_no_recorder_is_built_when_no_apim_connector_is_registered() -> None:
    audit: Any = object()
    stack: Any = SimpleNamespace(tenant_id="t")
    assert _publication_recorder(_cfg(None), object(), audit, stack, WriteTargetRegistry()) is None  # type: ignore[arg-type]


async def test_a_recorder_is_built_when_the_apim_connector_is_registered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = await grant_world()
    registry = WriteTargetRegistry()
    registry.register(world.connector)
    provider: Any = object()
    seen: dict[str, Any] = {}

    def fake_identity(settings: Settings, **kwargs: Any) -> Any:
        seen.update(kwargs)
        return SimpleNamespace(scope_provider=provider)

    monkeypatch.setattr(factories, "build_identity", fake_identity)
    container = object()
    database = SimpleNamespace(get_container_client=lambda name: container)
    cosmos: Any = SimpleNamespace(get_database_client=lambda name: database)
    audit: Any = object()
    stack: Any = SimpleNamespace(tenant_id="t")

    recorder = _publication_recorder(_cfg("oid"), cosmos, audit, stack, registry)
    assert isinstance(recorder, CatalogPublicationRecorder)
    assert recorder._scope is provider  # pyright: ignore[reportPrivateUsage]
    assert recorder._audit is audit  # pyright: ignore[reportPrivateUsage]
    assert seen["customer_id"] == "synthco"


async def test_a_publishing_worker_without_its_identity_refuses_to_start() -> None:
    world = await grant_world()
    registry = WriteTargetRegistry()
    registry.register(world.connector)
    stack: Any = SimpleNamespace(tenant_id="t")
    with pytest.raises(RoleConfigError):
        _publication_recorder(_cfg(None), object(), object(), stack, registry)  # type: ignore[arg-type]


async def test_the_apim_connector_refuses_to_exist_without_a_mode_handler() -> None:
    world = await grant_world()
    connector = world.connector
    assert isinstance(connector, ApimGatewayConnector)
    with pytest.raises(TypeError):
        ApimGatewayConnector(
            connector.gateway,
            world.apim,
            records=world.records,
            mode=None,  # type: ignore[arg-type]
        )
