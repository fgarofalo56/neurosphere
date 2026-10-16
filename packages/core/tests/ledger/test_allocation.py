"""Vendor/period allocation records stay apart from per-request entries."""

from __future__ import annotations

from datetime import date

from neurosphere_core.ledger import (
    AllocationParts,
    AllocationRecord,
    InMemoryLedgerStore,
    allocation_id,
)
from neurosphere_core.ledger.service import CostLedger

from .builders import CATEGORY, CUSTOMER, T0, WINDOW, D, billing, doc_id


def _record(n: int, **kw: object) -> AllocationRecord:
    fields: dict[str, object] = {
        "id": allocation_id(CUSTOMER, doc_id(n)),
        "customer_id": CUSTOMER,
        "granularity": "vendor_period",
        "observation_doc_id": doc_id(n),
        "observation_kind": "billing",
        "kind": "invoiced",
        "provider": "prov-a",
        "billing_period_start": date(2026, 10, 1),
        "billing_period_end": date(2026, 10, 31),
        "currency": "USD",
        "amount": D("1000.00"),
        "allocation": AllocationParts(ptu=D("600.00"), reservation=D("300.00")),
        "cloud": "commercial",
        "source_id": "src-1",
        "observed_at": T0,
        "period_end": date(2026, 10, 31),
    }
    fields.update(kw)
    return AllocationRecord(**fields)  # type: ignore[arg-type]


async def test_allocation_is_idempotent_and_never_becomes_an_entry() -> None:
    store = InMemoryLedgerStore()
    ledger = CostLedger(store)
    first = await ledger.record_allocation(_record(1))
    second = await ledger.record_allocation(_record(1))

    assert first == second and first.content_hash
    assert len(await store.list_allocations(CUSTOMER)) == 1
    assert await store.list_entries(CUSTOMER, WINDOW) == []  # not merged into any request entry


async def test_two_billing_lines_for_one_period_are_two_records() -> None:
    store = InMemoryLedgerStore()
    ledger = CostLedger(store)
    await ledger.record_allocation(_record(1))
    await ledger.record_allocation(_record(2, amount=D("50.00"), allocation=None))
    records = await store.list_allocations(CUSTOMER)
    assert len(records) == 2


def test_parts_are_separate_fields_and_unknown_stays_null() -> None:
    record = _record(1)
    assert record.allocation is not None
    assert record.allocation.ptu == D("600.00")
    assert record.allocation.reservation == D("300.00")
    assert record.allocation.compute is None and record.allocation.license_seat is None
    assert record.granularity == "vendor_period"


async def test_request_billing_with_allocation_does_not_fold_it_into_the_amount() -> None:
    store = InMemoryLedgerStore()
    change = await CostLedger(store).record(
        CUSTOMER,
        "r1",
        CATEGORY,
        billing(1, "10.00", allocation=AllocationParts(ptu=D("4.00"), license_seat=D("1.00"))),
    )
    entry = change.entry
    assert entry.authoritative_amount == D("10.00")  # not 10 + 4 + 1
    assert entry.allocation is not None and entry.allocation.ptu == D("4.00")
