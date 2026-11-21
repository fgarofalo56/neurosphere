"""PRP-139 item 3: ``StatusRecordingTick``, the gateway observer and the factory wiring."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

import pytest
from neurosphere_core.clients import ClientLifetime
from neurosphere_core.cloud import Settings
from neurosphere_core.gateway import GatewayRegistration, InMemoryGatewayStore, gateway_id_for
from neurosphere_core.sources_status import (
    ConnectorRunStatus,
    InMemorySourceStatusRepository,
    SourceStatusRepository,
)
from neurosphere_workers.connector_config import ConnectorIdle
from neurosphere_workers.runtime import factories
from neurosphere_workers.runtime.factories import RuntimeConfig
from neurosphere_workers.runtime.settings import AuthSettings, StoreSettings, WorkerSettings
from neurosphere_workers.sources_status import (
    ObservedGatewayStore,
    RunObservation,
    StatusRecordingTick,
    idle_recording,
)

CUSTOMER = "synthco"
NOW = datetime(2026, 11, 21, 10, 0, tzinfo=UTC)


def factory(repo: SourceStatusRepository) -> Callable[[], Awaitable[SourceStatusRepository]]:
    async def build() -> SourceStatusRepository:
        return repo

    return build


def recording(
    repo: SourceStatusRepository,
    tick: Callable[[], Awaitable[None]],
    observation: RunObservation,
    **kwargs: object,
) -> StatusRecordingTick:
    return StatusRecordingTick(
        "foundry_discovery",
        tick,
        lambda: observation,
        factory(repo),
        customer_id=CUSTOMER,
        clock=lambda: NOW,
        **kwargs,  # type: ignore[arg-type]
    )


async def noop() -> None:
    return None


async def test_a_tick_stores_its_observation_with_the_attempt_time() -> None:
    repo = InMemorySourceStatusRepository()
    await recording(repo, noop, RunObservation("ok", None, {"records": 4}))()
    stored = await repo.get(CUSTOMER, "foundry_discovery")
    assert stored is not None
    assert (stored.state, stored.counts, stored.last_attempt_at) == ("ok", {"records": 4}, NOW)
    assert stored.last_success_at == NOW


async def test_a_failed_run_keeps_the_earlier_success_time() -> None:
    repo = InMemorySourceStatusRepository()
    earlier = datetime(2026, 11, 20, tzinfo=UTC)
    await repo.record(
        CUSTOMER,
        ConnectorRunStatus(
            kind="foundry_discovery",
            state="ok",
            last_attempt_at=earlier,
            last_success_at=earlier,
        ),
    )
    await recording(repo, noop, RunObservation("failed", "source_access_denied"))()
    stored = await repo.get(CUSTOMER, "foundry_discovery")
    assert stored is not None and stored.state == "failed"
    assert stored.last_success_at == earlier


async def test_a_store_failure_is_logged_once_and_never_fails_the_tick(
    caplog: pytest.LogCaptureFixture,
) -> None:
    repo = InMemorySourceStatusRepository()
    repo.fail_with(RuntimeError("AccountKey=hunter2"))
    ran: list[int] = []

    async def tick() -> None:
        ran.append(1)

    wrapped = recording(repo, tick, RunObservation("ok"))
    with caplog.at_level(logging.WARNING):
        await wrapped()
        await wrapped()
        await wrapped()
    assert ran == [1, 1, 1]
    events = [getattr(r, "event", None) for r in caplog.records]
    assert events.count("worker.source_status_store_failed") == 1
    assert "hunter2" not in caplog.text


async def test_a_repository_that_cannot_be_built_never_fails_the_tick() -> None:
    async def broken() -> SourceStatusRepository:
        raise RuntimeError("cosmos_key_missing")

    wrapped = StatusRecordingTick(
        "gateway_poll", noop, lambda: RunObservation("ok"), broken, customer_id=CUSTOMER
    )
    await wrapped()


async def test_a_crashing_tick_is_recorded_failed_and_still_raises() -> None:
    repo = InMemorySourceStatusRepository()

    async def boom() -> None:
        raise ValueError("store outage")

    with pytest.raises(ValueError, match="store outage"):
        await recording(repo, boom, RunObservation("ok"))()
    stored = await repo.get(CUSTOMER, "foundry_discovery")
    assert stored is not None
    assert (stored.state, stored.reason) == ("failed", "tick_error")


async def test_the_before_hook_runs_ahead_of_the_tick() -> None:
    order: list[str] = []

    async def tick() -> None:
        order.append("tick")

    wrapped = recording(
        InMemorySourceStatusRepository(),
        tick,
        RunObservation("ok"),
        before=lambda: order.append("before"),
    )
    await wrapped()
    assert order == ["before", "tick"]


async def test_idle_recording_writes_once_then_stays_quiet() -> None:
    repo = InMemorySourceStatusRepository()
    idle = idle_recording("billing_export", object(), factory(repo), customer_id=CUSTOMER)
    await idle()
    first = await repo.get(CUSTOMER, "billing_export")
    assert first is not None
    assert (first.state, first.reason) == ("not_configured", None)
    repo.fail_with(RuntimeError("would be a second write"))
    await idle()
    await idle()


async def test_a_disabled_stored_config_is_idle_not_not_configured() -> None:
    repo = InMemorySourceStatusRepository()
    resolved = ConnectorIdle("gateway_poll", "disabled")
    await idle_recording("gateway_poll", resolved, factory(repo), customer_id=CUSTOMER)()
    stored = await repo.get(CUSTOMER, "gateway_poll")
    assert stored is not None and (stored.state, stored.reason) == ("idle", "disabled")
    other = InMemorySourceStatusRepository()
    missing = ConnectorIdle("gateway_poll", "no_stored_config")
    await idle_recording("gateway_poll", missing, factory(other), customer_id=CUSTOMER)()
    stored = await other.get(CUSTOMER, "gateway_poll")
    assert stored is not None and stored.state == "not_configured"


async def test_a_failing_idle_write_is_retried_until_it_lands() -> None:
    repo = InMemorySourceStatusRepository()
    repo.fail_with(RuntimeError("down"))
    idle = idle_recording("billing_export", None, factory(repo), customer_id=CUSTOMER)
    await idle()
    repo.fail_with(None)
    assert await repo.list(CUSTOMER) == []
    await idle()
    assert len(await repo.list(CUSTOMER)) == 1


async def test_the_gateway_observer_delegates_and_reports_replaced_statuses() -> None:
    arm_id = (
        "/subscriptions/22222222-2222-2222-2222-222222222222/resourceGroups/rg-demo"
        "/providers/Microsoft.ApiManagement/service/apim-demo"
    )
    created = await InMemoryGatewayStore().create(
        GatewayRegistration(
            id=gateway_id_for(CUSTOMER, "dom-1", arm_id),
            customer_id=CUSTOMER,
            domain_id="dom-1",
            cloud="commercial",
            arm_resource_id=arm_id,
            name="apim-demo",
            tier="standard_v2",
            workspace_id=None,
            created_at=NOW,
            updated_at=NOW,
            registered_by="operator-1",
        )
    )
    inner = InMemoryGatewayStore()
    observed = ObservedGatewayStore(inner)
    stored = await observed.create(created)
    assert observed.drain() == []
    assert etag_of(stored) is not None
    updated = stored.model_copy(update={"poll_status": "poll_failed:forbidden"})
    await observed.replace(updated, if_match=etag_of(stored) or "")
    assert observed.drain() == ["poll_failed:forbidden"]
    assert observed.drain() == []
    found = await observed.get(CUSTOMER, "dom-1", stored.id)
    assert found is not None and found.poll_status == "poll_failed:forbidden"


def etag_of(registration: GatewayRegistration) -> str | None:
    return registration.etag


# -- factory wiring ---------------------------------------------------------------------------


def _config() -> RuntimeConfig:
    return RuntimeConfig(Settings(env="local"), WorkerSettings(), StoreSettings(), AuthSettings())


@pytest.mark.parametrize(
    ("builder", "kind", "env"),
    [
        ("build_gateway_poll", "gateway_poll", "NS_GATEWAY_POLL_DOMAIN_IDS"),
        ("build_foundry_discovery", "foundry_discovery", "NS_FOUNDRY_DISCOVERY_PROJECTS"),
        ("build_billing_export", "billing_export", "NS_BILLING_EXPORT_CONTAINER"),
    ],
)
async def test_each_idle_role_records_not_configured_once(
    monkeypatch: pytest.MonkeyPatch, builder: str, kind: str, env: str
) -> None:
    repo = InMemorySourceStatusRepository()
    monkeypatch.delenv(env, raising=False)
    monkeypatch.setattr(factories, "cosmos_repository", lambda *a, **k: factory(repo))
    monkeypatch.setattr(factories, "_tick_role", lambda name, tick, cfg: tick)
    async with ClientLifetime() as lifetime:
        tick = await getattr(factories, builder)(_config(), lifetime)
    await tick()
    stored = await repo.get("synthco", kind)
    assert stored is not None and stored.state == "not_configured"
