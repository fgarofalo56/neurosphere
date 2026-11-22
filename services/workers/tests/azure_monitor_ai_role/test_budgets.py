"""azure_monitor_ai: query and event budgets, 429, truncation and the resume-next-tick rule."""

from __future__ import annotations

from neurosphere_core.errors import RateLimitedError
from neurosphere_workers.ingestion.azure_monitor_ai import checkpoint_key

from .support import (
    DEPS,
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


async def test_query_budget_stops_the_tick_and_the_next_tick_resumes_there() -> None:
    rig = Rig(workspace_ids=f"{WS1},{WS2}", max_queries_per_tick=2)
    await rig.poller.tick()
    assert [(k, w) for k, w, _ in rig.connector.calls] == [(DEPS, WS1), (REQS, WS1)]
    status = rig.poller.last_status
    assert (status.state, status.reason) == ("partial", "query_budget_exhausted")
    assert status.counts["queries"] == 2

    rig.connector.calls.clear()
    await rig.poller.tick()
    assert [(k, w) for k, w, _ in rig.connector.calls] == [(DEPS, WS2), (REQS, WS2)]


async def test_pages_are_capped_at_the_queries_left() -> None:
    rig = Rig(max_queries_per_tick=3)
    await rig.poller.tick()
    assert [b.max_pages for _, b in rig.factory_calls] == [3, 2]


async def test_a_budget_clipped_window_is_partial_with_the_budget_reason() -> None:
    connector = FakeConnector(
        {
            (DEPS, WS1): [result(dep_rows(), next_watermark=at(20), partial=True)],
        }
    )
    rig = Rig(connector, max_queries_per_tick=1)
    await rig.poller.tick()
    status = rig.poller.last_status
    assert (status.state, status.reason) == ("partial", "query_budget_exhausted")
    # What was read is kept: the watermark advanced to where the connector stopped.
    assert await rig.checkpoints.get(checkpoint_key(DEPS, WS1)) == at(20).isoformat()


async def test_a_window_cap_alone_is_not_a_partial() -> None:
    connector = FakeConnector(
        {(DEPS, WS1): [result(dep_rows(), next_watermark=at(20), partial=True)]}
    )
    rig = Rig(connector)
    await rig.poller.tick()
    assert rig.poller.last_status.state == "ok"


async def test_event_budget_stops_before_the_next_poll() -> None:
    connector = FakeConnector(
        {
            (DEPS, WS1): [result(dep_rows(), next_watermark=NOW)],
            (REQS, WS1): [result(req_rows(), next_watermark=NOW)],
        }
    )
    rig = Rig(connector, max_events_per_tick=5)
    await rig.poller.tick()
    # The first poll of a tick always goes through, so a big poll can never wedge the role.
    assert len(rig.api.events) == 5
    assert [k for k, _, _ in connector.calls] == [DEPS]
    status = rig.poller.last_status
    assert (status.state, status.reason) == ("partial", "event_budget_exhausted")


async def test_a_poll_that_would_overshoot_the_event_budget_is_left_for_the_next_tick() -> None:
    connector = FakeConnector(
        {
            (DEPS, WS1): [result(dep_rows(), next_watermark=NOW)],
            (REQS, WS1): [result(req_rows() * 3, next_watermark=NOW)],
        }
    )
    rig = Rig(connector, max_events_per_tick=6)
    await rig.poller.tick()
    assert len(rig.api.events) == 5  # three request events would pass the cap of six
    assert await rig.checkpoints.get(checkpoint_key(REQS, WS1)) is None
    assert rig.poller.last_status.reason == "event_budget_exhausted"

    await rig.poller.tick()  # resumes at the requests unit, as the first poll of the tick
    assert len(rig.api.events) == 8
    assert await rig.checkpoints.get(checkpoint_key(REQS, WS1)) is not None


async def test_a_throttled_first_slice_is_partial_rate_limited_and_stops_the_tick() -> None:
    connector = FakeConnector({(DEPS, WS1): [RateLimitedError(5, "throttled")]})
    rig = Rig(connector)
    await rig.poller.tick()
    status = rig.poller.last_status
    assert (status.state, status.reason) == ("partial", "rate_limited")
    assert await rig.checkpoints.get(checkpoint_key(DEPS, WS1)) is None
    assert len(connector.calls) == 1


async def test_a_mid_poll_429_keeps_the_completed_slices() -> None:
    connector = FakeConnector(
        {(DEPS, WS1): [result(dep_rows(), next_watermark=at(20), rate_limited=True)]}
    )
    rig = Rig(connector)
    await rig.poller.tick()
    assert len(rig.api.events) == 5
    status = rig.poller.last_status
    assert (status.state, status.reason) == ("partial", "rate_limited")
    assert await rig.checkpoints.get(checkpoint_key(DEPS, WS1)) == at(20).isoformat()


async def test_a_truncated_slice_commits_only_what_was_read() -> None:
    connector = FakeConnector(
        {(DEPS, WS1): [result(dep_rows(), next_watermark=at(25), partial=True, truncated_pages=1)]}
    )
    rig = Rig(connector)
    await rig.poller.tick()
    assert await rig.checkpoints.get(checkpoint_key(DEPS, WS1)) == at(25).isoformat()
    status = rig.poller.last_status
    assert (status.state, status.reason) == ("partial", "partial_results")


async def test_a_stalled_slice_is_reported() -> None:
    connector = FakeConnector(
        {(DEPS, WS1): [result([], next_watermark=at(25), partial=True, stalled_slice_start=at(25))]}
    )
    rig = Rig(connector)
    await rig.poller.tick()
    status = rig.poller.last_status
    assert (status.state, status.reason) == ("partial", "stalled")
