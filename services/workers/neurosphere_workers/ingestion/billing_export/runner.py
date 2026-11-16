"""``BillingExportPoller``: one tick reads the Cost Management export and posts invoiced costs.

Each daily per-resource aggregate becomes one ``CostRecord`` (``kind=invoiced``,
``observation_source=billing``, ``billing_period`` = that usage day, ``usage_start``/``usage_end``
= that day's bounds) sent as a ``com.neurosphere.cost.v1`` CloudEvent through the ingest edge.
It carries no request id, so the ledger folds it into an ``AllocationRecord`` and the aggregates
report it as the reconciliation ``billing`` source (the outbox emits granularity
``vendor_period``, which the aggregates map to ``vendor``, the coarsest label the aggregate model
has for request-less billing). Nothing is apportioned below the export's day-per-resource
granularity.

Closed months only: an actual-cost export for the still-open billing month is not an invoice (late
usage restates those days), so only days whose calendar month (UTC, from the injectable clock) ended
before the current month are posted as ``invoiced``. The export rows carry no billing-period end, so
the calendar month is the rule. Open-month days are held back and counted in
``last_status.held_open_period``; they are never posted as ``estimated`` (that needs a price
version and billing has none). Restatement limit: the first amount posted for a closed day wins,
because ids exclude the amount. A later export that reports a different amount for the same
day, resource and meter is detected (in memory, per process), counted in
``last_status.restated`` and logged as ``billing_export.restated`` with counts only; it is not
posted. Superseding the invoiced amount is a ledger concept (follow-up, PRP-07 territory).

Rules:

* A null cost is never posted (``CostRecord.amount`` is required and 0 would be a lie). It is
  counted in ``last_status.skipped_null_cost``. A currency-less aggregate is skipped likewise.
* ``cost_id`` and ``dedupe_key`` are a hash of (source, domain, day, resource, meter, currency,
  basis) and exclude the amount and the export run, so re-reading the same or a later export
  yields the same ids and the pipeline dedupes on ``(customer_id, source_id, event_id)``.
  Limit: a later restatement of an already-ingested day keeps the first amount.
* The checkpoint is the SHA-256 of the manifest bytes of the last export fully posted. It is held
  in memory: a restart re-posts once, which the dedupe makes harmless. It advances only when the
  export was complete and every record was accepted. While open-period days were held, the
  checkpoint also records the (year, month) of the clock, so an unchanged manifest is skipped only
  within that month; once the clock enters a new month the export is re-read and the now-closed
  days are posted (already-posted days dedupe on their deterministic ids).

An upstream failure (blob 429/5xx, ingest 5xx) never raises out of :meth:`tick`; the next tick
retries.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any, Final, Protocol

from neurosphere_connector_azure_billing import BillingAggregate, BillingReadResult
from neurosphere_contracts.cost.v1.cost_record import CostRecord
from neurosphere_core.payload import CLOUDEVENT_TYPE_COST
from pydantic import ValidationError

from neurosphere_workers.ingestion.gateway_poll import IngestPostError

__all__ = [
    "STATUS_INCOMPLETE",
    "STATUS_INGEST_FAILED",
    "STATUS_OK",
    "STATUS_READ_FAILED",
    "STATUS_UNCHANGED",
    "BillingExportPoller",
    "BillingReader",
    "IngestPort",
    "TickStatus",
    "to_cost_record",
]

logger = logging.getLogger("neurosphere.workers.billing_export")

STATUS_OK: Final = "ok"
STATUS_UNCHANGED: Final = "unchanged"
STATUS_INCOMPLETE: Final = "incomplete"
STATUS_READ_FAILED: Final = "read_failed"
STATUS_INGEST_FAILED: Final = "ingest_failed"
_SCHEMA_VERSION: Final = "1.0.0"
_MAX_INTEGER_DIGITS: Final = 18
_FRACTION: Final = Decimal(1).scaleb(-12)


class BillingReader(Protocol):
    async def read(self) -> BillingReadResult: ...


class IngestPort(Protocol):
    async def post(self, events: Sequence[Mapping[str, Any]]) -> int: ...


@dataclass(slots=True)
class TickStatus:
    status: str = "idle"
    posted: int = 0
    skipped_null_cost: int = 0
    skipped_unmappable: int = 0
    rows_dropped_no_date: int = 0
    blobs_missing: tuple[str, ...] = ()
    held_open_period: int = 0
    restated: int = 0


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _amount(value: Decimal) -> str | None:
    """A ``DecimalAmount`` string, or None when it cannot be one (never rounds across 12 dp
    silently beyond what the contract allows, and never uses an exponent)."""
    if not value.is_finite():
        return None
    exponent = value.as_tuple().exponent
    quantized = value
    if isinstance(exponent, int) and exponent < -12:
        quantized = value.quantize(_FRACTION, rounding=ROUND_HALF_EVEN)
    text = format(quantized, "f")
    integer = text.lstrip("-").split(".", 1)[0]
    if len(integer) > _MAX_INTEGER_DIGITS:
        return None
    if text.startswith("-") and Decimal(text) == 0:
        text = text[1:]
    return text


def _key(source_id: str, domain_id: str, agg: BillingAggregate) -> str:
    parts = (
        source_id,
        domain_id,
        agg.usage_date.isoformat(),
        (agg.resource_id or "").casefold(),
        agg.meter_id or "",
        agg.currency or "",
        agg.basis,
    )
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()


def to_cost_record(
    agg: BillingAggregate,
    *,
    customer_id: str,
    cloud: str,
    source_id: str,
    domain_id: str,
    recorded_at: datetime,
) -> CostRecord | None:
    """One invoiced billing ``CostRecord`` for a daily aggregate; None when it has no known
    amount or currency (unknown stays unknown, it is never posted as 0)."""
    if agg.cost is None or agg.currency is None or agg.amount_kind != "invoiced":
        return None
    amount = _amount(agg.cost)
    if amount is None:
        return None
    day = agg.usage_date.isoformat()
    digest = _key(source_id, domain_id, agg)
    try:
        return CostRecord.model_validate(
            {
                "schema_version": _SCHEMA_VERSION,
                "cost_id": f"billing-{digest[:48]}",
                "kind": "invoiced",
                "amount": amount,
                "currency": agg.currency,
                "billing_period": {"start_date": day, "end_date": day},
                "usage_start": f"{day}T00:00:00Z",
                "usage_end": f"{day}T23:59:59Z",
                "cloud": cloud,
                "customer_id": customer_id,
                "domain_id": domain_id,
                "source_id": source_id,
                "dedupe_key": f"azure-billing:{digest}",
                "observation_source": "billing",
                "recorded_at": recorded_at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
        )
    except ValidationError:
        return None


def _cloud_event(record: CostRecord) -> dict[str, Any]:
    return {
        "specversion": "1.0",
        "id": record.cost_id.root,
        "source": "neurosphere/billing-export",
        "type": CLOUDEVENT_TYPE_COST,
        "datacontenttype": "application/json",
        "data": record.model_dump(mode="json", exclude_none=True),
    }


class BillingExportPoller:
    def __init__(
        self,
        *,
        reader: BillingReader,
        ingest: IngestPort,
        customer_id: str,
        cloud: str,
        source_id: str,
        domain_id: str,
        batch_size: int = 100,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._reader = reader
        self._ingest = ingest
        self._customer = customer_id
        self._cloud = cloud
        self._source_id = source_id
        self._domain_id = domain_id
        self._batch = batch_size
        self._clock = clock
        self._posted_manifest: str | None = None
        self._held_month: tuple[int, int] | None = None  # set while open-period days were held
        # Posted closed-day key (the id digest) -> the first amount accepted for it.
        self._posted_amounts: dict[str, str] = {}
        self.last_status = TickStatus()

    async def tick(self) -> None:
        status = TickStatus()
        self.last_status = status
        try:
            result = await self._reader.read()
        except Exception as exc:  # blob 429/5xx, bad export: retried next tick, never a crash
            logger.warning(
                "billing export read failed",
                extra={"event": "billing_export.read_failed", "error": type(exc).__name__},
            )
            status.status = STATUS_READ_FAILED
            return
        export = result.export
        status.rows_dropped_no_date = result.rows_dropped_no_date
        status.blobs_missing = export.blobs_missing
        now = self._clock().astimezone(UTC)
        month = (now.year, now.month)
        if (
            export.manifest_sha256
            and export.manifest_sha256 == self._posted_manifest
            and self._held_month in (None, month)
        ):
            status.status = STATUS_UNCHANGED
            return

        events: list[dict[str, Any]] = []
        fresh: dict[str, str] = {}
        for agg in result.aggregates:
            if agg.cost is None:
                status.skipped_null_cost += 1
                continue
            if (agg.usage_date.year, agg.usage_date.month) >= month:
                status.held_open_period += 1  # open billing month: not an invoice yet
                continue
            record = to_cost_record(
                agg,
                customer_id=self._customer,
                cloud=self._cloud,
                source_id=self._source_id,
                domain_id=self._domain_id,
                recorded_at=now,
            )
            if record is None:
                status.skipped_unmappable += 1
                continue
            digest = record.cost_id.root
            first = self._posted_amounts.get(digest)
            if first is not None and Decimal(first) != Decimal(record.amount.root):
                status.restated += 1  # first amount wins: counted, not posted
                continue
            fresh[digest] = record.amount.root
            events.append(_cloud_event(record))

        accepted_all = True
        try:
            for start in range(0, len(events), self._batch):
                chunk = events[start : start + self._batch]
                accepted = await self._ingest.post(chunk)
                status.posted += accepted
                accepted_all = accepted_all and accepted >= len(chunk)
        except IngestPostError as exc:
            logger.warning(
                "billing ingest post failed",
                extra={"event": "billing_export.ingest_failed", "status": exc.status},
            )
            status.status = STATUS_INGEST_FAILED
            return

        if status.rows_dropped_no_date or status.blobs_missing or not export.complete:
            logger.warning(
                "billing export incomplete or has dateless rows",
                extra={
                    "event": "billing_export.incomplete",
                    "rows_dropped_no_date": status.rows_dropped_no_date,
                    "blobs_missing": len(status.blobs_missing),
                    "complete": export.complete,
                },
            )
        if status.restated:
            logger.warning(
                "billing export restated closed days (first amount kept)",
                extra={"event": "billing_export.restated", "restated": status.restated},
            )
        if status.held_open_period:
            logger.info(
                "billing export open-period days held (closed months only; first amount wins)",
                extra={
                    "event": "billing_export.held_open_period",
                    "held_open_period": status.held_open_period,
                },
            )
        if not export.complete or not accepted_all:
            status.status = STATUS_INCOMPLETE if not export.complete else STATUS_INGEST_FAILED
            return  # no checkpoint: the next tick re-reads, replays are deduped
        for digest, amount in fresh.items():
            self._posted_amounts.setdefault(digest, amount)
        self._posted_manifest = export.manifest_sha256 or None
        self._held_month = month if status.held_open_period else None
        status.status = STATUS_OK
