"""Models of the saved-reports API (PRP-19 item 5).

A stored report is a chart PLAN plus a bounded ``StructuredQuery``; it never holds result data
(``chart_plan.spec.data.values`` is stored empty). Rows are produced on every run, under the
viewer's own server-derived scope.

No ``from __future__ import annotations``: FastAPI inspects these models.
"""

from datetime import datetime
from typing import Annotated, Any, Final, Literal

from neurosphere_contracts.query.v1.structured_query import StructuredQuery
from pydantic import BaseModel, ConfigDict, Field, StrictStr

__all__ = [
    "MAX_SHARES",
    "CitationView",
    "DecisionBody",
    "Publication",
    "PublicationState",
    "ReportBody",
    "ReportList",
    "ReportView",
    "RunView",
    "ShareBody",
    "StoredReport",
]

MAX_SHARES: Final = 50

PublicationState = Literal["none", "pending", "approved", "rejected"]
Metric = Literal["cost", "latency", "errors"]
Title = Annotated[StrictStr, Field(min_length=1, max_length=200, pattern=r"^[^\x00-\x1f]+$")]
PrincipalId = Annotated[
    StrictStr, Field(min_length=3, max_length=512, pattern=r"^[A-Za-z0-9:._/=-]+$")
]


class Publication(BaseModel):
    """Add-to-UI workflow state. ``approved`` requires a different principal with
    ``config.manage``; any change to the report resets it to ``none``."""

    model_config = ConfigDict(extra="forbid")

    state: PublicationState = "none"
    requested_by: str | None = None
    requested_at: datetime | None = None
    decided_by: str | None = None
    decided_at: datetime | None = None
    reason: str | None = None


class StoredReport(BaseModel):
    """The persisted document. ``etag`` is assigned by the store."""

    model_config = ConfigDict(extra="forbid")

    id: str
    customer_id: str
    domain_id: str
    owner: str
    title: str
    chart_plan: dict[str, Any]
    query_spec: dict[str, Any]
    metric: Metric = "cost"
    shares: list[str] = Field(default_factory=list[str])
    publication: Publication = Field(default_factory=Publication)
    created_at: datetime
    updated_at: datetime
    etag: str | None = None


class ReportBody(BaseModel):
    """Create / replace body. ``chart_plan`` is validated by the server chart validator."""

    model_config = ConfigDict(extra="forbid")

    title: Title
    chart_plan: dict[str, Any]
    query_spec: StructuredQuery
    metric: Metric = "cost"


class ShareBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    principal_id: PrincipalId


class DecisionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["approve", "reject"]
    reason: Annotated[StrictStr, Field(max_length=500, pattern=r"^[^\x00-\x1f]*$")] | None = None


class ReportView(BaseModel):
    """Wire shape of a stored report (no result data). ``shares`` is empty for non-owners."""

    model_config = ConfigDict(extra="forbid")

    id: str
    domain_id: str
    owner: str
    title: str
    chart_plan: dict[str, Any]
    query_spec: dict[str, Any]
    metric: Metric
    shares: list[str]
    publication: Publication
    created_at: datetime
    updated_at: datetime
    etag: str
    is_owner: bool = False
    can_decide_publication: bool = False


class ReportList(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[ReportView]
    next_cursor: str | None = None


class CitationView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    record_id: str
    kind: str
    source: str
    as_of: str | None
    freshness: Literal["fresh", "stale", "unknown"]


class RunView(BaseModel):
    """Output of one run. ``chart_plan`` has ``data.values`` filled from the VIEWER's records;
    it is ``None`` when the viewer's scope yields no rows (``status`` = ``no_data``)."""

    model_config = ConfigDict(extra="forbid")

    report_id: str
    status: Literal["ok", "no_data"]
    chart_plan: dict[str, Any] | None
    citations: list[CitationView]
    truncated: bool
    ran_at: datetime
    etag: str
