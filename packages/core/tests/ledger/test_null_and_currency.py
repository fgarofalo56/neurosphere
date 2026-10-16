"""Null is unknown (never 0); totals group by ISO currency and report coverage."""

from __future__ import annotations

from decimal import Decimal

from hypothesis import given
from hypothesis import strategies as st
from neurosphere_core.ledger import LedgerFilters, compute_totals, fold_entry
from neurosphere_core.ledger.service import CostLedger, StoreLedgerReader
from neurosphere_core.ledger.store import InMemoryLedgerStore

from .builders import CATEGORY, CUSTOMER, WINDOW, D, gateway, obs


def test_never_sums_across_currencies() -> None:
    entries = [
        fold_entry(CUSTOMER, "r1", CATEGORY, [gateway(1, "10.00", currency="USD")]),
        fold_entry(CUSTOMER, "r2", CATEGORY, [gateway(2, "5.00", currency="EUR")]),
        fold_entry(CUSTOMER, "r3", CATEGORY, [gateway(3, "1.00", currency="USD")]),
    ]
    totals = compute_totals(entries)
    assert set(totals) == {"EUR", "USD"}
    assert totals["USD"].amount == D("11.00") and totals["EUR"].amount == D("5.00")


def test_partially_unknown_set_is_not_complete() -> None:
    entries = [
        fold_entry(CUSTOMER, "r1", CATEGORY, [gateway(1, "10.00")]),
        fold_entry(CUSTOMER, "r2", CATEGORY, [gateway(2, None)]),
    ]
    # The unknown entry has no currency of its own: it is reported under XXX, not hidden and not 0.
    totals = compute_totals(entries)
    assert totals["USD"].amount == D("10.00")
    assert totals["USD"].coverage == 0.5 and not totals["USD"].complete  # XXX could be USD
    assert totals["XXX"].amount is None and totals["XXX"].unknown_count == 1


def test_unknown_with_a_known_sibling_currency_lowers_that_currency_coverage() -> None:
    known = fold_entry(CUSTOMER, "r1", CATEGORY, [gateway(1, "10.00")])
    # Two spans of one request: one priced, one unknown -> group unknown, currency still USD.
    partial = fold_entry(CUSTOMER, "r2", CATEGORY, [gateway(2, "1.00"), gateway(3, None)])
    assert partial.authoritative_amount is None
    totals = compute_totals([known, partial])
    usd = totals["USD"]
    assert usd.amount == D("10.00")  # the partial entry is excluded, never counted as 0 or 1.00
    assert usd.coverage == 0.5 and not usd.complete
    assert (usd.known_count, usd.unknown_count, usd.entry_count) == (1, 1, 2)


async def test_filters_and_customer_scope() -> None:
    store = InMemoryLedgerStore()
    ledger = CostLedger(store)
    await ledger.record(CUSTOMER, "r1", CATEGORY, obs(1, amount="1.00"))
    await ledger.record(CUSTOMER, "r2", CATEGORY, obs(2, amount="2.00", model="other"))
    await ledger.record("cust-2", "r3", CATEGORY, obs(3, amount="100.00"))
    reader = StoreLedgerReader(store)

    everything = await reader.totals(CUSTOMER, WINDOW)
    only_x = await reader.totals(CUSTOMER, WINDOW, LedgerFilters(model="model-x"))

    assert everything["USD"].amount == D("3.00")  # cust-2 never leaks in
    assert only_x["USD"].amount == D("1.00")


@given(
    amounts=st.lists(
        st.one_of(st.none(), st.decimals(min_value=0, max_value=10_000, places=4)),
        min_size=1,
        max_size=12,
    )
)
def test_property_totals_over_partial_sets_report_coverage(amounts: list[Decimal | None]) -> None:
    # Sibling known span keeps the currency attributable to USD for the unknown entries.
    entries = []
    for i, amount in enumerate(amounts):
        items = [gateway(f"{i}-a", None if amount is None else str(amount))]
        if amount is None:
            items.append(gateway(f"{i}-b", "1.00"))  # known span + unknown span -> unknown
        entries.append(fold_entry(CUSTOMER, f"r{i}", CATEGORY, items))
    usd = compute_totals(entries)["USD"]
    known = [a for a in amounts if a is not None]
    assert usd.entry_count == len(amounts)
    assert usd.known_count == len(known)
    assert usd.coverage == len(known) / len(amounts)
    assert usd.unknown_count == len(amounts) - len(known)
    assert usd.complete == (len(known) == len(amounts))
    if known:
        assert usd.amount == sum(known, Decimal(0))
    else:
        assert usd.amount is None  # unknown, never 0
