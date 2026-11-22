"""azure_monitor_ai: run status, 401/403, secret hygiene and the StatusRecordingTick wiring."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

import pytest
from neurosphere_core.errors import DependencyTransientError, ForbiddenError, UnauthorizedError
from neurosphere_core.sources_status import (
    InMemorySourceStatusRepository,
    SourceStatusRepository,
)
from neurosphere_workers.ingestion.azure_monitor_ai import checkpoint_key
from neurosphere_workers.sources_status import StatusRecordingTick

from .support import (
    CUSTOMER,
    DEPS,
    GUID,
    NOW,
    REQS,
    WS1,
    WS2,
    FakeConnector,
    Rig,
    at,
    dep_rows,
    req_rows,
    result,
)


async def test_forbidden_workspace_fails_and_the_other_workspace_is_still_read() -> None:
    connector = FakeConnector(
        {
            (DEPS, WS1): [ForbiddenError("denied")],
            (REQS, WS1): [ForbiddenError("denied")],
            (DEPS, WS2): [result(dep_rows(WS2), next_watermark=NOW)],
        }
    )
    rig = Rig(connector, workspace_ids=f"{WS1},{WS2}")
    await rig.poller.tick()
    assert (DEPS, WS2) in [(k, w) for k, w, _ in connector.calls]
    assert len(rig.api.events) == 5
    status = rig.poller.last_status
    # Something was delivered, so it is partial; the reason still names the missing role.
    assert (status.state, status.reason) == ("partial", "source_access_denied")


@pytest.mark.parametrize("error", [ForbiddenError("x"), UnauthorizedError("x")])
async def test_every_workspace_denied_is_failed(error: Exception) -> None:
    connector = FakeConnector({(DEPS, WS1): [error], (REQS, WS1): [error]})
    rig = Rig(connector)
    await rig.poller.tick()
    status = rig.poller.last_status
    assert (status.state, status.reason) == ("failed", "source_access_denied")
    assert status.counts["events_posted"] == 0
    assert await rig.checkpoints.get(checkpoint_key(DEPS, WS1)) is None


async def test_other_upstream_failures_are_failed_source_unreachable_and_never_raise() -> None:
    connector = FakeConnector(
        {(DEPS, WS1): [DependencyTransientError("down")], (REQS, WS1): [RuntimeError("boom")]}
    )
    rig = Rig(connector)
    await rig.poller.tick()
    status = rig.poller.last_status
    assert (status.state, status.reason) == ("failed", "source_unreachable")
    assert len(connector.calls) == 2  # the role keeps going


async def test_status_counts_have_exactly_the_agreed_keys() -> None:
    rig = Rig(FakeConnector({(DEPS, WS1): [result(dep_rows(), next_watermark=NOW)]}))
    await rig.poller.tick()
    assert set(rig.poller.last_status.counts) == {
        "queries",
        "rows",
        "events_posted",
        "rows_skipped",
    }


async def test_unconfigured_workspaces_are_idle() -> None:
    rig = Rig(workspace_ids=None)
    await rig.poller.tick()
    assert rig.poller.last_status.state == "idle"


async def test_no_log_or_status_holds_an_id_a_host_or_a_url(
    caplog: pytest.LogCaptureFixture,
) -> None:
    connector = FakeConnector(
        {
            (DEPS, WS1): [ForbiddenError("https://api.loganalytics.io/v1/workspaces/" + WS1)],
            (REQS, WS1): [
                result(req_rows(), next_watermark=at(20), partial=True, truncated_pages=1)
            ],
            (DEPS, WS2): [RuntimeError("http://example.invalid/" + WS2)],
            (REQS, WS2): [result(req_rows(WS2), next_watermark=at(20), rate_limited=True)],
        }
    )
    rig = Rig(connector, workspace_ids=f"{WS1},{WS2}")
    rig.api.status = 500
    with caplog.at_level(logging.DEBUG):
        await rig.poller.tick()
    rig.api.status = 202
    with caplog.at_level(logging.DEBUG):
        await rig.poller.tick()
    # Our own records only: httpx's library logger prints the ingest URL by itself.
    ours = [r for r in caplog.records if r.name.startswith("neurosphere.")]
    assert ours  # the scan is not vacuous
    seen = [r.getMessage() for r in ours]
    extras = ("event", "error", "status")
    seen += [repr([getattr(r, name, None) for name in extras]) for r in ours]
    status = rig.poller.last_status
    seen += [repr(status.reason), repr(status.counts), status.state]
    for text in seen:
        assert GUID.search(text) is None
        assert "http" not in text.lower()


async def test_status_is_recorded_through_the_status_recording_tick() -> None:
    repo = InMemorySourceStatusRepository()

    async def build() -> SourceStatusRepository:
        return repo

    factory: Callable[[], Awaitable[SourceStatusRepository]] = build
    rig = Rig(FakeConnector({(DEPS, WS1): [result(dep_rows(), next_watermark=NOW)]}))
    tick = StatusRecordingTick(
        "azure_monitor_ai",
        rig.poller.tick,
        lambda: rig.poller.last_status,
        factory,
        customer_id=CUSTOMER,
    )
    await tick()
    stored = await repo.get(CUSTOMER, "azure_monitor_ai")
    assert stored is not None
    assert stored.state == "ok"
    assert stored.counts["events_posted"] == 5
    assert stored.last_success_at is not None
