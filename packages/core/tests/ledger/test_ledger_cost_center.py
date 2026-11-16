"""PRP-46: LedgerFilters.cost_center and hash stability for entries without one."""

from __future__ import annotations

from datetime import UTC, datetime

from neurosphere_core.ledger import LedgerFilters, Observation
from neurosphere_core.ledger.fold import fold_entry


def _obs(doc: str, cost_center: str | None) -> Observation:
    return Observation(
        observation_kind="gateway",
        doc_id=doc * 64,
        kind="estimated",
        amount=None,
        price_unresolved=True,
        observed_at=datetime(2026, 1, 1, tzinfo=UTC),
        cloud="commercial",
        source_id="src-1",
        cost_center=cost_center,
    )


def test_filter_matches_on_cost_center() -> None:
    entry = fold_entry("cust", "req", "tokens", [_obs("a", "CC-4410")])
    assert LedgerFilters(cost_center="CC-4410").matches(entry)
    assert not LedgerFilters(cost_center="CC-1").matches(entry)
    assert LedgerFilters().matches(entry)


def test_pre_change_entry_loads_and_keeps_hash() -> None:
    entry = fold_entry("cust", "req", "tokens", [_obs("a", None)])
    assert entry.cost_center is None
    legacy = entry.model_dump(mode="json")
    legacy.pop("cost_center")
    for obs in legacy["observations"]:
        obs.pop("cost_center")
    loaded = type(entry).model_validate(legacy)
    assert loaded.cost_center is None
    assert loaded.with_hash().content_hash == entry.content_hash
    assert LedgerFilters(cost_center="CC-1").matches(loaded) is False


def test_disagreement_is_none_and_single_carrier_wins() -> None:
    both = fold_entry("cust", "req", "tokens", [_obs("a", "CC-1"), _obs("b", "CC-2")])
    assert both.cost_center is None
    one = fold_entry("cust", "req", "tokens", [_obs("a", None), _obs("b", "CC-2")])
    assert one.cost_center == "CC-2"
