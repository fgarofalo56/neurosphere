"""Outbox subject -> ``Contribution`` (the facts one subject adds to the aggregates).

* ``model_call`` telemetry spans give latency and outcome. Other span kinds are not counted:
  an ``agent_run`` span and its child ``model_call`` spans describe the same work (the ledger
  mapping makes the same choice for cost).
* A ledger ENTRY gives cost facts (estimated and invoiced stay separate), the authoritative
  amount (the reference: one record per request, so a request seen by gateway, app and billing is
  counted once), coverage inputs and a per-source report.
* An ALLOCATION record (request-less, vendor/period spend) feeds reconciliation only. It is not a
  per-request cost, so it never enters the cost, coverage or reference series (no blending of
  granularities, no double counting against invoiced per-request entries).

Nothing here turns an unknown into 0: a missing duration, amount or currency stays ``None``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Final

from neurosphere_contracts.telemetry.v1.telemetry_event import TelemetryEvent
from neurosphere_core.aggregates import (
    UNASSIGNED_DOMAIN,
    AllocationFact,
    Contribution,
    CostFact,
    EntryFact,
    EventFact,
    SourceFact,
    format_fine,
)
from neurosphere_core.aggregates.models import CostKind, Granularity, SourceName
from neurosphere_core.ledger import AllocationRecord, LedgerEntry, Observation
from neurosphere_core.ledger.models import UNKNOWN_CURRENCY, format_time, quantize

ENTRY_PREFIX: Final = "entry-"
EVENT_PREFIX: Final = "event-"
ALLOCATION_PREFIX: Final = "alloc-"

_SOURCE_OF: Final[dict[str, SourceName]] = {
    "gateway": "gateway",
    "application": "app",
    "billing": "billing",
}


def entry_currency(entry: LedgerEntry) -> str:
    """The bucket ``compute_totals`` puts the entry in: its authoritative currency when the
    amount is known, else the one currency its sources agree on, else ``XXX``."""
    if entry.authoritative_amount is not None and entry.authoritative_currency:
        return entry.authoritative_currency
    currencies = {g.currency for g in entry.sources if g.currency is not None}
    return next(iter(currencies)) if len(currencies) == 1 else UNKNOWN_CURRENCY


def _domain(value: str | None) -> str:
    return value if value else UNASSIGNED_DOMAIN


def _cost_fact(entry: LedgerEntry, kind: CostKind) -> CostFact | None:
    groups = [g for g in entry.sources if g.kind == kind]
    if not groups:
        return None  # the entry has no component of this kind: not part of that series
    amount = entry.estimated_amount if kind == "estimated" else entry.invoiced_amount
    if amount is not None:
        currency = entry.estimated_currency if kind == "estimated" else entry.invoiced_currency
    else:
        agreed = {g.currency for g in groups if g.currency is not None}
        currency = next(iter(agreed)) if len(agreed) == 1 else None
    versions = sorted(
        {o.price_version_id for o in entry.observations if o.kind == kind and o.price_version_id}
    )
    return CostFact(kind=kind, currency=currency, amount=amount, price_version_ids=versions)


def _source_facts(entry: LedgerEntry, bucket: str) -> list[SourceFact]:
    by_source: dict[SourceName, list[Observation]] = {}
    for obs in entry.observations:
        by_source.setdefault(_SOURCE_OF[obs.observation_kind], []).append(obs)
    facts: list[SourceFact] = []
    for source in ("gateway", "app", "billing"):
        observations = by_source.get(source)
        if not observations:
            continue
        # Known only if EVERY observation of the source has an amount in the entry's currency.
        known = bucket != UNKNOWN_CURRENCY and all(
            o.amount is not None and o.currency == bucket for o in observations
        )
        amount = (
            quantize(sum((o.amount for o in observations if o.amount is not None), Decimal(0)))
            if known
            else None
        )
        facts.append(SourceFact(source=source, amount=amount, known=known))
    return facts


def contribution_from_entry(entry: LedgerEntry) -> Contribution:
    bucket = entry_currency(entry)
    billing = [o.observed_at for o in entry.observations if o.observation_kind == "billing"]
    costs = [
        fact for kind in ("estimated", "invoiced") if (fact := _cost_fact(entry, kind)) is not None
    ]
    return Contribution(
        id=ENTRY_PREFIX + entry.id,
        customer_id=entry.customer_id,
        domain_id=_domain(entry.domain_id),
        origin="ledger_entry",
        occurred_at=format_time(entry.occurred_at),
        observed_at=format_time(entry.observed_at),
        billing_observed_at=format_time(max(billing)) if billing else None,
        costs=costs,
        entry=EntryFact(
            currency=bucket,
            amount=entry.authoritative_amount,
            price_unresolved=entry.price_unresolved,
            sources=_source_facts(entry, bucket),
        ),
    )


def contribution_from_allocation(record: AllocationRecord) -> Contribution:
    granularity: Granularity = "vendor" if record.granularity == "vendor_period" else "unknown"
    source = _SOURCE_OF[record.observation_kind]
    observed = format_time(record.observed_at)
    return Contribution(
        id=ALLOCATION_PREFIX + record.id,
        customer_id=record.customer_id,
        domain_id=_domain(record.domain_id),
        origin="allocation",
        occurred_at=observed,
        observed_at=observed,
        billing_observed_at=observed if record.observation_kind == "billing" else None,
        allocation=AllocationFact(
            source=source,
            granularity=granularity,
            currency=record.currency
            if record.amount is not None and record.currency
            else (UNKNOWN_CURRENCY),
            amount=record.amount,
        ),
    )


def _utc(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(UTC)


def contribution_from_event(
    customer_id: str, doc_id: str, event: TelemetryEvent
) -> Contribution | None:
    """None for anything but a ``model_call`` span."""
    if event.span_kind != "model_call":
        return None
    moment = format_fine(_utc(event.event_time.root))
    return Contribution(
        id=EVENT_PREFIX + doc_id,
        customer_id=customer_id,
        domain_id=_domain(event.domain_id.root if event.domain_id else None),
        origin="event",
        occurred_at=moment,
        observed_at=moment,
        event=EventFact(duration_ms=event.duration_ms, outcome=event.outcome or "unknown"),
    )
