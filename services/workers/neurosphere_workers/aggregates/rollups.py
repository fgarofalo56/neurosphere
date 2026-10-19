"""Pure rollups: contributions of ONE bucket -> aggregate documents. No I/O, no clock.

Null discipline: sums use ``_known_sum`` (explicit filtering of ``None``, never a ``sum()`` that
could coerce one), a total over partially unknown inputs keeps the known sum with
``complete=False``, and a total over only unknown inputs is ``None``. A source with no
observations has ``coverage=None`` (unknown), not 0.

Unattributed currency: inputs whose currency cannot be determined sit in the ``XXX`` bucket and,
exactly like ``ledger.totals.compute_totals``, also count (as missing) against every real
currency's series, so a total is never presented as complete while they exist.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal
from typing import Final

from neurosphere_core.aggregates import (
    AggregateDoc,
    Contribution,
    CostFact,
    CostPoint,
    CoveragePoint,
    EntryFact,
    ErrorPoint,
    Grain,
    LatencyPoint,
    PriceVersionRef,
    ReconciliationPoint,
    SourceRollup,
    aggregate_doc_id,
    format_bucket,
)
from neurosphere_core.aggregates.models import AllocationFact, CostKind, Granularity, SourceName
from neurosphere_core.ledger.models import UNKNOWN_CURRENCY, quantize

ERROR_OUTCOMES: Final = frozenset({"error", "timeout"})
_COARSENESS: Final[dict[Granularity, int]] = {"request": 0, "vendor": 1, "unknown": 2}


def known_sum(values: Iterable[Decimal | None]) -> Decimal | None:
    """Sum of the non-None values; ``None`` when there is none. Never treats None as 0."""
    known = sorted(v for v in values if v is not None)
    return quantize(sum(known, Decimal(0))) if known else None


def percentile(sorted_values: Sequence[int], p: int) -> int | None:
    """Nearest-rank percentile of an ascending list; ``None`` for an empty list."""
    if not sorted_values:
        return None
    rank = max(1, math.ceil(p * len(sorted_values) / 100))
    return sorted_values[rank - 1]


def _watermark(contributions: Iterable[Contribution]) -> str | None:
    values = [c.observed_at for c in contributions]
    return max(values) if values else None


def _with_unattributed[T](by_currency: Mapping[str, list[T]]) -> dict[str, list[T]]:
    """Per-currency groups where XXX members also count against every real currency."""
    unattributed = by_currency.get(UNKNOWN_CURRENCY, [])
    return {
        currency: items if currency == UNKNOWN_CURRENCY else [*items, *unattributed]
        for currency, items in sorted(by_currency.items())
    }


def rollup_bucket(
    customer_id: str,
    domain_id: str,
    grain: Grain,
    start: datetime,
    contributions: Sequence[Contribution],
    price_dates: Mapping[str, date] | None = None,
) -> list[AggregateDoc]:
    """All metrics of one (customer, domain, grain, bucket). Empty input gives no documents."""
    ordered = sorted(contributions, key=lambda c: c.id)
    stamp = format_bucket(start)
    ctx = _Ctx(customer_id, domain_id, grain, stamp)
    docs: list[AggregateDoc] = [
        *_cost(ctx, ordered, price_dates or {}),
        *_latency_and_errors(ctx, ordered),
        *_coverage(ctx, ordered),
        *_reconciliation(ctx, ordered),
    ]
    return sorted(docs, key=lambda d: (d.metric, d.series_key))


class _Ctx:
    def __init__(self, customer_id: str, domain_id: str, grain: Grain, start: str) -> None:
        self.customer_id = customer_id
        self.domain_id = domain_id
        self.grain: Grain = grain
        self.start = start

    def doc_id(self, metric: str, series_key: str) -> str:
        return aggregate_doc_id(
            self.customer_id, self.domain_id, metric, self.grain, self.start, series_key
        )

    def base(self, metric: str, series_key: str, watermark: str | None, complete: bool) -> dict:  # type: ignore[type-arg]
        return {
            "id": self.doc_id(metric, series_key),
            "customer_id": self.customer_id,
            "domain_id": self.domain_id,
            "grain": self.grain,
            "bucket_start": self.start,
            "series_key": series_key,
            "watermark": watermark,
            "complete": complete,
        }


# --------------------------------------------------------------------------- cost


def _cost(
    ctx: _Ctx, contributions: Sequence[Contribution], price_dates: Mapping[str, date]
) -> list[AggregateDoc]:
    docs: list[AggregateDoc] = []
    kinds: tuple[CostKind, ...] = ("estimated", "invoiced")
    for kind in kinds:
        items = [(c, f) for c in contributions for f in c.costs if f.kind == kind]
        by_currency: dict[str, list[tuple[Contribution, CostFact]]] = {}
        for item in items:
            by_currency.setdefault(item[1].currency or UNKNOWN_CURRENCY, []).append(item)
        for currency, group in _with_unattributed(by_currency).items():
            own = by_currency[currency]
            known = [f for _, f in own if f.amount is not None]
            ids = sorted({v for _, f in own for v in f.price_version_ids})
            refs = [PriceVersionRef(id=v, effective_date=price_dates.get(v)) for v in ids]
            complete = len(known) == len(group)
            docs.append(
                CostPoint(
                    **ctx.base(
                        "cost", f"{kind}:{currency}", _watermark(c for c, _ in group), complete
                    ),
                    kind=kind,
                    currency=currency,
                    amount=known_sum(f.amount for f in known),
                    entry_count=len(group),
                    known_count=len(known),
                    price_versions=refs,
                )
            )
    return docs


# --------------------------------------------------------------------------- latency, errors


def _latency_and_errors(ctx: _Ctx, contributions: Sequence[Contribution]) -> list[AggregateDoc]:
    events = [c for c in contributions if c.event is not None]
    if not events:
        return []
    watermark = _watermark(events)
    durations = sorted(
        c.event.duration_ms for c in events if c.event and c.event.duration_ms is not None
    )
    missing = len(events) - len(durations)
    known = [c for c in events if c.event and c.event.outcome != "unknown"]
    unknown_outcomes = len(events) - len(known)
    errors = sum(1 for c in known if c.event and c.event.outcome in ERROR_OUTCOMES)
    return [
        LatencyPoint(
            **ctx.base("latency", "latency", watermark, missing == 0),
            sample_count=len(durations),
            missing_count=missing,
            p50_ms=percentile(durations, 50),
            p95_ms=percentile(durations, 95),
            p99_ms=percentile(durations, 99),
        ),
        ErrorPoint(
            **ctx.base("errors", "errors", watermark, unknown_outcomes == 0),
            request_count=len(known),
            unknown_count=unknown_outcomes,
            error_count=errors if known else None,
            error_rate=errors / len(known) if known else None,
        ),
    ]


# --------------------------------------------------------------------------- coverage


def _entries_by_currency(
    contributions: Sequence[Contribution],
) -> dict[str, list[tuple[Contribution, EntryFact]]]:
    by_currency: dict[str, list[tuple[Contribution, EntryFact]]] = {}
    for c in contributions:
        if c.entry is not None:
            by_currency.setdefault(c.entry.currency, []).append((c, c.entry))
    return by_currency


def _coverage(ctx: _Ctx, contributions: Sequence[Contribution]) -> list[AggregateDoc]:
    by_currency = _entries_by_currency(contributions)
    docs: list[AggregateDoc] = []
    for currency, group in _with_unattributed(by_currency).items():
        own = by_currency[currency]
        known = [e for _, e in own if e.amount is not None]
        missing = [e for _, e in group if e.amount is None]
        unresolved = sum(1 for e in missing if e.price_unresolved)
        docs.append(
            CoveragePoint(
                **ctx.base(
                    "coverage",
                    currency,
                    _watermark(c for c, _ in group),
                    len(known) == len(group),
                ),
                currency=currency,
                entry_count=len(group),
                known_count=len(known),
                unresolved_count=unresolved,
                unknown_count=len(missing) - unresolved,
                coverage=len(known) / len(group),
                amount=known_sum(e.amount for e in known),
            )
        )
    return docs


# --------------------------------------------------------------------------- reconciliation


def _source_rollup(
    source: SourceName,
    entries: Sequence[tuple[Contribution, EntryFact]],
    allocations: Sequence[AllocationFact],
) -> SourceRollup:
    facts = [sf for _, e in entries for sf in e.sources if sf.source == source]
    known_facts = [sf for sf in facts if sf.known]
    parts = [sf.amount for sf in known_facts] + [a.amount for a in allocations]
    unknown_parts = (len(facts) - len(known_facts)) + sum(
        1 for a in allocations if a.amount is None
    )
    levels: list[Granularity] = []
    if facts:
        levels.append("request")
    levels.extend(a.granularity for a in allocations)
    granularity: Granularity = max(levels, key=lambda g: _COARSENESS[g]) if levels else "unknown"
    amount = known_sum(parts)
    return SourceRollup(
        source=source,
        granularity=granularity,
        observed_entry_count=len(facts),
        known_count=len(known_facts),
        allocation_count=len(allocations),
        amount=amount,
        # No observed entries means coverage is UNKNOWN, not 0.
        coverage=len(known_facts) / len(entries) if facts and entries else None,
        complete=amount is not None and unknown_parts == 0,
    )


def _reconciliation(ctx: _Ctx, contributions: Sequence[Contribution]) -> list[AggregateDoc]:
    by_currency = _entries_by_currency(contributions)
    allocs: dict[str, list[tuple[Contribution, AllocationFact]]] = {}
    for c in contributions:
        if c.allocation is not None:
            allocs.setdefault(c.allocation.currency, []).append((c, c.allocation))
    seeded: dict[str, list[tuple[Contribution, EntryFact]]] = {
        currency: by_currency.get(currency, []) for currency in sorted({*by_currency, *allocs})
    }
    docs: list[AggregateDoc] = []
    for currency, group in _with_unattributed(seeded).items():
        own = seeded[currency]
        known = [e for _, e in own if e.amount is not None]
        members = [c for c, _ in group] + [c for c, _ in allocs.get(currency, [])]
        sources = [
            _source_rollup(
                source, group, [a for _, a in allocs.get(currency, []) if a.source == source]
            )
            for source in ("gateway", "app", "billing")
        ]
        docs.append(
            ReconciliationPoint(
                **ctx.base(
                    "reconciliation",
                    currency,
                    _watermark(members),
                    bool(group) and len(known) == len(group),
                ),
                currency=currency,
                reference_amount=known_sum(e.amount for e in known),
                reference_entry_count=len(group),
                reference_known_count=len(known),
                sources=sources,
            )
        )
    return docs
