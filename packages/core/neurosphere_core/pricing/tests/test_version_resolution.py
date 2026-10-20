"""Resolution by effective date, cloud applicability and the ledger PriceVersion mapping."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from neurosphere_core.ledger.prices import PriceVersion
from neurosphere_core.pricing import (
    FIXTURE_DIR,
    InMemoryPriceSnapshotStore,
    PriceRow,
    PriceSnapshot,
    TokenMeter,
    build_snapshot,
    load_snapshot_file,
)
from neurosphere_core.pricing.models import TokenKind


def _prices(price_in: str) -> list[tuple[TokenKind, str]]:
    return [("input", price_in), ("output", "4")]


MODEL = ("azure_openai", "gpt-4.1-mini", "2025-04-14")


def _sheet(
    snapshot_id: str, effective: date, price_in: str, clouds=("commercial",)
) -> PriceSnapshot:
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
        for kind, price in _prices(price_in)  # type: ignore[assignment]
    ]
    return build_snapshot(
        snapshot_id=snapshot_id,
        source="provider_price_sheet",
        source_url="https://pricing.invalid/s",
        retrieval_date=date(2026, 10, 19),
        effective_date=effective,
        currency="USD",
        clouds=clouds,
        rows=rows,
    )


def test_newest_snapshot_effective_on_or_before_date_wins() -> None:
    store = InMemoryPriceSnapshotStore(
        [
            _sheet("s-2026-08", date(2026, 8, 1), "1"),
            _sheet("s-2026-10", date(2026, 10, 1), "2"),
            _sheet("s-2026-12", date(2026, 12, 1), "3"),
        ]
    )
    pick = store.resolve("commercial", date(2026, 10, 19))
    assert pick is not None and pick.snapshot_id == "s-2026-10"
    boundary = store.resolve("commercial", date(2026, 10, 1))
    assert boundary is not None and boundary.snapshot_id == "s-2026-10"
    early = store.resolve("commercial", date(2026, 7, 31))
    assert early is None


def test_older_snapshot_remains_resolvable_for_older_dates() -> None:
    store = InMemoryPriceSnapshotStore(
        [_sheet("s-a", date(2026, 8, 1), "1"), _sheet("s-b", date(2026, 10, 1), "2")]
    )
    got = store.resolve_token_price("commercial", *MODEL, date(2026, 9, 1))
    assert got is not None
    assert got.snapshot.snapshot_id == "s-a"
    assert got.rate.input == Decimal("1")


def test_ties_break_deterministically_by_id() -> None:
    store = InMemoryPriceSnapshotStore(
        [_sheet("s-a", date(2026, 10, 1), "1"), _sheet("s-b", date(2026, 10, 1), "2")]
    )
    got = store.resolve("commercial", date(2026, 10, 2))
    assert got is not None and got.snapshot_id == "s-b"


def test_cloud_without_applicable_snapshot_resolves_nothing() -> None:
    store = InMemoryPriceSnapshotStore([_sheet("s-a", date(2026, 10, 1), "1")])
    assert store.resolve("government", date(2026, 10, 19)) is None
    assert store.resolve_token_price("government", *MODEL, date(2026, 10, 19)) is None


def test_model_missing_from_newest_falls_back_to_older_snapshot_for_that_model() -> None:
    other = build_snapshot(
        snapshot_id="s-new",
        source="provider_price_sheet",
        source_url="https://pricing.invalid/s",
        retrieval_date=date(2026, 10, 19),
        effective_date=date(2026, 10, 15),
        currency="USD",
        clouds=("commercial",),
        rows=[
            PriceRow(
                service_name="s", sku_name="vm", unit_of_measure="1 Hour", retail_price=Decimal(1)
            )
        ],
    )
    store = InMemoryPriceSnapshotStore([_sheet("s-old", date(2026, 10, 1), "1"), other])
    got = store.resolve_token_price("commercial", *MODEL, date(2026, 10, 19))
    assert got is not None and got.snapshot.snapshot_id == "s-old"


def test_unknown_provider_or_model_is_unresolved_not_zero() -> None:
    store = InMemoryPriceSnapshotStore([_sheet("s-a", date(2026, 10, 1), "1")])
    assert store.resolve_token_price("commercial", None, "m", None, date(2026, 10, 19)) is None
    assert (
        store.resolve_token_price("commercial", "azure_openai", "nope", None, date(2026, 10, 19))
        is None
    )


def test_fixture_maps_to_ledger_price_version_per_million() -> None:
    snap = load_snapshot_file(FIXTURE_DIR / "retail-prices-synthetic-2026-10.json")
    version = snap.to_price_version()
    assert isinstance(version, PriceVersion)
    assert version.price_version_id == snap.snapshot_id
    assert version.effective_date == date(2026, 10, 1)
    rate = version.rate_for("azure_openai", "gpt-4.1-mini", "2025-04-14")
    assert rate is not None
    # 0.0004 per 1K tokens -> 0.4 per 1M tokens
    assert rate.input == Decimal("0.4")
    assert rate.output == Decimal("1.6")
    assert rate.cached == Decimal("0.1")
    nano = version.rate_for("azure_openai", "gpt-4.1-nano", "2025-04-14")
    assert nano is not None and nano.cached is None


def test_government_sheet_applies_only_to_government() -> None:
    gov = load_snapshot_file(FIXTURE_DIR / "provider-sheet-gov-synthetic-2026-10.json")
    store = InMemoryPriceSnapshotStore([gov])
    assert store.resolve("government", date(2026, 10, 19)) == gov
    assert store.resolve("commercial", date(2026, 10, 19)) is None
