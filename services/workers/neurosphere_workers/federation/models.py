"""Federation wire and config models (PRP-21 item 3).

Only aggregates travel between cells: every model here carries counts and money totals per domain,
never an event, a ledger entry or a contribution. A cell is a domain/region deployment unit; the
registry is operator config, never request input.

Null discipline: an unknown count or amount is ``None``, never 0; ``estimated`` and ``invoiced``
amounts are separate rows and are never added together; a currency is never mixed with another.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Final, Literal
from urllib.parse import urlsplit

from neurosphere_core.aggregates.models import CostKind
from neurosphere_core.ledger.models import Money, quantize
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

__all__ = [
    "CellRef",
    "CellRegistry",
    "CellSummary",
    "CloudLiteral",
    "CostTotal",
    "DomainSummary",
    "combine_cost_totals",
    "combine_domain_summaries",
]

CloudLiteral = Literal["commercial", "government"]
_ID_PATTERN: Final = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CellRef(_Strict):
    """One registered cell. ``endpoint`` is an https base URL (operator config)."""

    cell_id: str = Field(pattern=_ID_PATTERN)
    cloud: CloudLiteral
    boundary_id: str = Field(pattern=_ID_PATTERN)
    endpoint: str = Field(min_length=1, max_length=2048)

    @field_validator("endpoint")
    @classmethod
    def _https_endpoint(cls, value: str) -> str:
        parts = urlsplit(value)
        if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
            raise ValueError("cell endpoint must be an https URL without credentials")
        return value


class CellRegistry(_Strict):
    cells: tuple[CellRef, ...] = ()

    @model_validator(mode="after")
    def _unique_ids(self) -> CellRegistry:
        ids = [c.cell_id for c in self.cells]
        if len(ids) != len(set(ids)):
            raise ValueError("cell ids must be unique")
        return self

    def get(self, cell_id: str) -> CellRef | None:
        for cell in self.cells:
            if cell.cell_id == cell_id:
                return cell
        return None


class CostTotal(_Strict):
    kind: CostKind
    currency: str = Field(pattern="^[A-Z]{3}$")
    amount: Money | None  # sum of the KNOWN parts; None when none is known
    complete: bool  # False when any input was unknown or partly known


class DomainSummary(_Strict):
    domain_id: str = Field(min_length=1)
    request_count: int | None = None  # None: no observation (unknown), never 0
    error_count: int | None = None
    unknown_outcome_count: int | None = None
    costs: tuple[CostTotal, ...] = ()
    complete: bool = False


class CellSummary(_Strict):
    """What a cell returns for the caller's derived scope."""

    cell_id: str
    cloud: CloudLiteral
    boundary_id: str
    customer_id: str
    scope_hash: str
    window_start: datetime
    window_end: datetime
    domains: tuple[DomainSummary, ...] = ()
    truncated: bool = False


def _add_known(values: list[int | None]) -> int | None:
    known = [v for v in values if v is not None]
    return sum(known) if known else None


def combine_cost_totals(totals: list[CostTotal]) -> tuple[CostTotal, ...]:
    """Merge rows per (kind, currency). Kinds and currencies are never mixed; unknown stays
    unknown (an all-unknown group is ``None``, a partly unknown one is incomplete)."""
    groups: dict[tuple[str, str], list[CostTotal]] = {}
    for total in totals:
        groups.setdefault((total.kind, total.currency), []).append(total)
    merged: list[CostTotal] = []
    for (_, _), rows in sorted(groups.items()):
        known = sorted(r.amount for r in rows if r.amount is not None)
        amount = quantize(sum(known, Decimal(0))) if known else None
        merged.append(
            CostTotal(
                kind=rows[0].kind,
                currency=rows[0].currency,
                amount=amount,
                complete=all(r.complete and r.amount is not None for r in rows),
            )
        )
    return tuple(merged)


def combine_domain_summaries(domain_id: str, rows: list[DomainSummary]) -> DomainSummary:
    """Combine several cells' rows for ONE domain (caller guarantees they share ``domain_id``)."""
    requests = _add_known([r.request_count for r in rows])
    return DomainSummary(
        domain_id=domain_id,
        request_count=requests,
        error_count=_add_known([r.error_count for r in rows]),
        unknown_outcome_count=_add_known([r.unknown_outcome_count for r in rows]),
        costs=combine_cost_totals([c for r in rows for c in r.costs]),
        complete=bool(rows) and all(r.complete for r in rows),
    )
