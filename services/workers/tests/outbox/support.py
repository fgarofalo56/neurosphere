"""Builders for the outbox tests (synthetic data only). Reuses the ingestion test harness."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from ingestion.support import (  # type: ignore[import-not-found]
    T0,
    Doc,
    Harness,
    hub_message,
    raw_from_bytes,
    rich_cost,
    rich_telemetry,
    telemetry_at,
    ts,
)
from neurosphere_core.ledger import (
    CostLedger,
    InMemoryLedgerStore,
    ModelRate,
    PriceTable,
    PriceVersion,
    Rate,
)
from neurosphere_workers.ingestion.models import RawMessage
from neurosphere_workers.ingestion.settings import IngestionSettings
from neurosphere_workers.projections.outbox import (
    CostLedgerSink,
    InMemoryCheckpointStore,
    InMemoryOutboxStore,
    OutboxReader,
    OutboxWriter,
)

__all__ = ["T0", "Harness", "Rig", "settings"]


def settings(**kwargs: Any) -> IngestionSettings:
    return IngestionSettings(**kwargs)


PROVIDER, MODEL = "prov-a", "model-x"


def price_table() -> PriceTable:
    return PriceTable(
        [
            PriceVersion(
                price_version_id="pv-synthetic-1",
                effective_date=date(2026, 1, 1),
                currency="USD",
                source="synthetic",
                rates=[
                    ModelRate(
                        provider=PROVIDER,
                        model=MODEL,
                        rate=Rate(
                            input=Decimal("2.00"), output=Decimal("8.00"), cached=Decimal("0.50")
                        ),
                    )
                ],
            )
        ]
    )


class Rig:
    """A LedgerSink wired to in-memory stores, plus everything a test inspects."""

    def __init__(self) -> None:
        self.store = InMemoryLedgerStore()
        self.outbox_store = InMemoryOutboxStore()
        self.checkpoints = InMemoryCheckpointStore()
        self.writer = OutboxWriter(self.outbox_store)
        self.ledger = CostLedger(self.store)
        self.sink = CostLedgerSink(self.ledger, self.writer, price_table())
        self.reader = OutboxReader(self.outbox_store, self.checkpoints, batch_size=2)

    def harness(self) -> Harness:
        harness = Harness()
        deps = harness.deps()
        deps.ledger = self.sink
        harness.deps = lambda: deps  # type: ignore[method-assign]
        return harness


def model_call(
    event_id: str,
    request_id: str | None = "req-1",
    *,
    tokens: dict[str, int | None] | None = None,
    model: str = MODEL,
    span_kind: str = "model_call",
    **extra: Any,
) -> Doc:
    doc = telemetry_at(rich_telemetry(), event_id, T0)
    doc.pop("model_version", None)
    doc.pop("retry_attempt", None)  # unreported unless a test passes retry_attempt=...
    doc.update(
        span_kind=span_kind,
        provider=PROVIDER,
        model=model,
        token_breakdown=tokens if tokens is not None else {"input": 1_000_000, "output": 500_000},
        **extra,
    )
    if request_id is None:
        doc.pop("request_id", None)
    else:
        doc["request_id"] = request_id
    return doc


def cost_doc(
    cost_id: str,
    *,
    kind: str = "invoiced",
    amount: str = "1.20",
    source: str = "billing",
    **extra: Any,
) -> Doc:
    doc = rich_cost()
    doc.update(cost_id=cost_id, kind=kind, amount=amount, currency="USD", observation_source=source)
    if kind == "invoiced":
        doc["billing_period"] = {"start_date": "2026-10-01", "end_date": "2026-10-31"}
        doc.pop("price_version", None)
        doc.pop("price_effective_date", None)
    else:
        doc.pop("billing_period", None)
        doc.pop("invoice_id", None)
        doc.update(price_version="pv-synthetic-1", price_effective_date="2026-01-01")
    for key in ("allocation", "retry_count", "retry_amount", "reconciliation", "event_ids"):
        doc.pop(key, None)
    doc.update(extra)
    return doc


def raw_message(doc: Doc, offset: int, *, kind: str, **overrides: Any) -> RawMessage:
    return raw_from_bytes(hub_message(doc, kind, **overrides).to_bytes(), offset)


__all__ += ["cost_doc", "model_call", "price_table", "raw_message", "ts"]
