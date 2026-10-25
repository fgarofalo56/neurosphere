"""PriceSnapshotStore protocol conformance checks (synchronous protocol), shared by every backend.

Each check takes a FRESH, empty store. ``CHECKS`` maps a check name to the function; the in-memory
+ fake-container suite and the emulator suite (``tests/integration/stores_cosmos``) both
parametrize over it.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from decimal import Decimal

import pytest
from neurosphere_core.pricing import (
    FIXTURE_DIR,
    PriceRow,
    PriceSnapshot,
    PriceSnapshotStore,
    SnapshotConflictError,
    TokenMeter,
    build_snapshot,
    load_snapshot_file,
)
from neurosphere_core.pricing.models import TokenKind

MODEL = ("azure_openai", "gpt-4.1-mini", "2025-04-14")


def sheet(
    snapshot_id: str,
    effective: date,
    price_in: str,
    clouds: tuple[str, ...] = ("commercial",),
    source: str = "provider_price_sheet",
) -> PriceSnapshot:
    kinds: list[tuple[TokenKind, str]] = [("input", price_in), ("output", "4")]
    rows = [
        PriceRow(
            service_name="s",
            sku_name=f"k-{kind}",
            unit_of_measure="1M",
            retail_price=Decimal(price),
            token_meter=TokenMeter(
                provider="azure_openai", model="gpt-4.1-mini", model_version="2025-04-14", kind=kind
            ),
        )
        for kind, price in kinds
    ]
    return build_snapshot(
        snapshot_id=snapshot_id,
        source=source,  # type: ignore[arg-type]
        source_url=(
            "https://prices.azure.com/api/retail/prices"
            if source == "azure_retail_prices"
            else "https://pricing.invalid/s"
        ),
        retrieval_date=date(2026, 10, 19),
        effective_date=effective,
        currency="USD",
        clouds=clouds,  # type: ignore[arg-type]
        rows=rows,
    )


def retail_fixture() -> PriceSnapshot:
    return load_snapshot_file(FIXTURE_DIR / "retail-prices-synthetic-2026-10.json")


def snap_ids(snapshots: list[PriceSnapshot]) -> list[str]:
    return [s.snapshot_id for s in snapshots]


Check = Callable[[PriceSnapshotStore], None]


def check_satisfies_protocol(store: PriceSnapshotStore) -> None:
    assert isinstance(store, PriceSnapshotStore)


def check_put_is_append_only_and_idempotent(store: PriceSnapshotStore) -> None:
    first = sheet("s-a", date(2026, 10, 1), "1")
    assert store.put(first) is True
    assert store.put(first) is False  # same id + same hash: no-op
    with pytest.raises(SnapshotConflictError):
        store.put(sheet("s-a", date(2026, 10, 1), "2"))  # same id, different content
    assert store.get("s-a") == first  # untouched


def check_snapshot_id_is_unique_across_sources(store: PriceSnapshotStore) -> None:
    store.put(sheet("shared-id", date(2026, 10, 1), "1", source="provider_price_sheet"))
    clash = sheet("shared-id", date(2026, 10, 1), "1", source="azure_retail_prices")
    with pytest.raises(SnapshotConflictError):
        store.put(clash)


def check_get_round_trips_exactly(store: PriceSnapshotStore) -> None:
    retail = retail_fixture()
    provider = sheet("s-gov", date(2026, 10, 1), "0.125", clouds=("commercial", "government"))
    store.put(retail)
    store.put(provider)
    assert store.get(retail.snapshot_id) == retail  # azure_retail_prices partition
    assert store.get("s-gov") == provider  # provider_price_sheet partition
    assert store.get("missing") is None


def check_list_is_newest_first_with_id_tiebreak_and_cloud_filter(
    store: PriceSnapshotStore,
) -> None:
    store.put(sheet("s-old", date(2026, 8, 1), "1"))
    store.put(sheet("s-b", date(2026, 10, 1), "2"))
    store.put(sheet("s-a", date(2026, 10, 1), "3"))
    store.put(sheet("s-gov", date(2026, 9, 1), "4", clouds=("government",)))
    assert snap_ids(store.list_snapshots()) == ["s-b", "s-a", "s-gov", "s-old"]
    assert snap_ids(store.list_snapshots("commercial")) == ["s-b", "s-a", "s-old"]
    assert snap_ids(store.list_snapshots("government")) == ["s-gov"]
    assert store.list_snapshots("nowhere") == []


def check_resolve_picks_newest_effective_on_or_before(store: PriceSnapshotStore) -> None:
    store.put(sheet("s-2026-08", date(2026, 8, 1), "1"))
    store.put(sheet("s-2026-10", date(2026, 10, 1), "2"))
    store.put(sheet("s-2026-12", date(2026, 12, 1), "3"))
    pick = store.resolve("commercial", date(2026, 10, 19))
    assert pick is not None
    assert pick.snapshot_id == "s-2026-10"
    boundary = store.resolve("commercial", date(2026, 10, 1))
    assert boundary is not None
    assert boundary.snapshot_id == "s-2026-10"
    assert store.resolve("commercial", date(2026, 7, 31)) is None


def check_government_never_falls_back_to_commercial(store: PriceSnapshotStore) -> None:
    store.put(sheet("s-com", date(2026, 10, 1), "1", clouds=("commercial",)))
    assert store.resolve("government", date(2026, 12, 1)) is None
    assert store.resolve_token_price("government", *MODEL, date(2026, 12, 1)) is None
    store.put(sheet("s-gov", date(2026, 9, 1), "9", clouds=("government",)))
    got = store.resolve_token_price("government", *MODEL, date(2026, 12, 1))
    assert got is not None
    assert got.snapshot.snapshot_id == "s-gov"
    assert got.rate.input == Decimal("9")


def check_resolve_token_price_by_date_and_model(store: PriceSnapshotStore) -> None:
    store.put(sheet("s-a", date(2026, 8, 1), "1"))
    store.put(sheet("s-b", date(2026, 10, 1), "2"))
    older = store.resolve_token_price("commercial", *MODEL, date(2026, 9, 1))
    assert older is not None
    assert older.snapshot.snapshot_id == "s-a"
    assert older.rate.input == Decimal("1")
    newer = store.resolve_token_price("commercial", *MODEL, date(2026, 10, 19))
    assert newer is not None
    assert newer.snapshot.snapshot_id == "s-b"
    assert newer.version.price_version_id == "s-b"
    assert (
        store.resolve_token_price("commercial", "azure_openai", "unknown", None, date(2026, 10, 19))
        is None
    )
    assert (
        store.resolve_token_price("commercial", None, "gpt-4.1-mini", None, date(2026, 10, 19))
        is None
    )
    assert store.resolve_token_price("commercial", *MODEL, date(2026, 7, 1)) is None


CHECKS: dict[str, Check] = {
    name.removeprefix("check_"): fn
    for name, fn in sorted(globals().items())
    if name.startswith("check_")
}
