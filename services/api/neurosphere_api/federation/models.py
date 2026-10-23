"""Response models of the federation API (PRP-21 item 3).

The per-cell wire models (``CellSummary``, ``DomainSummary``, ``CostTotal``) live with the cell
worker in ``neurosphere_workers.federation``; the merged view adds only cell outcomes and totals.
Unknown is ``None`` (never 0) and estimated/invoiced are separate rows.
"""

from datetime import datetime
from typing import Literal

from neurosphere_workers.federation import CloudLiteral, CostTotal, DomainSummary
from pydantic import BaseModel, ConfigDict

__all__ = ["CellOutcome", "MergedSummary"]


class CellOutcome(BaseModel):
    """How one cell contributed. ``denied``: the cell derived no access for the caller;
    ``unavailable``: the cell failed or timed out (the merged summary is then incomplete)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    cell_id: str
    state: Literal["ok", "denied", "unavailable"]


class MergedSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    cloud: CloudLiteral
    boundary_id: str
    customer_id: str
    window_start: datetime
    window_end: datetime
    cells: tuple[CellOutcome, ...]
    domains: tuple[DomainSummary, ...]
    totals: tuple[CostTotal, ...]
    complete: bool
    truncated: bool
