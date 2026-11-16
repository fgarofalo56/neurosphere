"""PRP-46: cost center on the ledger path, dropped-invoice counter, gateway pricing pin."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from neurosphere_core.ledger import DEFAULT_COST_CATEGORY, entry_id
from neurosphere_workers.ingestion.pipeline import process_batch
from neurosphere_workers.projections.outbox import CostLedgerSink
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader

from .support import Rig, cost_doc, model_call, raw_message, settings


async def _entry(rig: Rig, doc: dict[str, Any], request_id: str = "req-1") -> Any:
    found = await rig.store.read_entry(
        doc["customer_id"], entry_id(doc["customer_id"], request_id, DEFAULT_COST_CATEGORY)
    )
    assert found is not None
    return found.entry


async def test_single_carrier_sets_entry_cost_center() -> None:
    rig = Rig()
    gw = model_call("evt-gw")
    app = model_call("evt-app")
    batch = [
        raw_message(gw, 0, kind="telemetry", observation_kind="gateway", cost_center="CC-1"),
        raw_message(app, 1, kind="telemetry", observation_kind="application"),
    ]
    await process_batch(batch, rig.harness().deps(), settings())
    assert (await _entry(rig, gw)).cost_center == "CC-1"


async def test_agreeing_observations_keep_it_and_disagreeing_are_none() -> None:
    rig = Rig()
    gw = model_call("evt-gw")
    app = model_call("evt-app")
    same = [
        raw_message(gw, 0, kind="telemetry", observation_kind="gateway", cost_center="CC-1"),
        raw_message(app, 1, kind="telemetry", observation_kind="application", cost_center="CC-1"),
    ]
    await process_batch(same, rig.harness().deps(), settings())
    assert (await _entry(rig, gw)).cost_center == "CC-1"

    rig2 = Rig()
    gw2 = model_call("evt-gw2")
    app2 = model_call("evt-app2")
    differ = [
        raw_message(gw2, 0, kind="telemetry", observation_kind="gateway", cost_center="CC-1"),
        raw_message(app2, 1, kind="telemetry", observation_kind="application", cost_center="CC-2"),
    ]
    await process_batch(differ, rig2.harness().deps(), settings())
    assert (await _entry(rig2, gw2)).cost_center is None


async def test_entry_without_cost_center_keeps_legacy_hash() -> None:
    rig = Rig()
    gw = model_call("evt-gw")
    await process_batch(
        [raw_message(gw, 0, kind="telemetry", observation_kind="gateway")],
        rig.harness().deps(),
        settings(),
    )
    entry = await _entry(rig, gw)
    assert entry.cost_center is None
    payload = entry.model_dump(mode="json", exclude={"content_hash"})
    assert entry.content_hash == entry.model_copy().with_hash().content_hash
    assert payload["cost_center"] is None  # field exists, but is excluded from the hash


async def test_cost_record_cost_center_reaches_entry() -> None:
    rig = Rig()
    bill = cost_doc("cost-1", amount="2.00", kind="estimated", source="gateway")
    await process_batch(
        [
            raw_message(
                bill,
                0,
                kind="cost",
                observation_kind="gateway",
                request_id="req-1",
                cost_center="CC-9",
            )
        ],
        rig.harness().deps(),
        settings(),
    )
    assert (await _entry(rig, bill)).cost_center == "CC-9"


async def test_gateway_model_call_pricing_commercial_and_government() -> None:
    rig = Rig()
    priced = model_call("evt-c", request_id="req-c")
    deps = rig.harness().deps()
    await process_batch(
        [raw_message(priced, 0, kind="telemetry", observation_kind="gateway")], deps, settings()
    )
    commercial = await _entry(rig, priced, "req-c")
    assert commercial.estimated_amount == Decimal("6.00")

    # Government row: the price table does not cover it, so it is price_unresolved, not 0.
    unpriced = model_call("evt-u", request_id="req-u", model="gov-model-unpriced")
    await process_batch(
        [raw_message(unpriced, 2, kind="telemetry", observation_kind="gateway")],
        deps,
        settings(),
    )
    entry = await _entry(rig, unpriced, "req-u")
    assert entry.price_unresolved is True
    assert entry.estimated_amount is None


async def test_dropped_non_billing_invoiced_is_counted() -> None:
    reader = InMemoryMetricReader()
    provider = MeterProvider(metric_readers=[reader])
    rig = Rig()
    rig.sink = CostLedgerSink(
        rig.ledger, rig.writer, rig.sink._prices, meter=provider.get_meter("t")
    )
    bad = cost_doc("cost-bad", kind="invoiced", source="application")
    await process_batch(
        [raw_message(bad, 0, kind="cost", observation_kind="application", request_id="req-1")],
        rig.harness().deps(),
        settings(),
    )
    data = reader.get_metrics_data()
    assert data is not None
    metrics: list[Any] = [
        m for rm in data.resource_metrics for sm in rm.scope_metrics for m in sm.metrics
    ]
    dropped = next(m for m in metrics if m.name == "ns.outbox.cost_dropped")
    (point,) = dropped.data.data_points
    assert point.value == 1
    assert dict(point.attributes) == {"reason": "invoiced_not_billing"}
    provider.shutdown()
