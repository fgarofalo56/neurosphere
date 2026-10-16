"""item 2's ``process_batch`` driving the real ``CostLedgerSink`` (item 2 fakes for the rest)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from neurosphere_core.ledger import (
    DEFAULT_COST_CATEGORY,
    TimeWindow,
    entry_id,
)
from neurosphere_workers.ingestion.fakes import SimulatedCrash
from neurosphere_workers.ingestion.pipeline import process_batch

from .support import (
    Rig,
    cost_doc,
    model_call,
    raw_message,
    settings,
)


def _window():  # type: ignore[no-untyped-def]
    from datetime import UTC, datetime

    return TimeWindow(datetime(2026, 1, 1, tzinfo=UTC), datetime(2027, 1, 1, tzinfo=UTC))


async def _entry(rig: Rig, doc, request_id: str = "req-1"):  # type: ignore[no-untyped-def]
    return await rig.store.read_entry(
        doc["customer_id"], entry_id(doc["customer_id"], request_id, DEFAULT_COST_CATEGORY)
    )


async def test_gateway_application_and_billing_make_one_entry() -> None:
    rig = Rig()
    harness = rig.harness()
    gw = model_call("evt-gw")
    app = model_call("evt-app", tokens={"input": 1_000_000, "output": 0})
    bill = cost_doc("cost-1", amount="9.99")
    batch = [
        raw_message(gw, 0, kind="telemetry", observation_kind="gateway"),
        raw_message(app, 1, kind="telemetry", observation_kind="application"),
        raw_message(bill, 2, kind="cost", observation_kind="billing", request_id="req-1"),
    ]

    result = await process_batch(batch, harness.deps(), settings())

    assert result.accepted == 3 and result.quarantined_total == 0
    stored = await _entry(rig, gw)
    assert stored is not None
    entry = stored.entry
    assert len(entry.observations) == 3
    assert entry.authoritative_source == "billing"
    assert entry.authoritative_amount == Decimal("9.99")
    # gateway: 1M input * 2.00 + 0.5M output * 8.00 = 6.00 (estimated, cites its price version)
    assert entry.estimated_amount == Decimal("6.00")
    assert entry.price_version_ids == ["pv-synthetic-1"]
    kinds = [e.kind for e in rig.outbox_store.entries(gw["customer_id"])]
    assert kinds.count("event") == 3
    assert kinds.count("ledger_change") == 3  # one per distinct entry state


async def test_only_model_call_spans_are_cost_observations() -> None:
    rig = Rig()
    harness = rig.harness()
    run = model_call("evt-run", span_kind="agent_run")
    call = model_call("evt-call")
    no_request = model_call("evt-nr", request_id=None)

    await process_batch(
        [
            raw_message(run, 0, kind="telemetry", observation_kind="gateway"),
            raw_message(call, 1, kind="telemetry", observation_kind="gateway"),
            raw_message(no_request, 2, kind="telemetry", observation_kind="gateway"),
        ],
        harness.deps(),
        settings(),
    )

    stored = await _entry(rig, call)
    assert stored is not None and len(stored.entry.observations) == 1  # agent_run not counted
    assert len(await rig.store.list_entries(call["customer_id"], _window())) == 1
    events = [e for e in rig.outbox_store.entries(call["customer_id"]) if e.kind == "event"]
    assert len(events) == 3  # every accepted event still reaches the outbox


async def test_unknown_tokens_are_null_and_unpriced_model_is_flagged() -> None:
    rig = Rig()
    harness = rig.harness()
    unknown = model_call("evt-u", "req-u", tokens={"input": None, "output": 5})
    unpriced = model_call("evt-p", "req-p", model="mystery-model")

    await process_batch(
        [
            raw_message(unknown, 0, kind="telemetry", observation_kind="gateway"),
            raw_message(unpriced, 1, kind="telemetry", observation_kind="gateway"),
        ],
        harness.deps(),
        settings(),
    )

    u = await _entry(rig, unknown, "req-u")
    p = await _entry(rig, unpriced, "req-p")
    assert u is not None and p is not None
    assert u.entry.authoritative_amount is None and not u.entry.price_unresolved
    assert u.entry.price_version_ids == ["pv-synthetic-1"]
    assert p.entry.price_unresolved and p.entry.price_version_ids == []
    assert p.entry.authoritative_amount is None


async def test_billing_without_request_id_is_a_vendor_period_allocation() -> None:
    rig = Rig()
    harness = rig.harness()
    bill = cost_doc("cost-agg", amount="500.00")

    await process_batch(
        [raw_message(bill, 0, kind="cost", observation_kind="billing", request_id=None)],
        harness.deps(),
        settings(),
    )

    records = await rig.store.list_allocations(bill["customer_id"])
    assert len(records) == 1
    record = records[0]
    assert record.granularity == "vendor_period" and record.amount == Decimal("500.00")
    assert str(record.billing_period_end) == "2026-10-31"
    assert await rig.store.list_entries(bill["customer_id"], _window()) == []
    changes = [
        e for e in rig.outbox_store.entries(bill["customer_id"]) if e.kind == "ledger_change"
    ]
    assert [c.entity for c in changes] == ["allocation"]


@pytest.mark.parametrize("crash_in", ["event", "ledger_change"])
async def test_crash_between_ledger_upsert_and_outbox_write_then_redelivery(
    crash_in: str,
) -> None:
    rig = Rig()
    harness = rig.harness()
    gw = model_call("evt-crash")
    batch = [raw_message(gw, 0, kind="telemetry", observation_kind="gateway")]

    real_event, real_change = rig.writer.write_event, rig.writer.write_ledger_change

    async def crash_event(entry):  # type: ignore[no-untyped-def]
        raise SimulatedCrash

    async def crash_change(state):  # type: ignore[no-untyped-def]
        raise SimulatedCrash

    if crash_in == "event":
        rig.writer.write_event = crash_event  # type: ignore[method-assign]
    else:
        rig.writer.write_ledger_change = crash_change  # type: ignore[method-assign]
    with pytest.raises(SimulatedCrash):
        await process_batch(batch, harness.deps(), settings())

    # The ledger upsert happened; the event was not marked accepted (marker is LAST).
    assert await _entry(rig, gw) is not None
    assert not harness.markers.marked

    rig.writer.write_event, rig.writer.write_ledger_change = real_event, real_change  # type: ignore[method-assign]
    result = await process_batch(batch, harness.deps(), settings())  # redelivery

    assert result.accepted == 1 and result.duplicates == 0
    stored = await _entry(rig, gw)
    assert stored is not None and len(stored.entry.observations) == 1  # no double effect
    assert rig.store.entry_writes == 1
    outbox = rig.outbox_store.entries(gw["customer_id"])
    assert sorted(e.kind for e in outbox) == ["event", "ledger_change"]  # exactly one of each

    # A second redelivery of the already accepted event is a duplicate: still nothing new.
    await process_batch(batch, harness.deps(), settings())
    assert len(rig.outbox_store.entries(gw["customer_id"])) == 2


async def test_redelivery_of_an_earlier_event_after_later_ones_changes_nothing() -> None:
    rig = Rig()
    harness = rig.harness()
    gw = model_call("evt-a")
    bill = cost_doc("cost-b", amount="2.00")
    first = raw_message(gw, 0, kind="telemetry", observation_kind="gateway")
    second = raw_message(bill, 1, kind="cost", observation_kind="billing", request_id="req-1")
    await process_batch([first, second], harness.deps(), settings())
    before = (await _entry(rig, gw)).entry.model_dump_json()  # type: ignore[union-attr]
    outbox_before = len(rig.outbox_store.entries(gw["customer_id"]))

    # Bypass the accepted marker to model a crash-induced re-call of the sink itself.
    harness.markers.marked.clear()
    await process_batch([first, second], harness.deps(), settings())

    after = (await _entry(rig, gw)).entry.model_dump_json()  # type: ignore[union-attr]
    assert before == after
    assert len(rig.outbox_store.entries(gw["customer_id"])) == outbox_before
