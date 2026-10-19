"""Fold the day-grain reconciliation rollups of one domain into the response (pure, no I/O).

Input is item 1's ``ReconciliationPoint`` documents (one series per currency, one point per day).
Nothing here reads the ledger. Rules:

* Money is summed per currency only, in ``Decimal``; unknown (``None``) is never 0.
* The reference is the ledger amount, each request once (item 1 built it that way); the three
  sources are compared against it, not added to it.
* Variance is source minus reference and is unknown if either side is unknown.
* A source that reported on nothing in the window has unknown coverage, not 0.
* Request-less vendor/period allocations feed only the billing source (granularity ``vendor``)
  and are not in the reference, so a billing variance can be non-zero for that reason alone.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from typing import Final

from neurosphere_core.aggregates import (
    SOURCES,
    AggregateStatus,
    AggregateWindow,
    QueryResult,
    ReconciliationPoint,
    SourceRollup,
    format_bucket,
)
from neurosphere_core.aggregates.models import Granularity, SourceName
from neurosphere_core.ledger.models import UNKNOWN_CURRENCY

from neurosphere_api.reconciliation.models import (
    DISCLAIMER,
    REFERENCE_LABEL,
    Freshness,
    MetricValue,
    ReconciliationResponse,
    Reference,
    ReferenceLine,
    SourceLine,
    UnknownRemainder,
    Window,
)

_COARSENESS: Final[dict[Granularity, int]] = {"request": 0, "vendor": 1, "unknown": 2}


def _known_sum(values: Sequence[Decimal | None]) -> Decimal | None:
    known = [v for v in values if v is not None]
    return sum(known, Decimal(0)) if known else None


def _num(value: Decimal | None) -> float | None:
    return None if value is None else float(value)


def _has_data(rollup: SourceRollup) -> bool:
    return rollup.observed_entry_count > 0 or rollup.allocation_count > 0


def _source_line(
    source: SourceName,
    points: Sequence[ReconciliationPoint],
    currency: str | None,
    reference_amount: Decimal | None,
    reference_complete: bool,
    reference_entries: int,
) -> tuple[SourceLine, bool]:
    """One (source, currency) line and whether it is complete (full coverage, no unknown part)."""
    rollups = [r for p in points for r in p.sources if r.source == source]
    with_data = [r for r in rollups if _has_data(r)]
    amount = _known_sum([r.amount for r in with_data])
    observed = sum(r.observed_entry_count for r in rollups)
    known = sum(r.known_count for r in rollups)
    coverage = known / reference_entries if observed > 0 and reference_entries > 0 else None
    granularity: Granularity = (
        max((r.granularity for r in with_data), key=lambda g: _COARSENESS[g])
        if with_data
        else "unknown"
    )
    source_complete = (
        amount is not None
        and all(r.complete for r in with_data)
        # Vendor-only data (no observed entries) has no per-request coverage to fall short on.
        and (observed == 0 or (coverage is not None and coverage >= 1.0))
    )
    variance = None if amount is None or reference_amount is None else amount - reference_amount
    line = SourceLine(
        source=source,
        granularity=granularity,
        amount=MetricValue.of(_num(amount), complete=source_complete),
        coverage=MetricValue.of(coverage, complete=True),
        variance=MetricValue.of(_num(variance), complete=source_complete and reference_complete),
        currency=currency,
    )
    return line, source_complete


def build_response(
    domain_id: str,
    window: AggregateWindow,
    result: QueryResult,
    status: AggregateStatus | None,
    now: datetime,
) -> ReconciliationResponse:
    references: list[ReferenceLine] = []
    lines: list[SourceLine] = []
    all_complete = True
    for series in sorted(result.series, key=lambda s: s.key):
        points = [p for p in series.points if isinstance(p, ReconciliationPoint)]
        if not points:
            continue
        # XXX is the "currency could not be determined" bucket: reported with currency null.
        currency = None if points[0].currency == UNKNOWN_CURRENCY else points[0].currency
        reference_amount = _known_sum([p.reference_amount for p in points])
        entries = sum(p.reference_entry_count for p in points)
        unknown_entries = entries - sum(p.reference_known_count for p in points)
        reference_complete = all(p.complete for p in points)
        references.append(
            ReferenceLine(
                label=REFERENCE_LABEL,
                amount=MetricValue.of(_num(reference_amount), complete=reference_complete),
                currency=currency,
                entry_count=entries,
                unknown_entry_count=unknown_entries,
            )
        )
        all_complete = all_complete and reference_complete
        for source in SOURCES:
            line, source_ok = _source_line(
                source, points, currency, reference_amount, reference_complete, entries
            )
            lines.append(line)
            all_complete = all_complete and source_ok
    if not references:
        all_complete = False

    if len(references) == 1:
        only = references[0]
        reference = Reference(label=only.label, amount=only.amount, currency=only.currency)
        remainder = UnknownRemainder.of(float(only.unknown_entry_count), complete=True)
    else:
        # Zero currencies: nothing observed. Several: amounts and the shared XXX bucket cannot be
        # added across currencies, so the single contract-level fields stay unknown and the
        # per-currency ``references`` / ``sources`` entries carry the data.
        reference = Reference(
            label=REFERENCE_LABEL, amount=MetricValue.of(None, complete=False), currency=None
        )
        remainder = UnknownRemainder.of(None, complete=False)

    watermark = status.watermark if status else None
    lag = status.lag_seconds(now) if status else None
    return ReconciliationResponse(
        domain_id=domain_id,
        window=Window(start=format_bucket(window.start), end=format_bucket(window.end)),
        freshness=Freshness(
            watermark=watermark,
            lag_seconds=lag,
            billing_source_freshness=status.billing_observed_at if status else None,
        ),
        complete=all_complete and not result.truncated,
        truncated=result.truncated,
        reference=reference,
        references=references,
        sources=lines,
        unknown_remainder=remainder,
        disclaimer=DISCLAIMER,
    )
