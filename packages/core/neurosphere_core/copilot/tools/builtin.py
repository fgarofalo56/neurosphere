"""The five allowlisted copilot tools and ``build_default_registry``.

Each tool is ``(scope, args) -> ToolResult`` where ``scope`` is the server-derived
``IdentityScope`` and ``args`` is a typed model with no scope field. Each tool rechecks its own
permission against that scope (PRP-19 D5): domains come from ``domains_with_permission`` on the
scope, never from arguments, and every returned record is filtered against those domains a second
time so a misbehaving port cannot leak another domain. A ``domain_id`` filter inside a
``StructuredQuery`` can only narrow the readable set, never widen it.

Tool names match the PRP-12 corpus manifest (``tests/security/injection/stubs.py``).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Final

from neurosphere_contracts.query.v1.structured_query import StructuredQuery

from neurosphere_core.actions import DraftRequest
from neurosphere_core.aggregates import AggregateWindow, Grain, parse_time
from neurosphere_core.audit.canonical import sha256_digest
from neurosphere_core.auth.scope import Permission, domains_with_permission, permits
from neurosphere_core.catalog import EntityFilter
from neurosphere_core.copilot.tools.args import (
    CostSummaryArgs,
    EvidenceArgs,
    ListRecommendationsArgs,
    ProposeActionArgs,
    SearchCatalogArgs,
)
from neurosphere_core.copilot.tools.errors import ToolBudgetError, ToolPermissionError
from neurosphere_core.copilot.tools.models import (
    Citation,
    FreshnessPolicy,
    ToolRecord,
    ToolResult,
)
from neurosphere_core.copilot.tools.ports import (
    ActionDrafter,
    CatalogReader,
    EvidenceReader,
    MetricsReader,
    RecommendationReader,
)
from neurosphere_core.copilot.tools.registry import (
    RefusalSink,
    ToolHandler,
    ToolRegistry,
    ToolSpec,
)
from neurosphere_core.errors import ForbiddenError
from neurosphere_core.paging import PageRequest
from neurosphere_core.scope import IdentityScope

__all__ = [
    "MAX_RESULT_LIMIT",
    "TOOL_NAMES",
    "ToolDependencies",
    "build_default_registry",
]

#: Server ceiling for rows per tool call; the model's ``budget.limit`` is clamped to it.
MAX_RESULT_LIMIT: Final = 100
TOOL_NAMES: Final = (
    "get_cost_summary",
    "get_evidence",
    "list_recommendations",
    "propose_action",
    "search_catalog",
)

_CATALOG_LIFECYCLES: Final = ("draft", "active", "deprecated", "retired")
_NON_CATALOG_ENTITIES: Final = ("telemetry_event", "cost_record", "evaluation_result")
_PLAIN_QUERY_FIELDS: Final = ("cursor", "fields", "group_by", "sort", "traversal")

Row = tuple[str, str, str, "str | None", dict[str, Any]]
"""(record_id, kind, source, as_of, data): the raw material of one record and its citation."""


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class ToolDependencies:
    """Everything the tools read through. Bound once at startup; never from a model."""

    catalog: CatalogReader
    metrics: MetricsReader
    recommendations: RecommendationReader
    evidence: EvidenceReader
    drafter: ActionDrafter
    clock: Callable[[], datetime] = _utc_now
    freshness: FreshnessPolicy = field(default_factory=FreshnessPolicy)


# -- shared helpers ------------------------------------------------------------------------------


def _readable_domains(
    scope: IdentityScope, permission: Permission, now: datetime
) -> tuple[str, ...]:
    domains = domains_with_permission(scope, permission, now=now)
    if not domains:
        raise ToolPermissionError(permission.value)
    return tuple(sorted(domains))


def _clamped_limit(requested: int) -> tuple[int, bool]:
    return min(requested, MAX_RESULT_LIMIT), requested > MAX_RESULT_LIMIT


def _require_query(query: StructuredQuery, operation: str) -> None:
    """Operation, depth and unsupported-clause checks shared by the read tools."""
    if query.operation != operation:
        raise ToolBudgetError(f"operation must be {operation}", reason="unsupported_operation")
    if query.budget.max_depth != 0:
        raise ToolBudgetError("max_depth must be 0 for this tool", reason="depth_denied")
    unsupported = [name for name in _PLAIN_QUERY_FIELDS if getattr(query, name) is not None]
    if operation == "list":
        unsupported += [n for n in ("aggregations", "time_bucket") if getattr(query, n) is not None]
    if unsupported:
        raise ToolBudgetError(
            "query uses clauses this tool does not support", reason="unsupported_query"
        )


def _filter_values(
    query: StructuredQuery, field_name: str, supported: frozenset[str]
) -> list[str] | None:
    """Values of the ``eq``/``in`` filters on ``field_name``; ``None`` when there is none.

    A filter on a field outside ``supported``, or with another operator, is refused rather than
    silently dropped: a dropped filter would widen what the model asked for.
    """
    found: list[str] | None = None
    for flt in query.filters or []:
        root: Any = flt.root
        if root.field.root not in supported:
            raise ToolBudgetError(
                "filter field is not supported by this tool", reason="unsupported_filter"
            )
        if root.op not in ("eq", "in"):
            raise ToolBudgetError(
                "filter operator is not supported by this tool", reason="unsupported_filter"
            )
        if root.field.root != field_name:
            continue
        raw = [root.value] if root.value is not None else list(root.values or [])
        found = (found or []) + [item.root for item in raw]
    return found


def _entity_name(query: StructuredQuery) -> str:
    root: Any = query.entity.root
    return str(getattr(root, "root", root))


def _narrow(readable: tuple[str, ...], requested: list[str] | None) -> tuple[str, ...]:
    """Readable domains, narrowed (never widened) by a model-requested ``domain_id`` filter."""
    if requested is None:
        return readable
    return tuple(d for d in readable if d in requested)


def _build_result(
    tool: str, rows: Sequence[Row], deps: ToolDependencies, *, truncated: bool
) -> ToolResult:
    """Records and citations are both built here from the same rows."""
    now = deps.clock()
    records: list[ToolRecord] = []
    citations: list[Citation] = []
    for record_id, kind, source, as_of, data in rows:
        records.append(ToolRecord(record_id=record_id, kind=kind, data=data))
        citations.append(
            Citation(
                record_id=record_id,
                kind=kind,
                source=source,
                as_of=as_of,
                freshness=deps.freshness.state(as_of, now),
            )
        )
    return ToolResult(
        tool=tool, records=tuple(records), citations=tuple(citations), truncated=truncated
    )


def _entity_domain(entity: object) -> str | None:
    """A catalog entity's domain: its ``domain_id``, or its own id when it is a Domain."""
    domain: Any = getattr(entity, "domain_id", None)
    if domain is not None:
        return str(getattr(domain, "root", domain))
    if getattr(entity, "entity_type", None) == "domain":
        return str(getattr(entity, "id"))  # noqa: B009 - attribute presence checked above
    return None


# -- tools ---------------------------------------------------------------------------------------


def _search_catalog(deps: ToolDependencies) -> ToolHandler:
    supported = frozenset({"lifecycle_status", "domain_id"})

    async def run(scope: IdentityScope, args: SearchCatalogArgs) -> ToolResult:
        query = args.query
        _require_query(query, "list")
        entity = _entity_name(query)
        if entity in _NON_CATALOG_ENTITIES:
            raise ToolBudgetError("entity is not a catalog entity", reason="unsupported_entity")
        readable = _readable_domains(scope, Permission.DATA_READ, deps.clock())
        lifecycles = _filter_values(query, "lifecycle_status", supported)
        if any(v not in _CATALOG_LIFECYCLES for v in lifecycles or []):
            raise ToolBudgetError("unknown lifecycle status", reason="unsupported_filter")
        domains = _narrow(readable, _filter_values(query, "domain_id", supported))
        if not domains:
            return _build_result("search_catalog", [], deps, truncated=False)
        limit, clamped = _clamped_limit(query.budget.limit)
        flt = EntityFilter.model_validate(
            {
                "entity_types": [entity],
                "domain_ids": list(domains),
                "lifecycle_statuses": lifecycles,
            }
        )
        page = await deps.catalog.list_entities(scope, flt, PageRequest(page_size=limit))
        rows: list[Row] = [
            (
                item.id,
                item.entity_type,
                "catalog",
                item.updated_at.root,
                item.model_dump(mode="json"),
            )
            for item in page.items
            if _entity_domain(item) in domains
        ]
        return _build_result(
            "search_catalog", rows, deps, truncated=clamped or page.next_cursor is not None
        )

    return run


def _get_cost_summary(deps: ToolDependencies) -> ToolHandler:
    supported = frozenset({"domain_id"})

    async def run(scope: IdentityScope, args: CostSummaryArgs) -> ToolResult:
        query = args.query
        _require_query(query, "aggregate")
        if query.time_range is None:
            raise ToolBudgetError("time_range is required", reason="time_range_required")
        grain: Grain
        if query.time_bucket in (None, "day"):
            grain = "day"
        elif query.time_bucket == "hour":
            grain = "hour"
        else:
            raise ToolBudgetError("time_bucket must be day or hour", reason="unsupported_query")
        readable = _readable_domains(scope, Permission.DATA_READ, deps.clock())
        domains = _narrow(readable, _filter_values(query, "domain_id", supported))
        window = AggregateWindow(
            start=parse_time(query.time_range.start.root), end=parse_time(query.time_range.end.root)
        )
        limit, clamped = _clamped_limit(query.budget.limit)
        rows: list[Row] = []
        truncated = clamped
        for domain in domains:
            result = await deps.metrics.query(
                scope.customer_id,
                domain,
                args.metric,
                grain,
                window,
                max_series=min(limit, 50),
                max_points=limit,
            )
            truncated = truncated or result.truncated
            for series in result.series:
                for point in series.points:
                    rows.append(
                        (
                            point.id,
                            args.metric,
                            "aggregates",
                            point.watermark,
                            point.model_dump(mode="json"),
                        )
                    )
        if len(rows) > limit:
            rows, truncated = rows[:limit], True
        return _build_result("get_cost_summary", rows, deps, truncated=truncated)

    return run


def _list_recommendations(deps: ToolDependencies) -> ToolHandler:
    supported = frozenset({"kind", "domain_id"})

    async def run(scope: IdentityScope, args: ListRecommendationsArgs) -> ToolResult:
        query = args.query
        _require_query(query, "list")
        if _entity_name(query) != "recommendation":
            raise ToolBudgetError("entity must be recommendation", reason="unsupported_entity")
        readable = _readable_domains(scope, Permission.DATA_READ, deps.clock())
        kinds = _filter_values(query, "kind", supported)
        if kinds is not None and len(kinds) != 1:
            raise ToolBudgetError(
                "exactly one kind filter value is supported", reason="unsupported_filter"
            )
        domains = _narrow(readable, _filter_values(query, "domain_id", supported))
        limit, clamped = _clamped_limit(query.budget.limit)
        rows: list[Row] = []
        truncated = clamped
        for domain in domains:
            page = await deps.recommendations.list(
                scope, domain, kind=kinds[0] if kinds else None, limit=limit
            )
            truncated = truncated or page.next_cursor is not None
            rows.extend(
                (
                    rec.recommendation_id.root,
                    "recommendation",
                    "recommendations",
                    rec.created_at.root,
                    rec.model_dump(mode="json"),
                )
                for rec in page.items
                if rec.domain_id.root == domain
            )
        if len(rows) > limit:
            rows, truncated = rows[:limit], True
        return _build_result("list_recommendations", rows, deps, truncated=truncated)

    return run


def _get_evidence(deps: ToolDependencies) -> ToolHandler:
    async def run(scope: IdentityScope, args: EvidenceArgs) -> ToolResult:
        domains = _readable_domains(scope, Permission.EVIDENCE_READ, deps.clock())
        wanted = set(args.evidence_ids)
        found = await deps.evidence.get_many(scope, domains, sorted(wanted))
        limit, clamped = _clamped_limit(args.budget.limit)
        rows: list[Row] = [
            (
                rec.evidence_id,
                "evidence",
                "evidence",
                rec.observed_at,
                {"evidence_kind": rec.kind, "ref": rec.ref, "domain_id": rec.domain_id},
            )
            for rec in found
            if rec.domain_id in domains and rec.evidence_id in wanted
        ]
        truncated = clamped or len(rows) > limit
        return _build_result("get_evidence", rows[:limit], deps, truncated=truncated)

    return run


def _propose_action(deps: ToolDependencies) -> ToolHandler:
    async def run(scope: IdentityScope, args: ProposeActionArgs) -> ToolResult:
        now = deps.clock()
        # The domain is a server fact about the target, never a model argument. An entity outside
        # the scope is indistinguishable from a missing one.
        entity = await deps.catalog.get_entity(scope, args.target.canonical_id)
        domain = None if entity is None else _entity_domain(entity)
        if domain is None:
            raise ForbiddenError(
                "target is outside the caller's scope", reason="target_out_of_scope"
            )
        if not permits(scope, Permission.ACTION_PROPOSE, now=now, domain_id=domain):
            raise ToolPermissionError(Permission.ACTION_PROPOSE.value)
        digest = sha256_digest(
            {
                "action_kind": args.action_kind,
                "target": args.target.model_dump(mode="json"),
                "target_version": args.target_version,
                "proposed_diff": args.proposed_diff.model_dump(mode="json"),
            }
        )
        request = DraftRequest(
            action_kind=args.action_kind,
            target=args.target,
            target_version=args.target_version,
            proposed_diff=args.proposed_diff,
            evidence=args.evidence,
            idempotency_key="chat-" + digest.removeprefix("sha256:")[:32],
            channel="chat",
        )
        intent = await deps.drafter.draft(scope, request, domain_id=domain)
        data: dict[str, Any] = {
            "intent_id": intent.intent_id.root,
            "state": intent.state.root if hasattr(intent.state, "root") else str(intent.state),
            "action_kind": intent.action_kind,
            "target": intent.target.model_dump(mode="json"),
            "target_version": intent.target_version,
            "next_step": "confirm_in_ui",
        }
        row: Row = (
            intent.intent_id.root,
            "action_intent",
            "action_service",
            intent.created_at.root,
            data,
        )
        return _build_result("propose_action", [row], deps, truncated=False)

    return run


def build_default_registry(
    deps: ToolDependencies, *, sink: RefusalSink | None = None
) -> ToolRegistry:
    """The five-tool allowlist. Nothing else is callable through the returned registry."""
    return ToolRegistry(
        [
            ToolSpec(
                "search_catalog",
                "Search catalog entities in the caller's readable domains.",
                SearchCatalogArgs,
                Permission.DATA_READ,
                _search_catalog(deps),
            ),
            ToolSpec(
                "get_cost_summary",
                "Cost, latency or error aggregates for the caller's readable domains.",
                CostSummaryArgs,
                Permission.DATA_READ,
                _get_cost_summary(deps),
            ),
            ToolSpec(
                "get_evidence",
                "Look up evidence pointers by id in domains where evidence.read is held.",
                EvidenceArgs,
                Permission.EVIDENCE_READ,
                _get_evidence(deps),
            ),
            ToolSpec(
                "list_recommendations",
                "List recommendations in the caller's readable domains.",
                ListRecommendationsArgs,
                Permission.DATA_READ,
                _list_recommendations(deps),
            ),
            ToolSpec(
                "propose_action",
                "Draft (never confirm or execute) an action intent for a catalog target.",
                ProposeActionArgs,
                Permission.ACTION_PROPOSE,
                _propose_action(deps),
            ),
        ],
        sink=sink,
    )
