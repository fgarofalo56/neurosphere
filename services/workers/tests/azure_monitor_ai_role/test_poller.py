"""azure_monitor_ai: rows are read per workspace and kind, mapped, batched and posted."""

from __future__ import annotations

from .support import (
    DEPS,
    FAKE_SECRET,
    NOW,
    REQS,
    WS1,
    WS2,
    FakeConnector,
    Rig,
    dep_rows,
    req_rows,
    result,
)


async def test_reads_both_kinds_and_posts_mapped_events() -> None:
    connector = FakeConnector(
        {
            (DEPS, WS1): [result(dep_rows(), next_watermark=NOW)],
            (REQS, WS1): [result(req_rows(), next_watermark=NOW)],
        }
    )
    rig = Rig(connector)
    await rig.poller.tick()

    assert [(kind, ws) for kind, ws, _ in connector.calls] == [(DEPS, WS1), (REQS, WS1)]
    assert connector.closed == 2
    assert len(rig.api.events) == 6  # five dependencies + one request; one row had bad ids
    first = rig.api.events[0]
    assert first["type"] and first["specversion"] == "1.0"
    assert first["data"]["source_id"] == "azure-monitor-ai"
    assert first["data"]["domain_id"] == "dom-1"
    assert first["data"]["customer_id"] == "synthco"
    status = rig.poller.last_status
    assert status.state == "ok" and status.reason is None
    assert status.counts == {"queries": 2, "rows": 7, "events_posted": 6, "rows_skipped": 1}


async def test_posts_in_batches_of_batch_size() -> None:
    connector = FakeConnector({(DEPS, WS1): [result(dep_rows(), next_watermark=NOW)]})
    rig = Rig(connector, batch_size=2)
    await rig.poller.tick()
    assert [len(batch) for batch in rig.api.batches] == [2, 2, 1]


async def test_one_connector_poll_per_workspace_and_kind() -> None:
    rig = Rig(workspace_ids=f"{WS1},{WS2.upper()},{WS1}")
    await rig.poller.tick()
    pairs = {(kind, ws) for kind, ws, _ in rig.connector.calls}
    assert pairs == {(DEPS, WS1), (REQS, WS1), (DEPS, WS2), (REQS, WS2)}
    assert len(rig.connector.calls) == 4  # never more than the configured workspaces


async def test_app_role_filter_counts_skips() -> None:
    connector = FakeConnector({(DEPS, WS1): [result(dep_rows(), next_watermark=NOW)]})
    rig = Rig(connector, app_role_names="some-other-role")
    await rig.poller.tick()
    assert rig.api.events == []
    assert rig.poller.last_status.counts["rows_skipped"] == 6


async def test_producer_secret_is_never_in_the_event_body() -> None:
    connector = FakeConnector({(DEPS, WS1): [result(dep_rows(), next_watermark=NOW)]})
    rig = Rig(connector)
    await rig.poller.tick()
    assert FAKE_SECRET not in repr(rig.api.batches)
    assert FAKE_SECRET not in repr(rig.settings)


async def test_bounds_follow_the_settings() -> None:
    rig = Rig(window_seconds=1800)
    await rig.poller.tick()
    cloud, bounds = rig.factory_calls[0]
    assert cloud == "commercial"
    assert bounds.max_window.total_seconds() == 1800
    assert bounds.max_pages == 2  # 1800 s of 15 minute slices
