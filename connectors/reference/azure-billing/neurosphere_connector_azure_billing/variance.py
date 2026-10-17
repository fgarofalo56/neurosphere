"""Reconciliation variance report: billing aggregates compared with ledger ESTIMATES.

Pure function over inputs; no network, no clock, no storage.

Rules (PRP-09 clarification 9 and gotchas):

- The report is stated at the billing source's granularity. Azure cost exports report one row per
  usage day per resource per meter, so the finest honest comparison level is ``day_resource``;
  ``day`` rolls billing up further. Billing is never apportioned below the level the export
  reports, and the chosen level is written into the report (``comparison_level`` and
  ``granularity_statement``).
- This COMPARES; it never adds. Billing amounts and gateway/application observations describe
  the same requests, so no output field is a sum across the two sources. Within one source a
  roll-up (billing meters to billing day) is fine and keeps unknown as unknown.
- Unknown stays unknown: a ``None`` billing or estimate amount gives ``variance=None``, never 0.
  An estimate that is absent for a billing line is "no estimate" (``None``), not zero spend.
- Estimated vs invoiced is carried on every line (``billing_amount_kind``) and the ledger side is
  always labelled ``estimate``. Different currencies are not compared.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict

from neurosphere_connector_azure_billing.export_reader import (
    AmountKind,
    BillingAggregate,
    CostBasis,
)

__all__ = [
    "ComparisonLevel",
    "LedgerEstimate",
    "UnmatchedEstimate",
    "VarianceLine",
    "VarianceReport",
    "VarianceStatus",
    "build_variance_report",
]

ComparisonLevel = Literal["day", "day_resource"]
VarianceStatus = Literal[
    "compared",
    "billing_unknown",
    "estimate_unknown",
    "both_unknown",
    "no_estimate",
    "currency_mismatch",
]

_STATEMENTS: dict[str, str] = {
    "day": (
        "Billing source reports daily rows per resource per meter; this report rolls billing up "
        "to day (all resources) before comparing with ledger estimates at day."
    ),
    "day_resource": (
        "Billing source reports daily rows per resource per meter; this report rolls meters up "
        "to day per resource and compares with ledger estimates at day per resource. "
        "Nothing is apportioned below the billing granularity."
    ),
}
_NOTES = (
    "Compares only: billing and gateway/application observations are never summed.",
    "null amount = unknown, not 0; variance is null whenever either side is unknown.",
    "variance = billing - ledger estimate, in the shared currency.",
)


class LedgerEstimate(BaseModel):
    """A ledger ESTIMATE already bucketed by the caller to day (and optionally resource)."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    usage_date: date
    resource_id: str | None = None
    currency: str | None = None
    amount: Decimal | None = None


class VarianceLine(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    usage_date: date
    resource_id: str | None
    status: VarianceStatus
    billing_amount: Decimal | None
    billing_currency: str | None
    billing_amount_kind: AmountKind
    billing_basis: CostBasis
    estimate_amount: Decimal | None
    estimate_currency: str | None
    variance: Decimal | None
    variance_ratio: Decimal | None


class UnmatchedEstimate(BaseModel):
    """A ledger estimate day with no billing line at the comparison level (not a variance)."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    usage_date: date
    resource_id: str | None
    currency: str | None
    amount: Decimal | None


class VarianceReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    comparison_level: ComparisonLevel
    billing_basis: CostBasis
    billing_granularity: str
    granularity_statement: str
    lines: list[VarianceLine]
    billing_rows_other_basis_ignored: int
    unmatched_estimates: list[UnmatchedEstimate]
    notes: tuple[str, ...] = _NOTES


_BillKey = tuple[date, str | None, str | None, AmountKind]


def _rid(resource_id: str | None, level: ComparisonLevel) -> str | None:
    return None if level == "day" else resource_id


def _fold(resource_id: str | None) -> str | None:
    return None if resource_id is None else resource_id.casefold()


def _roll(amounts: list[Decimal | None]) -> Decimal | None:
    if any(a is None for a in amounts):
        return None
    return sum((a for a in amounts if a is not None), Decimal(0))


def build_variance_report(
    billing: Iterable[BillingAggregate],
    estimates: Iterable[LedgerEstimate],
    *,
    level: ComparisonLevel = "day_resource",
    basis: CostBasis = "actual",
) -> VarianceReport:
    """Compare ``basis`` billing aggregates with ledger estimates at ``level``."""
    ignored = 0
    bill_groups: dict[_BillKey, list[BillingAggregate]] = {}
    for b in billing:
        if b.basis != basis:
            ignored += 1
            continue
        key: _BillKey = (b.usage_date, _fold(_rid(b.resource_id, level)), b.currency, b.amount_kind)
        bill_groups.setdefault(key, []).append(b)

    est_groups: dict[tuple[date, str | None], list[LedgerEstimate]] = {}
    for e in estimates:
        est_groups.setdefault((e.usage_date, _fold(_rid(e.resource_id, level))), []).append(e)
    est_used: set[tuple[date, str | None]] = set()

    lines: list[VarianceLine] = []
    for key in sorted(bill_groups, key=lambda k: (k[0], k[1] or "", k[2] or "", k[3])):
        day, folded, currency, kind = key
        members = bill_groups[key]
        bill_amt = _roll([m.cost for m in members])
        shown_rid = _rid(members[0].resource_id, level)
        est_members = est_groups.get((day, folded))
        est_amt: Decimal | None = None
        est_cur: str | None = None
        status: VarianceStatus
        variance: Decimal | None = None
        ratio: Decimal | None = None
        if est_members is None:
            status = "no_estimate"
        else:
            est_used.add((day, folded))
            currencies = {e.currency for e in est_members}
            est_cur = next(iter(currencies)) if len(currencies) == 1 else None
            est_amt = _roll([e.amount for e in est_members])
            if est_cur is None or currency is None or est_cur != currency:
                status = "currency_mismatch"
                est_amt = est_amt if len(currencies) == 1 else None
            elif bill_amt is None and est_amt is None:
                status = "both_unknown"
            elif bill_amt is None:
                status = "billing_unknown"
            elif est_amt is None:
                status = "estimate_unknown"
            else:
                status = "compared"
                variance = bill_amt - est_amt
                ratio = None if est_amt == 0 else variance / est_amt
        lines.append(
            VarianceLine(
                usage_date=day,
                resource_id=shown_rid,
                status=status,
                billing_amount=bill_amt,
                billing_currency=currency,
                billing_amount_kind=kind,
                billing_basis=basis,
                estimate_amount=est_amt,
                estimate_currency=est_cur,
                variance=variance,
                variance_ratio=ratio,
            )
        )

    unmatched: list[UnmatchedEstimate] = []
    for ekey in sorted(est_groups, key=lambda k: (k[0], k[1] or "")):
        if ekey in est_used:
            continue
        group = est_groups[ekey]
        cur = {e.currency for e in group}
        single = len(cur) == 1
        unmatched.append(
            UnmatchedEstimate(
                usage_date=ekey[0],
                resource_id=_rid(group[0].resource_id, level),
                currency=next(iter(cur)) if single else None,
                amount=_roll([e.amount for e in group]) if single else None,
            )
        )

    return VarianceReport(
        comparison_level=level,
        billing_basis=basis,
        billing_granularity="day per resource per meter (as reported by the export)",
        granularity_statement=_STATEMENTS[level],
        lines=lines,
        billing_rows_other_basis_ignored=ignored,
        unmatched_estimates=unmatched,
    )
