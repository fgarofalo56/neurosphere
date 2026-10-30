"""The APIM backend canary probe (PRP-34 item 3): pool read-back plus one gateway log row.

Probe-level tests drive the connector directly (test code); the executor tests at the bottom run
the real executor phases (apply -> canary -> verify, rollback on a failed canary).
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from neurosphere_connector.write import ApplyResult, VerifyResult, WriteRequest
from neurosphere_connector_apim_gateway import GatewayRef
from neurosphere_connector_apim_gateway.swap import pool_weights
from neurosphere_connector_azure_monitor import SourceKind
from neurosphere_core.errors import DependencyTransientError
from neurosphere_workers.actions import DEFAULT_ACTION_CONNECTORS
from neurosphere_workers.actions.apim import apim_gateway_ref
from neurosphere_workers.actions.apim_canary import ApimBackendCanaryProbe

from .apim_support import (
    CANARY_WEIGHTS,
    NEW_URL,
    POOL,
    SINGLE,
    WORKSPACE,
    ApimWorld,
    FakeLogs,
    apim_world,
    gateway_row,
    poll_result,
    registration,
    reviewed_draft,
    swap_request,
)
from .executor_support import FakeClock, Harness, draft_request

WINDOW = timedelta(minutes=5)
INTERVAL = timedelta(seconds=30)


class ClockSleep:
    """Sleep that advances the fake clock (the probe's bounded wait never really waits)."""

    def __init__(self, clock: FakeClock) -> None:
        self.clock = clock
        self.slept: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.clock.advance(timedelta(seconds=seconds))


def _probe(
    world: ApimWorld, *, logs: FakeLogs | None = None, clock: FakeClock | None = None
) -> tuple[ApimBackendCanaryProbe, ClockSleep]:
    clock = clock or FakeClock()
    sleep = ClockSleep(clock)
    probe = ApimBackendCanaryProbe(
        gateway=_ref(world),
        arm=world.apim,
        gateways=world.store,
        logs=logs,
        window=WINDOW,
        interval=INTERVAL,
        clock=clock,
        sleep=sleep,
    )
    return probe, sleep


def _ref(world: ApimWorld) -> GatewayRef:
    return apim_gateway_ref(world.registration)


async def _applied(world: ApimWorld, request: WriteRequest) -> tuple[ApplyResult, VerifyResult]:
    planned = await world.connector.dry_run(request)
    reviewed = request.model_copy(update={"proposed_diff": planned.planned_diff})
    applied = await world.connector.apply(reviewed)
    return applied, await world.connector.verify(reviewed)


# -- probe ----------------------------------------------------------------------------------------


async def test_other_targets_fall_back_to_verify_only() -> None:
    world = await apim_world()
    probe, _ = _probe(world)
    foundry = draft_request()
    request = WriteRequest(
        target=foundry.target, target_version="v1", proposed_diff=foundry.proposed_diff
    )
    applied = ApplyResult(
        target=request.target, version_before="v1", applied_diff=request.proposed_diff
    )
    observed = VerifyResult(
        target=request.target,
        requested_diff=request.proposed_diff,
        observed_state={},
        checks=(),
    )
    assert await probe.probe(request, applied, observed) == "verify_only"
    assert world.apim.calls == []


async def test_single_backend_is_an_atomic_swap_with_verify_only_canary() -> None:
    world = await apim_world(backends={"foundry": SINGLE})
    request = swap_request(world, "foundry", url=NEW_URL)
    applied, observed = await _applied(world, request)
    assert observed.matched
    probe, _ = _probe(world)
    assert await probe.probe(request, applied, observed) == "verify_only"


async def test_pool_without_gateway_logs_passes_on_read_back() -> None:
    world = await apim_world()
    request = swap_request(world)
    applied, observed = await _applied(world, request)
    world.apim.calls.clear()
    probe, sleep = _probe(world)
    assert await probe.probe(request, applied, observed) == "passed"
    assert [(c.method, c.path) for c in world.apim.calls] == [("GET", "backends/chat-pool")]
    assert sleep.slept == []


async def test_pool_with_gateway_logs_passes_on_one_row_for_the_new_backend() -> None:
    world = await apim_world(registration(gateway_logs=True))
    request = swap_request(world)
    applied, observed = await _applied(world, request)
    clock = FakeClock()
    logs = FakeLogs(
        [
            poll_result([gateway_row("gpt4o-east")]),  # only the old member so far
            poll_result([gateway_row("gpt4o-east"), gateway_row("/backends/GPT41-East")]),
        ]
    )
    probe, sleep = _probe(world, logs=logs, clock=clock)
    started = clock.now
    assert await probe.probe(request, applied, observed) == "passed"
    assert len(logs.calls) == 2 and sleep.slept == [INTERVAL.total_seconds()]
    sources, watermark = logs.calls[0]
    assert [(s.kind, s.source_id) for s in sources] == [(SourceKind.APIM_GATEWAY, WORKSPACE)]
    assert watermark == started


async def test_no_row_within_the_window_fails_the_canary() -> None:
    world = await apim_world(registration(gateway_logs=True))
    request = swap_request(world)
    applied, observed = await _applied(world, request)
    logs = FakeLogs([poll_result([gateway_row("gpt4o-east")])])
    probe, sleep = _probe(world, logs=logs)
    assert await probe.probe(request, applied, observed) == "failed"
    expected_polls = int(WINDOW / INTERVAL) + 1
    assert len(logs.calls) == expected_polls  # bounded: one query per interval, then stop
    assert len(sleep.slept) == expected_polls - 1


async def test_a_failed_query_is_retried_inside_the_window() -> None:
    world = await apim_world(registration(gateway_logs=True))
    request = swap_request(world)
    applied, observed = await _applied(world, request)
    logs = FakeLogs(
        [
            DependencyTransientError("throttled", reason="la_unavailable"),
            poll_result([gateway_row("gpt41-east")]),
        ]
    )
    probe, _ = _probe(world, logs=logs)
    assert await probe.probe(request, applied, observed) == "passed"


async def test_diagnostics_without_a_log_source_fail_closed() -> None:
    world = await apim_world(registration(gateway_logs=True))
    request = swap_request(world)
    applied, observed = await _applied(world, request)
    probe, _ = _probe(world, logs=None)
    assert await probe.probe(request, applied, observed) == "failed"


async def test_pool_weights_that_do_not_read_back_fail() -> None:
    world = await apim_world()
    request = swap_request(world)
    applied, observed = await _applied(world, request)
    world.apim.seed("backends/chat-pool", POOL)  # someone put the old weights back
    probe, _ = _probe(world)
    assert await probe.probe(request, applied, observed) == "failed"


async def test_unmatched_executor_read_back_fails_without_further_reads() -> None:
    world = await apim_world()
    request = swap_request(world)
    applied, _ = await _applied(world, request)
    world.apim.seed("backends/chat-pool", POOL)
    observed = await world.connector.verify(request)
    assert not observed.matched
    world.apim.calls.clear()
    probe, _ = _probe(world)
    assert await probe.probe(request, applied, observed) == "failed"
    assert world.apim.calls == []


def test_probe_rejects_a_non_positive_window() -> None:
    with pytest.raises(ValueError):
        ApimBackendCanaryProbe(
            gateway=apim_gateway_ref(registration()),
            arm=object(),  # type: ignore[arg-type]
            gateways=object(),  # type: ignore[arg-type]
            window=timedelta(0),
        )


# -- through the executor -------------------------------------------------------------------------


async def _run(
    world: ApimWorld, request: WriteRequest, logs: FakeLogs | None
) -> tuple[Harness, str | None, str | None]:
    h = Harness()
    h.registry.register(world.connector)
    clock = h.clock
    probe = ApimBackendCanaryProbe(
        gateway=_ref(world),
        arm=world.apim,
        gateways=world.store,
        logs=logs,
        window=WINDOW,
        interval=INTERVAL,
        clock=clock,
        sleep=ClockSleep(clock),
    )
    key = await h.executing(await reviewed_draft(world, request))
    report = await h.executor(
        table=dict(DEFAULT_ACTION_CONNECTORS), canary=probe, gateways=world.store
    ).execute(key)
    stored = await h.current(key)
    canary = stored.execution.canary if stored.execution else None
    return h, report.outcome, canary


async def test_executor_pool_canary_passes_and_the_shift_is_verified() -> None:
    world = await apim_world(registration(gateway_logs=True))
    logs = FakeLogs([poll_result([gateway_row("gpt41-east")])])
    h, outcome, canary = await _run(world, swap_request(world), logs)
    assert (outcome, canary) == ("succeeded", "passed")
    assert pool_weights(world.apim.snapshot()["backends/chat-pool"]) == CANARY_WEIGHTS
    assert h.connector.calls == []  # the Foundry-style fake connector was never touched


async def test_executor_pool_canary_failure_rolls_the_shift_back() -> None:
    world = await apim_world(registration(gateway_logs=True))
    logs = FakeLogs([poll_result([])])
    _, outcome, canary = await _run(world, swap_request(world), logs)
    assert (outcome, canary) == ("rolled_back", "failed")
    assert world.apim.snapshot()["backends/chat-pool"] == POOL
    assert world.statuses()[-1][-2:] == ["applying", "rolled_back"]


async def test_executor_single_backend_swap_records_verify_only() -> None:
    world = await apim_world(backends={"foundry": SINGLE})
    _, outcome, canary = await _run(world, swap_request(world, "foundry", url=NEW_URL), None)
    assert (outcome, canary) == ("succeeded", "verify_only")
    assert world.apim.snapshot()["backends/foundry"]["url"] == NEW_URL
