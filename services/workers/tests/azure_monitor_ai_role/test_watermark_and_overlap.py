"""azure_monitor_ai: lookback, overlap, and a watermark that moves only after every batch landed."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from neurosphere_workers.ingestion.azure_monitor_ai import checkpoint_key

from .support import (
    DEPS,
    NOW,
    REQS,
    WS1,
    FakeConnector,
    Rig,
    at,
    dep_rows,
    result,
)


async def test_first_poll_starts_at_the_lookback() -> None:
    rig = Rig(lookback_seconds=7200)
    await rig.poller.tick()
    assert rig.connector.calls[0][2] == NOW - timedelta(seconds=7200)


async def test_next_poll_starts_at_the_watermark_minus_the_overlap() -> None:
    mark = at(20)
    connector = FakeConnector({(DEPS, WS1): [result(dep_rows(), next_watermark=mark)]})
    rig = Rig(connector, overlap_seconds=600)
    await rig.poller.tick()
    assert await rig.checkpoints.get(checkpoint_key(DEPS, WS1)) == mark.isoformat()
    assert await rig.checkpoints.get(checkpoint_key(REQS, WS1)) is not None

    await rig.poller.tick()
    deps_calls = [w for kind, _, w in connector.calls if kind is DEPS]
    assert deps_calls[1] == mark - timedelta(seconds=600)


def test_checkpoint_key_shape() -> None:
    assert checkpoint_key(DEPS, WS1) == f"azure-monitor-ai/app_genai_dependencies/{WS1}"


async def test_start_never_reaches_past_the_lookback() -> None:
    rig = Rig(lookback_seconds=3600)
    await rig.checkpoints.commit(checkpoint_key(DEPS, WS1), at(60 * 24 * 3).isoformat())
    await rig.poller.tick()
    assert rig.connector.calls[0][2] == NOW - timedelta(seconds=3600)


async def test_watermark_never_moves_backwards() -> None:
    stored = at(5)
    rig = Rig()  # unscripted: no progress, next_watermark == the start (stored - overlap)
    await rig.checkpoints.commit(checkpoint_key(DEPS, WS1), stored.isoformat())
    before = rig.checkpoints.commit_count
    await rig.poller.tick()
    assert await rig.checkpoints.get(checkpoint_key(DEPS, WS1)) == stored.isoformat()
    # The requests kind had no watermark, so only that one advanced.
    assert rig.checkpoints.commit_count == before + 1


async def test_ingest_failure_leaves_the_watermark_and_says_why() -> None:
    connector = FakeConnector({(DEPS, WS1): [result(dep_rows(), next_watermark=at(20))]})
    rig = Rig(connector)
    rig.api.status = 500
    await rig.poller.tick()
    assert await rig.checkpoints.get(checkpoint_key(DEPS, WS1)) is None
    status = rig.poller.last_status
    assert (status.state, status.reason) == ("failed", "ingest_failed")
    assert status.counts["events_posted"] == 0
    assert len(connector.calls) == 1  # the shared edge is down: the rest of the tick is skipped


async def test_second_batch_failing_commits_nothing_and_is_partial() -> None:
    connector = FakeConnector({(DEPS, WS1): [result(dep_rows(), next_watermark=at(20))]})
    rig = Rig(connector, batch_size=2)
    rig.api.fail_after = 1
    await rig.poller.tick()
    assert await rig.checkpoints.get(checkpoint_key(DEPS, WS1)) is None
    status = rig.poller.last_status
    assert (status.state, status.reason) == ("partial", "ingest_failed")
    assert status.counts["events_posted"] == 2


async def test_replay_after_failure_reads_the_same_window() -> None:
    mark = at(20)
    connector = FakeConnector({(DEPS, WS1): [result(dep_rows(), next_watermark=mark)]})
    rig = Rig(connector)
    rig.api.status = 500
    await rig.poller.tick()
    rig.api.status = 202
    await rig.poller.tick()
    first, second = connector.calls[0][2], connector.calls[1][2]
    assert first == second  # same start: nothing was acknowledged
    assert await rig.checkpoints.get(checkpoint_key(DEPS, WS1)) == mark.isoformat()


class _BrokenStore:
    def __init__(self, *, on_get: bool) -> None:
        self._on_get = on_get

    async def get(self, partition_key: str) -> str | None:
        if self._on_get:
            raise RuntimeError("store outage")
        return None

    async def commit(self, partition_key: str, checkpoint: str) -> None:
        raise RuntimeError("store outage")


@pytest.mark.parametrize("on_get", [True, False])
async def test_checkpoint_store_outage_propagates(on_get: bool) -> None:
    connector = FakeConnector({(DEPS, WS1): [result(dep_rows(), next_watermark=at(20))]})
    rig = Rig(connector)
    rig.poller._checkpoints = _BrokenStore(on_get=on_get)  # pyright: ignore[reportPrivateUsage]
    with pytest.raises(RuntimeError, match="store outage"):
        await rig.poller.tick()


async def test_a_stored_garbage_watermark_falls_back_to_the_lookback() -> None:
    rig = Rig()
    await rig.checkpoints.commit(checkpoint_key(DEPS, WS1), "not-a-date")
    await rig.poller.tick()
    start = rig.connector.calls[0][2]
    assert isinstance(start, datetime) and start == NOW - timedelta(seconds=86400)
