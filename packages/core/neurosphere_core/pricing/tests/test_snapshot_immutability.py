"""Snapshots are frozen, content-hashed and append-only (no network, fixtures only)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from neurosphere_core.pricing import (
    FIXTURE_DIR,
    InMemoryPriceSnapshotStore,
    PriceRow,
    PriceSnapshot,
    SnapshotConflictError,
    build_snapshot,
    compute_content_hash,
    load_snapshot_file,
)
from pydantic import ValidationError


def _retail() -> PriceSnapshot:
    return load_snapshot_file(FIXTURE_DIR / "retail-prices-synthetic-2026-10.json")


def _row(price: str) -> PriceRow:
    return PriceRow(
        service_name="svc", sku_name="sku", unit_of_measure="1 Hour", retail_price=Decimal(price)
    )


def _snap(snapshot_id: str = "snap-a", price: str = "1.5", **over: object) -> PriceSnapshot:
    args: dict[str, object] = {
        "snapshot_id": snapshot_id,
        "source": "provider_price_sheet",
        "source_url": "https://pricing.invalid/sheet",
        "retrieval_date": date(2026, 10, 19),
        "effective_date": date(2026, 10, 1),
        "currency": "USD",
        "clouds": ("commercial",),
        "rows": [_row(price)],
    }
    args.update(over)
    return build_snapshot(**args)  # type: ignore[arg-type]


def test_fixture_is_marked_synthetic_with_metadata() -> None:
    snap = _retail()
    assert snap.synthetic is True
    assert "SYNTHETIC" in snap.notes
    assert snap.source == "azure_retail_prices"
    assert snap.clouds == ("commercial",)
    assert snap.retrieval_date == date(2026, 10, 19)
    assert snap.currency == "USD"


def test_hash_is_sha256_of_content_and_stable() -> None:
    first, second = _retail(), _retail()
    assert first.content_hash == second.content_hash == compute_content_hash(first)
    assert len(first.content_hash) == 64


def test_hash_ignores_row_order_but_not_content() -> None:
    a = _snap(rows=[_row("1"), _row("2")])
    b = _snap(rows=[_row("2"), _row("1")])
    assert a.content_hash == b.content_hash
    assert _snap(price="1.5").content_hash != _snap(price="1.6").content_hash


def test_hash_treats_equal_decimals_alike() -> None:
    assert _snap(price="1.50").content_hash == _snap(price="1.5").content_hash


def test_snapshot_cannot_be_mutated() -> None:
    snap = _snap()
    with pytest.raises(ValidationError):
        snap.currency = "EUR"  # type: ignore[misc]
    assert isinstance(snap.rows, tuple)


def test_tampered_content_fails_hash_verification() -> None:
    snap = _snap()
    payload = snap.model_dump()
    payload["rows"] = [_row("999").model_dump()]
    with pytest.raises(ValidationError, match="content_hash"):
        PriceSnapshot.model_validate(payload)


def test_float_money_is_rejected() -> None:
    with pytest.raises(ValidationError):
        PriceRow.model_validate(
            {"service_name": "s", "sku_name": "k", "unit_of_measure": "1K", "retail_price": 0.1}
        )


def test_put_new_snapshot_returns_true_and_does_not_overwrite() -> None:
    store = InMemoryPriceSnapshotStore()
    old = _snap("snap-old", "1")
    new = _snap("snap-new", "2", effective_date=date(2026, 11, 1))
    assert store.put(old) is True
    assert store.put(new) is True
    assert store.get("snap-old") == old
    assert store.get("snap-new") == new


def test_identical_reput_is_an_idempotent_noop() -> None:
    store = InMemoryPriceSnapshotStore()
    snap = _snap()
    assert store.put(snap) is True
    assert store.put(_snap()) is False
    assert len(store.list_snapshots()) == 1


def test_same_id_different_content_is_refused_and_original_kept() -> None:
    store = InMemoryPriceSnapshotStore()
    original = _snap("snap-a", "1")
    store.put(original)
    with pytest.raises(SnapshotConflictError):
        store.put(_snap("snap-a", "2"))
    assert store.get("snap-a") == original


def test_retail_snapshot_cannot_claim_government() -> None:
    with pytest.raises(ValidationError, match="commercial only"):
        _snap(
            source="azure_retail_prices",
            source_url="https://prices.azure.com/x",
            clouds=("government",),
        )


def test_retail_snapshot_host_is_checked_by_hostname() -> None:
    with pytest.raises(ValidationError, match="host"):
        _snap(
            source="azure_retail_prices",
            source_url="https://prices.azure.com.evil.invalid/api/retail/prices",
        )
