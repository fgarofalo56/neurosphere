"""Price table refresh: a sheet written after start is picked up; failures keep the old table."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, ClassVar

import neurosphere_core.pricing as pricing_pkg
import pytest
from neurosphere_core.clients import ClientLifetime
from neurosphere_core.cloud import Settings
from neurosphere_core.ledger import PriceTable
from neurosphere_core.pricing.loader import load_snapshot_file
from neurosphere_core.pricing.models import PriceSnapshot
from neurosphere_workers.runtime import factories
from neurosphere_workers.runtime.factories import RuntimeConfig, build_aggregates
from neurosphere_workers.runtime.price_refresh import PriceTableRefresher
from neurosphere_workers.runtime.settings import AuthSettings, StoreSettings, WorkerSettings
from pydantic import ValidationError

_FIXTURES = Path(pricing_pkg.__file__).parent / "fixtures"
_SNAP_A = load_snapshot_file(_FIXTURES / "retail-prices-synthetic-2026-10.json")
_SNAP_B = load_snapshot_file(_FIXTURES / "provider-sheet-gov-synthetic-2026-10.json")


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class _FakePriceStore:
    """Stands in for the sync price store behind the loader."""

    def __init__(self, snapshots: list[PriceSnapshot] | None = None) -> None:
        self.snapshots = list(snapshots or [])
        self.fail = False
        self.loads = 0

    async def load(self) -> list[PriceSnapshot]:
        self.loads += 1
        if self.fail:
            raise OSError("store down: secret-endpoint")
        return list(self.snapshots)


def _ids(table: PriceTable) -> set[str]:
    return {v.price_version_id for v in table.versions}


def _refresher(store: _FakePriceStore, clock: _Clock) -> PriceTableRefresher:
    return PriceTableRefresher(store.load, [], 60.0, clock=clock)


async def test_new_snapshot_is_seen_after_the_interval() -> None:
    store, clock = _FakePriceStore(), _Clock()
    refresher = _refresher(store, clock)
    assert _ids(refresher.table) == set()

    store.snapshots.append(_SNAP_A)
    assert await refresher.refresh_if_due() is False  # interval not elapsed
    assert store.loads == 0

    clock.now += 61
    assert await refresher.refresh_if_due() is True
    assert _ids(refresher.table) == {_SNAP_A.snapshot_id}


async def test_unchanged_set_does_not_rebuild() -> None:
    store, clock = _FakePriceStore([_SNAP_A]), _Clock()
    refresher = PriceTableRefresher(store.load, [_SNAP_A], 60.0, clock=clock)
    table = refresher.table
    clock.now += 61
    assert await refresher.refresh_if_due() is False
    assert store.loads == 1
    assert refresher.table is table


async def test_failed_refresh_keeps_previous_table_and_logs_class_only(
    caplog: pytest.LogCaptureFixture,
) -> None:
    store, clock = _FakePriceStore([_SNAP_A]), _Clock()
    refresher = PriceTableRefresher(store.load, [_SNAP_A], 60.0, clock=clock)
    table = refresher.table
    store.fail = True
    clock.now += 61
    with caplog.at_level("WARNING", logger="neurosphere.workers.runtime"):
        assert await refresher.refresh_if_due() is False
    assert refresher.table is table
    assert [getattr(r, "error", None) for r in caplog.records] == ["OSError"]
    assert "secret-endpoint" not in caplog.text

    # not retried in a hot loop, recovers on the next interval
    store.fail = False
    store.snapshots.append(_SNAP_B)
    assert await refresher.refresh_if_due() is False
    assert store.loads == 1
    clock.now += 61
    assert await refresher.refresh_if_due() is True
    assert _ids(refresher.table) == {_SNAP_A.snapshot_id, _SNAP_B.snapshot_id}


def test_refresh_interval_is_bounded() -> None:
    assert WorkerSettings().price_refresh_seconds == 60.0
    with pytest.raises(ValidationError):
        WorkerSettings(price_refresh_seconds=1)
    with pytest.raises(ValidationError):
        WorkerSettings(price_refresh_seconds=7200)


class _Projection:
    built: ClassVar[list[PriceTable]] = []

    def __init__(self, *, prices: PriceTable, **_: Any) -> None:
        self.prices = prices
        _Projection.built.append(prices)

    async def handle(self, entry: object) -> None:
        return None

    async def prune(self, customer_id: str) -> None:
        return None


class _Reader:
    def __init__(self) -> None:
        self.handlers: list[Callable[..., Any]] = []

    async def drain(self, sink: str, customer_id: str, handler: Callable[..., Any]) -> Any:
        self.handlers.append(handler)

        class _Result:
            ok = True
            error = None

        return _Result()


class _Db:
    def get_container_client(self, name: str) -> object:
        return object()


async def test_aggregates_role_swaps_projection_between_ticks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, clock, reader = _FakePriceStore(), _Clock(), _Reader()
    _Projection.built = []

    async def fake_cosmos(cfg: object, lifetime: object) -> object:
        return object()

    async def fake_list(cfg: object) -> list[PriceSnapshot]:
        return await store.load()

    monkeypatch.setattr(factories, "_cosmos", fake_cosmos)
    monkeypatch.setattr(factories, "_database", lambda cfg, client: _Db())
    monkeypatch.setattr(factories, "_list_price_snapshots", fake_list)
    monkeypatch.setattr(factories, "_outbox_reader", lambda db: reader)
    monkeypatch.setattr(factories, "_archive_container", lambda cfg, lifetime: object())
    monkeypatch.setattr(factories, "CosmosAggregateStore", lambda container: object())
    monkeypatch.setattr(factories, "CosmosLedgerStore", lambda container: object())
    monkeypatch.setattr(factories, "StoreLedgerSource", lambda ledger: object())
    monkeypatch.setattr(factories, "ArchiveReader", lambda container: object())
    monkeypatch.setattr(factories, "ArchiveTraceEventSource", lambda reader_: object())
    monkeypatch.setattr(factories, "AggregateProjection", _Projection)
    ticks: list[Callable[[], Awaitable[None]]] = []
    monkeypatch.setattr(
        factories, "_tick_role", lambda name, tick, cfg: ticks.append(tick) or object()
    )
    monkeypatch.setattr(
        factories,
        "PriceTableRefresher",
        lambda load, initial, interval: PriceTableRefresher(load, initial, interval, clock=clock),
    )

    cfg = RuntimeConfig(Settings(env="local"), WorkerSettings(), StoreSettings(), AuthSettings())
    async with ClientLifetime() as lifetime:
        await build_aggregates(cfg, lifetime)
        tick = ticks[0]
        await tick()
        assert [_ids(t) for t in _Projection.built] == [set()]

        store.snapshots.append(_SNAP_A)
        await tick()  # interval not elapsed: same projection
        assert len(_Projection.built) == 1

        clock.now += 61
        await tick()
        assert [_ids(t) for t in _Projection.built] == [set(), {_SNAP_A.snapshot_id}]

        clock.now += 61
        await tick()  # unchanged set: no rebuild
        assert len(_Projection.built) == 2
