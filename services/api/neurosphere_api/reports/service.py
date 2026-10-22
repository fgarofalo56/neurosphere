"""Saved-report use cases (PRP-19 item 5).

Route dependencies (``require``) check the domain permission against the server-derived scope;
this service adds the per-report rules:

* read / run -- owner, a share principal, or (once approved) any ``data.read`` holder of the
  domain; everyone else gets 404 (a report you cannot see does not exist for you). A config
  reviewer may READ the definition of a pending publication, never run it.
* mutate (update, delete, share, request publication) -- owner only (403 ``not_owner`` for a
  viewer who can see it). Any change to plan or query resets publication to ``none``.
* decide publication -- ``config.manage`` in the domain, a principal other than the owner and
  the requester (``self_approval_refused``).
* run -- the plan is re-validated, then the stored ``StructuredQuery`` runs through the bounded
  tool registry with the VIEWER's scope (never the owner's). Rows become ``data.values``; the
  filled plan is validated again before it leaves.
"""

import uuid
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any, Final

from fastapi import HTTPException
from neurosphere_core.auth.scope import Permission, permits
from neurosphere_core.charts import validate_chart_plan
from neurosphere_core.copilot.tools import ToolRegistry, ToolResult
from neurosphere_core.errors import ForbiddenError, StaleVersionError
from neurosphere_core.paging import Page
from neurosphere_core.scope import IdentityScope

from neurosphere_api.reports.cache import RunCache, run_cache_key
from neurosphere_api.reports.models import (
    MAX_SHARES,
    CitationView,
    DecisionBody,
    Publication,
    PublicationState,
    ReportBody,
    ReportView,
    RunView,
    StoredReport,
)
from neurosphere_api.reports.plan import (
    build_rows,
    check_template,
    fill_plan,
    numeric_fields,
    strip_data,
)
from neurosphere_api.reports.store import DEFAULT_LIMIT, ReportStore, report_modified

__all__ = ["ReportService", "expected_etag", "principal_of", "tool_for"]

Clock = Callable[[], datetime]
SHARE_LIMIT_REASON: Final = "share_limit_reached"


def _utc_now() -> datetime:
    return datetime.now(UTC)


def principal_of(scope: IdentityScope) -> str:
    return scope.to_contract().principal.principal_id.root


def not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="not found")


def expected_etag(header: str, stored: str | None) -> str:
    """The header value matched to the stored ETag form (quoted or not); a different version is
    passed through so the comparison fails with ``stale_version``."""
    value = header.strip().removeprefix("W/")
    if stored is not None:
        for candidate in (value, f'"{value}"', value.strip('"')):
            if candidate == stored:
                return stored
    return value


def tool_for(query_spec: Mapping[str, Any]) -> str:
    """The bounded registry tool that executes a stored query. Never free-form text."""
    if query_spec.get("operation") == "aggregate":
        return "get_cost_summary"
    if query_spec.get("entity") == "recommendation":
        return "list_recommendations"
    return "search_catalog"


class ReportService:
    def __init__(
        self,
        store: ReportStore,
        registry: ToolRegistry,
        *,
        clock: Clock = _utc_now,
        id_factory: Callable[[], str] = lambda: str(uuid.uuid4()),
        cache: RunCache | None = None,
    ) -> None:
        self._store = store
        self._registry = registry
        self._clock = clock
        self._new_id = id_factory
        self._cache = cache

    # -- helpers ---------------------------------------------------------------------------

    def _holds(self, scope: IdentityScope, permission: Permission, domain_id: str) -> bool:
        return permits(scope, permission, now=self._clock(), domain_id=domain_id)

    async def _load(self, scope: IdentityScope, domain_id: str, report_id: str) -> StoredReport:
        report = await self._store.get(scope.customer_id, domain_id, report_id)
        if report is None:
            raise not_found()
        return report

    def _can_see(self, scope: IdentityScope, report: StoredReport, *, reviewer: bool) -> bool:
        principal = principal_of(scope)
        if (
            report.owner == principal
            or principal in report.shares
            or report.publication.state == "approved"
        ):
            return True
        return (
            reviewer
            and report.publication.state == "pending"
            and self._holds(scope, Permission.CONFIG_MANAGE, report.domain_id)
        )

    async def _readable(
        self, scope: IdentityScope, domain_id: str, report_id: str, *, reviewer: bool = False
    ) -> StoredReport:
        report = await self._load(scope, domain_id, report_id)
        if not self._can_see(scope, report, reviewer=reviewer):
            raise not_found()
        return report

    async def _owned(
        self, scope: IdentityScope, domain_id: str, report_id: str, if_match: str | None
    ) -> StoredReport:
        report = await self._readable(scope, domain_id, report_id)
        if report.owner != principal_of(scope):
            raise ForbiddenError("only the report owner can change it", reason="not_owner")
        self._check_etag(report, if_match)
        return report

    @staticmethod
    def _check_etag(report: StoredReport, if_match: str | None) -> None:
        if if_match is not None and expected_etag(if_match, report.etag) != report.etag:
            raise report_modified()

    def view(self, scope: IdentityScope, report: StoredReport) -> ReportView:
        """Wire view. ``is_owner`` and ``can_decide_publication`` are server-computed hints for
        the UI (the decision route still enforces); they are never an authorization input."""
        me = principal_of(scope)
        owner = report.owner == me
        can_decide = (
            report.publication.state == "pending"
            and me not in (report.owner, report.publication.requested_by)
            and self._holds(scope, Permission.CONFIG_MANAGE, report.domain_id)
        )
        return ReportView(
            id=report.id,
            domain_id=report.domain_id,
            owner=report.owner,
            title=report.title,
            chart_plan=report.chart_plan,
            query_spec=report.query_spec,
            metric=report.metric,
            shares=list(report.shares) if owner else [],
            publication=report.publication,
            created_at=report.created_at,
            updated_at=report.updated_at,
            etag=report.etag or "",
            is_owner=owner,
            can_decide_publication=can_decide,
        )

    @staticmethod
    def _definition(body: ReportBody) -> tuple[dict[str, Any], dict[str, Any]]:
        """(plan template, query spec) ready to store. The plan is validated first and persisted
        in its validated, aliased form with its rows removed."""
        plan = validate_chart_plan(body.chart_plan)
        template = strip_data(plan.model_dump(mode="json", by_alias=True, exclude_unset=True))
        query = body.query_spec.model_dump(mode="json", by_alias=True, exclude_none=True)
        return template, query

    # -- CRUD ------------------------------------------------------------------------------

    async def create(self, scope: IdentityScope, domain_id: str, body: ReportBody) -> StoredReport:
        template, query = self._definition(body)
        now = self._clock()
        return await self._store.create(
            StoredReport(
                id=self._new_id(),
                customer_id=scope.customer_id,
                domain_id=domain_id,
                owner=principal_of(scope),
                title=body.title,
                chart_plan=template,
                query_spec=query,
                metric=body.metric,
                created_at=now,
                updated_at=now,
            )
        )

    async def list(
        self,
        scope: IdentityScope,
        domain_id: str,
        *,
        publication_state: PublicationState | None,
        cursor: str | None,
        limit: int = DEFAULT_LIMIT,
    ) -> Page[StoredReport]:
        reviewer = publication_state is not None and self._holds(
            scope, Permission.CONFIG_MANAGE, domain_id
        )
        return await self._store.list(
            scope.customer_id,
            domain_id,
            visible_to=None if reviewer else principal_of(scope),
            publication_state=publication_state,
            cursor=cursor,
            limit=limit,
        )

    async def get(self, scope: IdentityScope, domain_id: str, report_id: str) -> StoredReport:
        return await self._readable(scope, domain_id, report_id, reviewer=True)

    async def update(
        self,
        scope: IdentityScope,
        domain_id: str,
        report_id: str,
        body: ReportBody,
        if_match: str,
    ) -> StoredReport:
        report = await self._owned(scope, domain_id, report_id, if_match)
        template, query = self._definition(body)
        changed = report.model_copy(
            update={
                "title": body.title,
                "chart_plan": template,
                "query_spec": query,
                "metric": body.metric,
                "publication": Publication(),
                "updated_at": self._clock(),
            }
        )
        return await self._store.replace(changed, if_match=report.etag or "")

    async def delete(
        self, scope: IdentityScope, domain_id: str, report_id: str, if_match: str
    ) -> None:
        report = await self._owned(scope, domain_id, report_id, if_match)
        await self._store.delete(
            scope.customer_id, domain_id, report_id, if_match=report.etag or ""
        )

    # -- sharing ---------------------------------------------------------------------------

    async def share(
        self,
        scope: IdentityScope,
        domain_id: str,
        report_id: str,
        principal_id: str,
        if_match: str | None,
    ) -> StoredReport:
        report = await self._owned(scope, domain_id, report_id, if_match)
        if principal_id == report.owner or principal_id in report.shares:
            return report
        if len(report.shares) >= MAX_SHARES:
            raise StaleVersionError("share limit reached", reason=SHARE_LIMIT_REASON)
        changed = report.model_copy(
            update={"shares": [*report.shares, principal_id], "updated_at": self._clock()}
        )
        return await self._store.replace(changed, if_match=report.etag or "")

    async def unshare(
        self,
        scope: IdentityScope,
        domain_id: str,
        report_id: str,
        principal_id: str,
        if_match: str | None,
    ) -> StoredReport:
        report = await self._owned(scope, domain_id, report_id, if_match)
        if principal_id not in report.shares:
            return report
        changed = report.model_copy(
            update={
                "shares": [p for p in report.shares if p != principal_id],
                "updated_at": self._clock(),
            }
        )
        return await self._store.replace(changed, if_match=report.etag or "")

    # -- publication (add-to-UI) -----------------------------------------------------------

    async def request_publication(
        self, scope: IdentityScope, domain_id: str, report_id: str, if_match: str | None
    ) -> StoredReport:
        report = await self._owned(scope, domain_id, report_id, if_match)
        if report.publication.state == "pending":
            return report
        now = self._clock()
        changed = report.model_copy(
            update={
                "publication": Publication(
                    state="pending", requested_by=principal_of(scope), requested_at=now
                ),
                "updated_at": now,
            }
        )
        return await self._store.replace(changed, if_match=report.etag or "")

    async def decide_publication(
        self,
        scope: IdentityScope,
        domain_id: str,
        report_id: str,
        body: DecisionBody,
        if_match: str | None,
    ) -> StoredReport:
        report = await self._load(scope, domain_id, report_id)
        self._check_etag(report, if_match)
        decider = principal_of(scope)
        if decider in (report.owner, report.publication.requested_by):
            raise ForbiddenError(
                "a report cannot be approved by its owner or requester",
                reason="self_approval_refused",
            )
        if report.publication.state != "pending":
            raise StaleVersionError("no publication is pending", reason="publication_not_pending")
        now = self._clock()
        publication = report.publication.model_copy(
            update={
                "state": "approved" if body.decision == "approve" else "rejected",
                "decided_by": decider,
                "decided_at": now,
                "reason": body.reason,
            }
        )
        changed = report.model_copy(update={"publication": publication, "updated_at": now})
        return await self._store.replace(changed, if_match=report.etag or "")

    # -- run -------------------------------------------------------------------------------

    async def run(self, scope: IdentityScope, domain_id: str, report_id: str) -> RunView:
        report = await self._readable(scope, domain_id, report_id)
        etag = report.etag or ""
        tool = tool_for(report.query_spec)
        args: dict[str, object] = {"query": report.query_spec}
        if tool == "get_cost_summary":
            args["metric"] = report.metric
        key = run_cache_key(scope, report.id, report.etag) if self._cache else None
        result: ToolResult | None = self._cache.get(key) if self._cache and key else None
        if result is None:
            # The viewer's scope, derived by the server for THIS request. Never the owner's.
            result = await self._registry.invoke(tool, args, scope)
            if self._cache and key:
                self._cache.put(key, result)
        citations = [
            CitationView(
                record_id=c.record_id,
                kind=c.kind,
                source=c.source,
                as_of=c.as_of,
                freshness=c.freshness,
            )
            for c in result.citations
        ]
        if not result.records:
            check_template(report.chart_plan)
            return RunView(
                report_id=report.id,
                status="no_data",
                chart_plan=None,
                citations=[],
                truncated=result.truncated,
                ran_at=self._clock(),
                etag=etag,
            )
        rows = build_rows(result.records, numeric_fields(report.chart_plan))
        filled = fill_plan(report.chart_plan, rows, result.citations)
        validate_chart_plan(filled)
        return RunView(
            report_id=report.id,
            status="ok",
            chart_plan=filled,
            citations=citations,
            truncated=result.truncated,
            ran_at=self._clock(),
            etag=etag,
        )
