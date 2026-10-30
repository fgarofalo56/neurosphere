"""Worker wiring of the APIM gateway connector (PRP-34 item 3, item 2 review hand-offs).

Target-kind routing (Foundry targets keep Foundry), the gateway-domain binding check, the
always-wired observe guard, Government -> advisory, and a rollback that reads as busy.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest
from neurosphere_connector.write import WriteTargetRegistry
from neurosphere_connector_apim_gateway import (
    ApimGatewayAdvisoryConnector,
    ApimGatewayConnector,
    ApplyRecord,
    InMemoryApim,
)
from neurosphere_core.errors import CapabilityUnavailableError, DependencyTransientError
from neurosphere_core.gateway import InMemoryGatewayRecordStore, InMemoryGatewayStore
from neurosphere_core.gateway.mode import (
    GATEWAY_APPLYING,
    GATEWAY_OBSERVE_MODE,
    GatewayModeSwitch,
    ModeChange,
    mode_target_version,
)
from neurosphere_workers.actions import DEFAULT_ACTION_CONNECTORS, resolve_connector
from neurosphere_workers.actions.apim import build_apim_gateway_connector

from .apim_support import (
    GW,
    NEW_URL,
    POOL,
    SINGLE,
    ApimWorld,
    apim_world,
    registration,
    reviewed_draft,
    swap_request,
)
from .executor_support import CUSTOMER, DOMAIN, START, CountingConnector, Harness, draft_request

TABLE = dict(DEFAULT_ACTION_CONNECTORS)


def _harness(world: ApimWorld, foundry: CountingConnector | None = None) -> Harness:
    h = Harness(connector=foundry or CountingConnector("foundry-model-swap"))
    h.registry.register(world.connector)
    return h


# -- routing --------------------------------------------------------------------------------------


async def test_resolution_routes_by_target_kind() -> None:
    world = await apim_world()
    foundry = CountingConnector("foundry-model-swap")
    registry = WriteTargetRegistry()
    registry.register(foundry)
    registry.register(world.connector)
    assert resolve_connector(registry, TABLE, "model_deployment_swap", "model_deployment") is (
        foundry
    )
    assert resolve_connector(registry, TABLE, "model_deployment_swap") is foundry
    assert (
        resolve_connector(registry, TABLE, "model_deployment_swap", "apim_backend")
        is world.connector
    )
    assert resolve_connector(registry, TABLE, "gateway_mode_change", "apim_gateway_mode") is (
        world.connector
    )
    with pytest.raises(CapabilityUnavailableError):
        resolve_connector(registry, TABLE, "model_deployment_scale", "apim_backend")


async def test_foundry_swaps_still_reach_foundry_and_backend_swaps_reach_apim() -> None:
    world = await apim_world(backends={"foundry": SINGLE})
    h = _harness(world)
    executor = h.executor(table=TABLE, gateways=world.store)
    foundry_key = await h.executing(draft_request(key="idem-foundry-swap-0001"))
    assert (await executor.execute(foundry_key)).outcome == "succeeded"
    assert h.connector.count("apply") == 1
    assert world.apim.writes() == []
    apim_key = await h.executing(
        await reviewed_draft(world, swap_request(world, "foundry", url=NEW_URL))
    )
    assert (await executor.execute(apim_key)).outcome == "succeeded"
    assert h.connector.count("apply") == 1  # unchanged: the backend swap went to APIM
    assert world.apim.snapshot()["backends/foundry"]["url"] == NEW_URL


# -- gateway binding (item 2 hand-off 1) ----------------------------------------------------------


async def test_a_gateway_registered_in_another_domain_is_refused_before_any_call() -> None:
    world = await apim_world()
    other = InMemoryGatewayStore()
    await other.create(registration(domain="commercial:contoso:catalog:domain:finance"))
    h = _harness(world)
    key = await h.executing(await reviewed_draft(world, swap_request(world)))
    report = await h.executor(table=TABLE, gateways=other).execute(key)
    assert (report.outcome, report.reason) == ("failed", "gateway_domain_mismatch")
    assert world.apim.calls == []  # not even a dry run
    assert world.apim.snapshot()["backends/chat-pool"] == POOL


async def test_without_a_gateway_lookup_apim_intents_fail_closed() -> None:
    world = await apim_world()
    h = _harness(world)
    key = await h.executing(await reviewed_draft(world, swap_request(world)))
    report = await h.executor(table=TABLE).execute(key)
    assert (report.outcome, report.reason) == ("failed", "gateway_lookup_unconfigured")
    assert world.apim.calls == []


async def test_an_unregistered_gateway_fails_and_an_outage_defers() -> None:
    world = await apim_world()
    h = _harness(world)
    key = await h.executing(await reviewed_draft(world, swap_request(world)))
    down = InMemoryGatewayStore()
    down.fail_with(DependencyTransientError("down", reason="gateway_store_unavailable"))
    deferred = await h.executor(table=TABLE, gateways=down).execute(key)
    assert (deferred.outcome, deferred.reason) == ("deferred", "gateway_store_unavailable")
    report = await h.executor(table=TABLE, gateways=InMemoryGatewayStore()).execute(key)
    assert (report.outcome, report.reason) == ("failed", "gateway_not_registered")
    assert world.apim.calls == []


# -- observe guard always wired (item 2 hand-off 2) -----------------------------------------------


async def test_observe_mode_gateway_changes_nothing_through_the_executor() -> None:
    manage = await apim_world()
    request = swap_request(manage)
    draft = await reviewed_draft(manage, request)
    # The same gateway, now registered in observe mode (switched back after the review).
    world = await apim_world(registration(mode="observe"), apim=manage.apim, backends={})
    h = _harness(world)
    key = await h.executing(draft)
    report = await h.executor(table=TABLE, gateways=world.store).execute(key)
    assert (report.outcome, report.reason) == ("failed", GATEWAY_OBSERVE_MODE)
    assert world.apim.writes() == []
    assert world.apim.snapshot()["backends/chat-pool"] == POOL
    assert world.statuses() == []


async def test_composition_always_wires_the_mode_guard_and_refuses_government() -> None:
    world = await apim_world()
    assert isinstance(world.connector, ApimGatewayConnector)
    with pytest.raises(TypeError):
        ApimGatewayConnector(  # type: ignore[call-arg]
            world.connector.gateway,
            world.apim,
            records=world.records,
        )
    gov = registration(cloud="government")
    store = InMemoryGatewayStore()
    await store.create(gov)
    advisory = build_apim_gateway_connector(
        gov,
        InMemoryApim(),
        store=store,
        records=InMemoryGatewayRecordStore(ApplyRecord),
    )
    assert isinstance(advisory, ApimGatewayAdvisoryConnector)
    with pytest.raises(CapabilityUnavailableError):
        WriteTargetRegistry().register(advisory)


# -- rollback reads as busy (item 2 hand-off 3) ---------------------------------------------------


class _WatchingApim(InMemoryApim):
    """Records whether the gateway reads as busy, and the mode switch refuses, on each PUT."""

    def __init__(self) -> None:
        super().__init__()
        self.during_put: list[tuple[bool, str | None]] = []
        self.watch: tuple[InMemoryGatewayRecordStore[ApplyRecord], GatewayModeSwitch] | None = None

    async def put(self, path: str, properties: Mapping[str, Any], *, if_match: str | None) -> None:
        if self.watch is not None:
            records, switch = self.watch
            reason: str | None = None
            try:
                current = await switch.load()
                await switch.check(
                    mode_target_version(current), ModeChange(desired="observe", changed_by="pn")
                )
            except CapabilityUnavailableError as exc:
                reason = exc.reason
            self.during_put.append((await records.running(GW), reason))
        await super().put(path, properties, if_match=if_match)


class _FailingCanary:
    async def probe(self, request: Any, applied: Any, observed: Any) -> str:
        return "failed"


async def test_a_rollback_of_a_succeeded_apply_is_visible_as_busy() -> None:
    apim = _WatchingApim()
    world = await apim_world(apim=apim)
    h = _harness(world)
    key = await h.executing(await reviewed_draft(world, swap_request(world)))
    switch = GatewayModeSwitch(
        world.store,
        customer_id=CUSTOMER,
        domain_id=DOMAIN,
        gateway_id=GW,
        activity=world.records,
        clock=lambda: START,
    )
    apim.watch = (world.records, switch)
    report = await h.executor(
        table=TABLE,
        gateways=world.store,
        canary=_FailingCanary(),  # type: ignore[arg-type]
    ).execute(key)
    assert report.outcome == "rolled_back"
    # Two PUTs: the apply, then the rollback's restore. Both ran while the gateway was busy.
    assert apim.during_put == [(True, GATEWAY_APPLYING), (True, GATEWAY_APPLYING)]
    assert not await world.records.running(GW)
    assert world.apim.snapshot()["backends/chat-pool"] == POOL
