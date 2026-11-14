"""A posted billing record reaches the reconciliation ``billing`` source (in-process, fakes).

Chain under test: role -> CloudEvent -> (edge stand-in: scope stamp, HubMessage) -> ingestion
``process_batch`` -> real ``CostLedgerSink`` (request-less => ``AllocationRecord``) -> aggregates
projection -> ``ReconciliationPoint``. The HTTP edge itself is covered by the API ingest tests.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any

from neurosphere_contracts.cost.v1.cost_record import CostRecord
from neurosphere_core.aggregates import ReconciliationPoint
from neurosphere_core.payload import HubMessage, HubMessageKind
from neurosphere_workers.aggregates.tests.support import Rig as AggregatesRig
from neurosphere_workers.aggregates.tests.support import wide_window
from neurosphere_workers.ingestion.models import RawMessage
from neurosphere_workers.ingestion.pipeline import process_batch
from neurosphere_workers.ingestion.settings import IngestionSettings
from outbox.support import Rig as LedgerRig  # type: ignore[import-not-found]

from .support import CUSTOMER, DOMAIN, SOURCE, default_source, make_poller


class EdgeStandIn:
    """What the ingest edge does to a cost CloudEvent, minus HTTP and auth."""

    def __init__(self, rig: LedgerRig) -> None:
        self.rig = rig
        self.harness = rig.harness()  # one marker store: replays are deduped
        self.offset = 0
        self.results: list[Any] = []

    async def post(self, events: Sequence[Mapping[str, Any]]) -> int:
        raws: list[RawMessage] = []
        for event in events:
            cost = CostRecord.model_validate(event["data"])  # the edge validates the contract
            assert cost.kind == "invoiced"
            message = HubMessage(
                kind=HubMessageKind.COST,
                event_id=cost.cost_id.root,
                cloud="commercial",
                customer_id=CUSTOMER,
                source_id=SOURCE,
                producer_id="azure-billing-export",
                received_at="2026-10-19T12:00:00Z",
                request_id=None,  # a billing export row carries no request id
                observation_kind="billing",  # stamped from the producer registration
                data=cost.model_dump(mode="json"),
            )
            raws.append(
                RawMessage(
                    body=message.to_bytes(),
                    partition_id="0",
                    offset=str(self.offset),
                    sequence_number=self.offset,
                    enqueued_time=self.rig_time(),
                )
            )
            self.offset += 1
        self.results.append(await process_batch(raws, self.harness.deps(), IngestionSettings()))
        return len(events)

    @staticmethod
    def rig_time() -> Any:
        from datetime import UTC, datetime

        return datetime(2026, 10, 19, 12, 0, 0, tzinfo=UTC)


async def test_billing_export_surfaces_as_reconciliation_billing_source() -> None:
    ledger = LedgerRig()
    edge = EdgeStandIn(ledger)
    poller = make_poller(default_source(), edge)
    await poller.tick()
    assert sum(r.accepted for r in edge.results) == 3
    assert all(not r.quarantined for r in edge.results)

    allocations = await ledger.store.list_allocations(CUSTOMER)
    assert len(allocations) == 3
    assert {a.granularity for a in allocations} == {"vendor_period"}
    assert {a.observation_kind for a in allocations} == {"billing"}
    assert {a.kind for a in allocations} == {"invoiced"}
    assert sum(a.amount for a in allocations if a.amount is not None) == Decimal("9.10")

    agg = AggregatesRig()
    for allocation in allocations:
        await agg.add_allocation(allocation)
    assert (await agg.drain()).ok
    result = await agg.aggregates.query(
        CUSTOMER, DOMAIN, "reconciliation", "day", wide_window(agg), max_series=20, max_points=720
    )
    assert [s.key for s in result.series] == ["USD"]
    points = [p for p in result.series[0].points if isinstance(p, ReconciliationPoint)]
    by_day: dict[str, Decimal | None] = {}
    for point in points:
        billing = next(s for s in point.sources if s.source == "billing")
        assert billing.granularity == "vendor"  # request-less billing: no request-level claim
        assert billing.coverage is None  # unknown, not 0
        by_day[str(point.bucket_start)[:10]] = billing.amount
    assert by_day == {"2026-10-10": Decimal("5.10"), "2026-10-11": Decimal("4.00")}


async def test_replayed_export_is_deduped_by_the_pipeline() -> None:
    ledger = LedgerRig()
    edge = EdgeStandIn(ledger)
    source = default_source()
    poller = make_poller(source, edge)
    await poller.tick()
    source.manifest = source.manifest.replace(b'"blobCount"', b'"runId": "2", "blobCount"')
    await poller.tick()  # a new export run with the same days: same ids
    assert sum(r.accepted for r in edge.results) == 3
    assert sum(r.duplicates for r in edge.results) == 3
    assert len(await ledger.store.list_allocations(CUSTOMER)) == 3
