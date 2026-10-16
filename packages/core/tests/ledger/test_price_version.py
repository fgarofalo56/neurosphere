"""Versioned price table: resolution by effective date; unresolved flagged and excluded."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from neurosphere_core.ledger import (
    InMemoryLedgerStore,
    PriceTable,
    StoreLedgerReader,
    TimeWindow,
    TokenCounts,
)
from neurosphere_core.ledger.service import CostLedger

from .builders import CATEGORY, CUSTOMER, WINDOW, D, obs, price_table

M = 1_000_000


def test_resolves_by_effective_date() -> None:
    table = price_table()
    early = table.resolve("prov-a", "model-x", None, date(2026, 8, 31))
    late = table.resolve("prov-a", "model-x", None, date(2026, 9, 1))
    assert early is not None and early.version.price_version_id == "pv-2026-01"
    assert late is not None and late.version.price_version_id == "pv-2026-09"
    assert table.resolve("prov-a", "model-x", None, date(2025, 12, 31)) is None  # before any sheet


def test_falls_back_to_an_older_version_that_has_the_model() -> None:
    table = price_table()
    found = table.resolve("prov-a", "model-y", "2", date(2026, 10, 1))
    assert found is not None and found.version.price_version_id == "pv-2026-01"
    assert table.resolve("prov-a", "model-y", "3", date(2026, 10, 1)) is None  # other version


def test_estimate_cites_version_and_uses_cached_rate_separately() -> None:
    tokens = TokenCounts(input=M, output=M, cached=M // 2)
    est = price_table().estimate_cost("prov-a", "model-x", None, tokens, date(2026, 8, 1))
    # input 0.5M * 2.00 + cached 0.5M * 0.50 + output 1M * 8.00
    assert est.amount == Decimal("1.00") + Decimal("0.25") + Decimal("8.00")
    assert est.price_version_id == "pv-2026-01" and est.currency == "USD"


def test_cached_is_not_folded_into_input() -> None:
    table = price_table()
    all_input = table.estimate_cost(
        "prov-a", "model-x", None, TokenCounts(input=M, output=0, cached=0), date(2026, 8, 1)
    )
    all_cached = table.estimate_cost(
        "prov-a", "model-x", None, TokenCounts(input=M, output=0, cached=M), date(2026, 8, 1)
    )
    assert all_input.amount == Decimal("2.00")
    assert all_cached.amount == Decimal("0.50")


@pytest.mark.parametrize(
    "tokens",
    [
        None,
        TokenCounts(),
        TokenCounts(input=10),
        TokenCounts(output=10),
        TokenCounts(input=10, output=10, cached=11),  # cached cannot exceed input
    ],
)
def test_unknown_or_inconsistent_tokens_give_null_not_zero(tokens: TokenCounts | None) -> None:
    est = price_table().estimate_cost("prov-a", "model-x", None, tokens, date(2026, 8, 1))
    assert est.resolved and est.amount is None
    assert est.price_version_id == "pv-2026-01"  # still cites the version it would have used


def test_cached_tokens_without_a_cached_rate_are_unknown() -> None:
    est = price_table().estimate_cost(
        "prov-a", "model-y", "2", TokenCounts(input=10, output=10, cached=5), date(2026, 8, 1)
    )
    assert est.amount is None


def test_zero_tokens_are_a_measured_zero() -> None:
    est = price_table().estimate_cost(
        "prov-a", "model-x", None, TokenCounts(input=0, output=0), date(2026, 8, 1)
    )
    assert est.amount == Decimal(0)


def test_unresolved_when_provider_or_model_unknown() -> None:
    table = price_table()
    tokens = TokenCounts(input=1, output=1)
    for provider, model in [(None, "model-x"), ("prov-a", None), ("nope", "model-x")]:
        est = table.estimate_cost(provider, model, None, tokens, date(2026, 10, 1))
        assert not est.resolved and est.amount is None and est.price_version_id is None


def test_duplicate_version_ids_are_rejected() -> None:
    version = price_table().versions[0]
    with pytest.raises(ValueError, match="duplicate"):
        PriceTable([version, version])


def test_float_never_enters_money() -> None:
    est = price_table().estimate_cost(
        "prov-a", "model-x", None, TokenCounts(input=3, output=7), date(2026, 8, 1)
    )
    assert isinstance(est.amount, Decimal)
    assert est.amount == D("0.000062")  # (3*2 + 7*8) / 1M exactly


async def test_unresolved_entry_is_flagged_excluded_and_coverage_reported() -> None:
    store = InMemoryLedgerStore()
    ledger = CostLedger(store)
    await ledger.record(CUSTOMER, "r1", CATEGORY, obs(1, amount="3.00"))
    await ledger.record(CUSTOMER, "r2", CATEGORY, obs(2, amount="1.00"))
    await ledger.record(CUSTOMER, "r3", CATEGORY, obs(3, amount=None, unresolved=True))

    entry = await StoreLedgerReader(store).get_entry(CUSTOMER, "r3", CATEGORY)
    assert entry is not None
    assert entry.price_unresolved and entry.authoritative_amount is None

    totals = await StoreLedgerReader(store).totals(CUSTOMER, WINDOW)
    # The unresolved entry has no currency: it has its own XXX bucket AND it lowers the coverage
    # of every real currency (it could belong to any), so USD is never presented as complete.
    assert totals["USD"].amount == D("4.00")  # excluded from the sum, not counted as 0
    assert totals["USD"].coverage == pytest.approx(2 / 3)
    assert not totals["USD"].complete
    assert totals["USD"].unresolved_count == 1
    assert totals["XXX"].amount is None
    assert (totals["XXX"].unresolved_count, totals["XXX"].unknown_count) == (1, 0)
    assert totals["XXX"].coverage == 0.0 and not totals["XXX"].complete


async def test_window_is_half_open_on_occurred_at() -> None:
    store = InMemoryLedgerStore()
    ledger = CostLedger(store)
    inside = datetime(2026, 10, 1, tzinfo=UTC)
    await ledger.record(CUSTOMER, "r1", CATEGORY, obs(1, amount="1.00", at=inside))
    reader = StoreLedgerReader(store)
    assert await reader.totals(CUSTOMER, TimeWindow(inside, inside)) == {}
    got = await reader.totals(CUSTOMER, TimeWindow(inside, datetime(2026, 10, 2, tzinfo=UTC)))
    assert got["USD"].amount == D("1.00")
