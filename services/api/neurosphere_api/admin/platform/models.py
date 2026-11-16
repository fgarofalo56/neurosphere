"""Response models of the platform admin API (PRP-44).

Defined here, not the generated contract classes: a contract model used as ``response_model``
renames ``openapi.json`` components. Price rows are never returned by list or get (a sheet is
summarised; the rows stay in the snapshot store).
"""

from __future__ import annotations

from typing import Any, Final

from neurosphere_contracts.admin.v1.admin_config_document import AdminConfigDocument
from neurosphere_contracts.admin.v1.budget import SpendBudget
from neurosphere_contracts.admin.v1.domain_definition import DomainDefinition
from neurosphere_core.admin.platform import (
    CoverageReport,
    PolicyChange,
    PriceSheetResult,
    ReviewPolicyRead,
    ReviewPolicyWrite,
)
from neurosphere_core.pricing.models import PriceSnapshot
from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "BudgetPage",
    "BudgetView",
    "ChangeView",
    "CoverageView",
    "DomainPage",
    "DomainView",
    "PriceSheetPage",
    "PriceSheetUploadView",
    "PriceSheetView",
    "ReviewPolicyView",
    "ReviewPolicyWriteView",
    "budget_view",
    "coverage_view",
    "domain_view",
    "policy_view",
    "policy_write_view",
    "sheet_view",
    "upload_view",
]

MAX_PAGE_LIMIT: Final = 200


class _View(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DomainView(_View):
    domain_id: str
    display_name: str
    classification: str
    residency_region: str
    status: str
    is_control_domain: bool
    version: int
    updated_at: str
    updated_by: str
    #: True when this create also registered the reserved control domain.
    control_registered: bool = False


class DomainPage(_View):
    items: list[DomainView]


class BudgetView(_View):
    budget_id: str
    domain_id: str
    period: str
    amount: str
    currency: str
    thresholds_percent: list[int]
    tags_filter: dict[str, str] | None
    status: str
    version: int
    updated_at: str
    updated_by: str


class BudgetPage(_View):
    items: list[BudgetView]


class PriceSheetView(_View):
    snapshot_id: str
    source: str
    source_url: str
    retrieval_date: str
    effective_date: str
    currency: str
    clouds: list[str]
    synthetic: bool
    content_hash: str
    row_count: int
    notes: str


class IncompleteModelView(_View):
    provider: str
    model: str
    model_version: str | None
    missing: list[str]


class CoverageView(_View):
    snapshot_id: str
    rows: int
    models_priced: int
    models_incomplete: list[IncompleteModelView]
    rows_without_token_meter: int
    warnings: list[str]


class PriceSheetUploadView(_View):
    sheet: PriceSheetView
    coverage: CoverageView
    #: False when the same sheet (equal content hash) was already stored.
    created: bool


class PriceSheetPage(_View):
    items: list[PriceSheetView]


class ChangeView(_View):
    path: str
    before: Any = None
    after: Any = None


class ReviewPolicyView(_View):
    #: ``stored`` or ``defaults`` (nothing stored yet).
    source: str
    version: int
    policy_version: str
    document: dict[str, Any]


class ReviewPolicyWriteView(ReviewPolicyView):
    before: dict[str, Any]
    changes: list[ChangeView] = Field(default_factory=list)


def domain_view(document: AdminConfigDocument, *, control_registered: bool = False) -> DomainView:
    body = document.body
    assert isinstance(body, DomainDefinition)
    return DomainView(
        domain_id=body.domain_id.root,
        display_name=body.display_name.root,
        classification=body.classification,
        residency_region=body.residency_region,
        status=document.status,
        is_control_domain=body.is_control_domain,
        version=document.version.root,
        updated_at=document.updated_at.root,
        updated_by=document.updated_by.root,
        control_registered=control_registered,
    )


def budget_view(document: AdminConfigDocument) -> BudgetView:
    body = document.body
    assert isinstance(body, SpendBudget)
    tags = body.tags_filter.root if body.tags_filter is not None else None
    return BudgetView(
        budget_id=body.budget_id.root,
        domain_id=body.domain_id.root,
        period=body.period,
        amount=body.amount.root,
        currency=body.currency.root,
        thresholds_percent=[t.root for t in body.thresholds_percent],
        tags_filter=None if tags is None else {k: v.root for k, v in tags.items()},
        status=document.status,
        version=document.version.root,
        updated_at=document.updated_at.root,
        updated_by=document.updated_by.root,
    )


def sheet_view(snapshot: PriceSnapshot) -> PriceSheetView:
    return PriceSheetView(
        snapshot_id=snapshot.snapshot_id,
        source=snapshot.source,
        source_url=snapshot.source_url,
        retrieval_date=snapshot.retrieval_date.isoformat(),
        effective_date=snapshot.effective_date.isoformat(),
        currency=snapshot.currency,
        clouds=list(snapshot.clouds),
        synthetic=snapshot.synthetic,
        content_hash=snapshot.content_hash,
        row_count=len(snapshot.rows),
        notes=snapshot.notes,
    )


def coverage_view(report: CoverageReport) -> CoverageView:
    return CoverageView(
        snapshot_id=report.snapshot_id,
        rows=report.rows,
        models_priced=report.models_priced,
        models_incomplete=[
            IncompleteModelView(
                provider=m.provider,
                model=m.model,
                model_version=m.model_version,
                missing=list(m.missing),
            )
            for m in report.models_incomplete
        ],
        rows_without_token_meter=report.rows_without_token_meter,
        warnings=list(report.warnings),
    )


def upload_view(result: PriceSheetResult) -> PriceSheetUploadView:
    return PriceSheetUploadView(
        sheet=sheet_view(result.snapshot),
        coverage=coverage_view(result.coverage),
        created=result.created,
    )


def _change(change: PolicyChange) -> ChangeView:
    return ChangeView(path=change.path, before=change.before, after=change.after)


def policy_view(read: ReviewPolicyRead) -> ReviewPolicyView:
    return ReviewPolicyView(
        source=read.source,
        version=read.version,
        policy_version=read.document.policy_version,
        document=read.document.model_dump(mode="json"),
    )


def policy_write_view(write: ReviewPolicyWrite) -> ReviewPolicyWriteView:
    return ReviewPolicyWriteView(
        source="stored",
        version=write.stored.version.root,
        policy_version=write.after.policy_version,
        document=write.after.model_dump(mode="json"),
        before=write.before.model_dump(mode="json"),
        changes=[_change(c) for c in write.changes],
    )
