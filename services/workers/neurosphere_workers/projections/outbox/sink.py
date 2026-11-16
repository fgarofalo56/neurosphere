"""``CostLedgerSink``: the ``LedgerSink`` item 2 calls for EVERY accepted event.

Order inside ``accept`` (each step idempotent, so a crash anywhere is repaired by redelivery,
because the normalizer marks the event accepted LAST):

1. ledger upsert (observation keyed by ``doc_id``; the entry is recomputed from the full set),
2. outbox ``event`` entry (id = event ``doc_id``),
3. outbox ``ledger_change`` entry (id = hash(entry id + content hash)).

A repeat after a crash between 1 and 2/3 finds the ledger unchanged but still writes the missing
outbox entries. The ledger-change entry is written even when the ledger did not change on this
call, for exactly that reason. No cross-item transaction is assumed (the Cosmos vNext emulator
has none).
"""

from __future__ import annotations

import logging

from neurosphere_core.ledger import AllocationRecord, CostLedger, PriceTable
from neurosphere_core.ledger.models import format_time
from opentelemetry import metrics as otel_metrics
from opentelemetry.metrics import Meter

from neurosphere_workers.ingestion.models import NormalizedEvent
from neurosphere_workers.projections.outbox.mapping import (
    RequestObservation,
    dropped_reason,
    map_event,
)
from neurosphere_workers.projections.outbox.models import OutboxEntry, event_outbox_id
from neurosphere_workers.projections.outbox.writer import OutboxWriter

_log = logging.getLogger(__name__)
METRIC_OUTBOX_COST_DROPPED = "ns.outbox.cost_dropped"


class CostLedgerSink:
    def __init__(
        self,
        ledger: CostLedger,
        outbox: OutboxWriter,
        prices: PriceTable,
        meter: Meter | None = None,
    ) -> None:
        self._ledger = ledger
        self._outbox = outbox
        self._prices = prices
        # Created once per sink, not per event (#167 pattern).
        self._dropped = (
            meter or otel_metrics.get_meter("neurosphere_workers.outbox")
        ).create_counter(METRIC_OUTBOX_COST_DROPPED, unit="{event}")
        self._logged_reasons: set[str] = set()

    async def accept(self, event: NormalizedEvent) -> None:
        mapped = map_event(event, self._prices)
        state = None
        if mapped is None:
            reason = dropped_reason(event)
            if reason is not None:
                self._dropped.add(1, {"reason": reason})
                if (
                    reason not in self._logged_reasons
                ):  # once per sink; literal text, never the record
                    self._logged_reasons.add(reason)
                    _log.warning("outbox dropped non-billing invoiced cost records")
        if isinstance(mapped, RequestObservation):
            change = await self._ledger.record(
                mapped.customer_id, mapped.request_id, mapped.cost_category, mapped.observation
            )
            state = change.entry
        elif isinstance(mapped, AllocationRecord):
            state = await self._ledger.record_allocation(mapped)
        await self._outbox.write_event(
            OutboxEntry(
                id=event_outbox_id(event.doc_id),
                customer_id=event.message.customer_id,
                kind="event",
                ref_id=event.doc_id,
                entity="event",
                source_id=event.message.source_id,
                request_id=event.message.request_id,
                event_kind=event.message.kind.value,
                occurred_at=format_time(event.event_time),
            )
        )
        if state is not None:
            await self._outbox.write_ledger_change(state)
