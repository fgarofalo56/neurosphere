"""One entry per (customer, request, category); order- and redelivery-independent."""

from __future__ import annotations

import itertools
from decimal import Decimal

from hypothesis import given
from hypothesis import strategies as st
from neurosphere_core.ledger import (
    CostLedger,
    InMemoryLedgerStore,
    StoreLedgerReader,
    entry_id,
    fold_entry,
)

from .builders import CATEGORY, CUSTOMER, REQUEST, WINDOW, application, billing, gateway, obs


async def _record_all(ledger: CostLedger, observations: list) -> None:  # type: ignore[type-arg]
    for o in observations:
        await ledger.record(CUSTOMER, REQUEST, CATEGORY, o)


async def test_three_observations_make_one_entry_invoiced_authoritative() -> None:
    store = InMemoryLedgerStore()
    ledger = CostLedger(store)
    await _record_all(ledger, [gateway(1, "1.00"), application(2, "0.90"), billing(3, "1.20")])

    entries = await store.list_entries(CUSTOMER, WINDOW)
    assert len(entries) == 1
    entry = entries[0]
    assert entry.id == entry_id(CUSTOMER, REQUEST, CATEGORY)
    assert len(entry.observations) == 3
    assert {o.observation_kind for o in entry.observations} == {"gateway", "application", "billing"}
    assert entry.authoritative_source == "billing"
    assert entry.authoritative_kind == "invoiced"
    assert entry.authoritative_amount == Decimal("1.20")
    # The three amounts are evidence; they are never summed (1.00 + 0.90 + 1.20 = 3.10).
    assert entry.authoritative_amount != Decimal("3.10")
    assert entry.estimated_amount == Decimal("1.00")  # gateway-metered beats application
    assert entry.invoiced_amount == Decimal("1.20")


async def test_gateway_beats_application_when_no_invoice() -> None:
    entry = fold_entry(CUSTOMER, REQUEST, CATEGORY, [application(1, "0.90"), gateway(2, "1.00")])
    assert (entry.authoritative_source, entry.authoritative_amount) == ("gateway", Decimal("1.00"))
    assert entry.invoiced_amount is None


async def test_every_arrival_order_gives_the_identical_entry() -> None:
    items = [gateway(1, "1.00"), application(2, "0.90"), billing(3, "1.20")]
    results = set()
    for order in itertools.permutations(items):
        store = InMemoryLedgerStore()
        await _record_all(CostLedger(store), list(order))
        stored = await store.read_entry(CUSTOMER, entry_id(CUSTOMER, REQUEST, CATEGORY))
        assert stored is not None
        results.add(stored.entry.model_dump_json())
    assert len(results) == 1


async def test_redelivery_adds_nothing() -> None:
    store = InMemoryLedgerStore()
    ledger = CostLedger(store)
    first = await ledger.record(CUSTOMER, REQUEST, CATEGORY, gateway(1))
    await ledger.record(CUSTOMER, REQUEST, CATEGORY, billing(3))
    writes = store.entry_writes

    again = await ledger.record(CUSTOMER, REQUEST, CATEGORY, gateway(1))
    again_billing = await ledger.record(CUSTOMER, REQUEST, CATEGORY, billing(3))

    assert first.changed
    assert not again.changed and not again_billing.changed
    assert store.entry_writes == writes
    assert len(again.entry.observations) == 2


async def test_same_request_other_customer_or_category_is_a_separate_entry() -> None:
    store = InMemoryLedgerStore()
    ledger = CostLedger(store)
    a = await ledger.record(CUSTOMER, REQUEST, CATEGORY, gateway(1))
    b = await ledger.record("cust-2", REQUEST, CATEGORY, gateway(2))
    c = await ledger.record(CUSTOMER, REQUEST, "other", gateway(3))
    assert len({a.entry.id, b.entry.id, c.entry.id}) == 3
    reader = StoreLedgerReader(store)
    assert await reader.get_entry("cust-2", REQUEST, CATEGORY) == b.entry


async def test_etag_contention_is_retried_then_succeeds() -> None:
    store = InMemoryLedgerStore()
    store.fail_next_writes = 2
    change = await CostLedger(store).record(CUSTOMER, REQUEST, CATEGORY, gateway(1))
    assert change.changed and store.entry_writes == 1


async def test_permanent_contention_raises_transient() -> None:
    import pytest
    from neurosphere_core.errors import DependencyTransientError

    store = InMemoryLedgerStore()
    store.fail_next_writes = 99
    with pytest.raises(DependencyTransientError):
        await CostLedger(store, max_attempts=3).record(CUSTOMER, REQUEST, CATEGORY, gateway(1))


def test_spans_of_one_source_sum_and_unknown_makes_the_group_unknown() -> None:
    summed = fold_entry(CUSTOMER, REQUEST, CATEGORY, [gateway(1, "1.00"), gateway(2, "0.25")])
    assert summed.authoritative_amount == Decimal("1.25")
    assert summed.sources[0].observation_count == 2

    unknown = fold_entry(CUSTOMER, REQUEST, CATEGORY, [gateway(1, "1.00"), gateway(2, None)])
    assert unknown.authoritative_amount is None
    assert unknown.sources[0].unknown_count == 1


_amounts = st.one_of(st.none(), st.decimals(min_value=0, max_value=1000, places=4))


@st.composite
def _observation_sets(draw):  # type: ignore[no-untyped-def]
    n = draw(st.integers(min_value=1, max_value=7))
    items = []
    for i in range(n):
        source = draw(st.sampled_from(["gateway", "application", "billing"]))
        amount = draw(_amounts)
        text = None if amount is None else str(amount)
        if source == "billing":
            items.append(billing(i, text))
        else:
            items.append(obs(i, source=source, amount=text))
    return items


@given(data=_observation_sets(), seed=st.randoms(use_true_random=False))
def test_property_any_permutation_and_duplication_is_identical(data, seed) -> None:  # type: ignore[no-untyped-def]
    baseline = fold_entry(CUSTOMER, REQUEST, CATEGORY, data)
    shuffled = list(data) + list(data[: len(data) // 2 + 1])  # redeliveries
    seed.shuffle(shuffled)
    again = fold_entry(CUSTOMER, REQUEST, CATEGORY, shuffled)
    assert again == baseline
    assert again.model_dump_json() == baseline.model_dump_json()
    assert len(again.observations) == len(data)
