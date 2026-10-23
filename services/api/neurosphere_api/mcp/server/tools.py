"""The MCP tool surface: PRP-19 read tools plus PRP-17 action-plane tools (PRP-22 item 1).

Every tool is a ``ToolSpec`` in one ``neurosphere_core.copilot.tools.ToolRegistry``, so every
call goes through ``ToolRegistry.invoke``: unregistered names, scope-shaped arguments (any
spelling of ``domain_id``, ``customer_id``, ``tenant``, ``scope``... after the registry's
normalisation) and undeclared arguments are refused and logged by key NAME, never consulted.

* Read tools (``search_catalog``, ``get_cost_summary``, ``list_recommendations``) are the PRP-19
  specs themselves, taken from ``build_default_registry``; nothing is re-implemented here.
* Action tools call :class:`~neurosphere_api.actions.service.ActionApi`, the same methods as the
  REST routes, with the same permission per step: ``draft_action`` (``action.propose`` on the
  target's domain, intent channel ``mcp``), ``validate_action`` and
  ``present_action_confirmation`` (``action.propose``), ``get_action_status`` (``data.read``).
  There is NO confirm, execute or approve tool (PRP-22 D5): a human confirms the bound
  confirmation hash in the UI or through REST, so an agent cannot confirm its own draft.

Domains are server facts: the draft domain is the catalog domain of the target entity (looked up
with the caller's scope), and an intent is looked up only in domains where the caller holds the
step's permission. Every port is read from ``app.state`` when a tool runs (fail closed with 503
when unbound); nothing here opens a network client or sees request headers.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Any, Final

from fastapi import FastAPI
from neurosphere_contracts.actions.v1.action_intent import EvidenceRef, ProposedDiff
from neurosphere_contracts.actions.v1.target_ref import TargetRef
from neurosphere_contracts.recommendations.v1.recommendation import Recommendation
from neurosphere_core.actions import DraftRequest, IntentKey, compute_confirmation_hash
from neurosphere_core.actions.errors import IntentNotFoundError
from neurosphere_core.aggregates import AggregateReader, AggregateWindow, Grain, Metric, QueryResult
from neurosphere_core.audit.canonical import sha256_digest
from neurosphere_core.auth.scope import Permission, domains_with_permission, permits
from neurosphere_core.catalog import CatalogEntity, CatalogRepository, EntityFilter
from neurosphere_core.copilot.tools import (
    TOOL_NAMES,
    Citation,
    EvidenceRecord,
    FreshnessPolicy,
    RefusalSink,
    ToolArgs,
    ToolDependencies,
    ToolNotRegisteredError,
    ToolPermissionError,
    ToolRecord,
    ToolRegistry,
    ToolResult,
    ToolSpec,
    build_default_registry,
)
from neurosphere_core.errors import DependencyTransientError, ForbiddenError
from neurosphere_core.paging import Page, PageRequest
from neurosphere_core.recommendations import RecommendationStore
from neurosphere_core.scope import IdentityScope
from pydantic import Field, StrictStr
from starlette.requests import Request

from neurosphere_api.actions.dependencies import ActionPlane, get_action_plane
from neurosphere_api.actions.models import ActionView, DraftIntentBody
from neurosphere_api.actions.service import ActionApi

__all__ = [
    "ACTION_TOOL_NAMES",
    "MCP_TOOL_NAMES",
    "READ_TOOL_NAMES",
    "DraftActionArgs",
    "IntentNotVisibleError",
    "IntentRefArgs",
    "StatePorts",
    "ToolAnnotationsSpec",
    "build_mcp_registry",
]

READ_TOOL_NAMES: Final = ("get_cost_summary", "list_recommendations", "search_catalog")
ACTION_TOOL_NAMES: Final = (
    "draft_action",
    "get_action_status",
    "present_action_confirmation",
    "validate_action",
)
MCP_TOOL_NAMES: Final = tuple(sorted((*READ_TOOL_NAMES, *ACTION_TOOL_NAMES)))

_SCOPE_NOTE: Final = (
    " Results are limited to the caller's server-derived scope; scope, domain and customer "
    "arguments are refused."
)
_READ_DESCRIPTIONS: Final = {
    "search_catalog": (
        "Search NeuroSphere catalog entities (agents, models, deployments and other registered "
        "entities) in the caller's readable domains."
    ),
    "get_cost_summary": (
        "Cost, latency or error aggregates that NeuroSphere has ingested for the caller's "
        "readable domains (coverage depends on the configured connectors)."
    ),
    "list_recommendations": "List NeuroSphere recommendations in the caller's readable domains.",
}
_ACTION_DESCRIPTIONS: Final = {
    "draft_action": (
        "Draft (never confirm or execute) an action intent for a catalog target. Returns the "
        "intent id, diff, target version and intent hash. A human confirms in the NeuroSphere "
        "UI or REST API; this server has no confirm, execute or approve tool."
    ),
    "validate_action": "Run the prerequisite checks and a dry run for an intent you drafted.",
    "present_action_confirmation": (
        "Bind the confirmation hash and expiry of a validated intent you drafted, for a human "
        "to confirm in the NeuroSphere UI or REST API."
    ),
    "get_action_status": "Current state of an action intent in the caller's readable domains.",
}

_UUID: Final = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
_FRESHNESS: Final = FreshnessPolicy()

Clock = Callable[[], datetime]


@dataclass(frozen=True, slots=True)
class ToolAnnotationsSpec:
    """MCP tool annotations (hints for clients; never authorization)."""

    read_only: bool
    idempotent: bool


ANNOTATIONS: Final[Mapping[str, ToolAnnotationsSpec]] = {
    "search_catalog": ToolAnnotationsSpec(read_only=True, idempotent=True),
    "get_cost_summary": ToolAnnotationsSpec(read_only=True, idempotent=True),
    "list_recommendations": ToolAnnotationsSpec(read_only=True, idempotent=True),
    "get_action_status": ToolAnnotationsSpec(read_only=True, idempotent=True),
    "draft_action": ToolAnnotationsSpec(read_only=False, idempotent=True),
    "validate_action": ToolAnnotationsSpec(read_only=False, idempotent=False),
    "present_action_confirmation": ToolAnnotationsSpec(read_only=False, idempotent=False),
}


# -- argument models -----------------------------------------------------------------------------


class DraftActionArgs(ToolArgs):
    """A change proposal. The domain is resolved server-side from the target entity."""

    action_kind: Annotated[StrictStr, Field(pattern="^[a-z][a-z0-9_]{0,63}$")]
    target: TargetRef
    target_version: Annotated[StrictStr, Field(min_length=1, max_length=256)]
    proposed_diff: ProposedDiff
    evidence: Annotated[list[EvidenceRef], Field(max_length=20)] = Field(
        default_factory=list[EvidenceRef]
    )
    idempotency_key: Annotated[StrictStr | None, Field(pattern=r"^[A-Za-z0-9._:-]{16,128}$")] = None
    """Optional caller key; absent means one derived from the change itself."""


class IntentRefArgs(ToolArgs):
    intent_id: Annotated[StrictStr, Field(pattern=_UUID)]


class IntentNotVisibleError(LookupError):
    """No intent with that id in any domain where the caller holds the step's permission
    (indistinguishable from a missing one, like the REST 404)."""


# -- ports bound to app.state --------------------------------------------------------------------


class StatePorts:
    """Read ports resolved from ``app.state`` at call time; unbound -> 503, never an allow.

    ``app.state`` keys: ``catalog_repository`` (``CatalogRepository``), ``aggregate_reader``
    (``AggregateReader``), ``recommendation_store`` (``RecommendationStore``) and the PRP-17
    action-plane keys (see ``neurosphere_api.actions.dependencies``).
    """

    def __init__(self, app: FastAPI) -> None:
        self._app = app

    def _required(self, key: str, kind: type) -> Any:
        value = getattr(self._app.state, key, None)
        if value is None or not isinstance(value, kind):
            raise DependencyTransientError(
                "MCP tool backend is not configured", reason="mcp_unconfigured"
            )
        return value

    # CatalogReader
    async def get_entity(self, scope: IdentityScope, entity_id: str) -> CatalogEntity | None:
        catalog: CatalogRepository = self._required("catalog_repository", CatalogRepository)
        return await catalog.get_entity(scope, entity_id)

    async def list_entities(
        self, scope: IdentityScope, flt: EntityFilter, page: PageRequest
    ) -> Page[CatalogEntity]:
        catalog: CatalogRepository = self._required("catalog_repository", CatalogRepository)
        return await catalog.list_entities(scope, flt, page)

    # MetricsReader
    async def query(
        self,
        customer_id: str,
        domain_id: str,
        metric: Metric,
        grain: Grain,
        window: AggregateWindow,
        *,
        max_series: int,
        max_points: int,
    ) -> QueryResult:
        reader: AggregateReader = self._required("aggregate_reader", AggregateReader)
        return await reader.query(
            customer_id,
            domain_id,
            metric,
            grain,
            window,
            max_series=max_series,
            max_points=max_points,
        )

    # RecommendationReader
    async def list(
        self,
        scope: IdentityScope,
        domain: str,
        kind: str | None = None,
        q: str | None = None,
        cursor: str | None = None,
        limit: int = 50,
    ) -> Page[Recommendation]:
        store: RecommendationStore = self._required("recommendation_store", RecommendationStore)
        return await store.list(scope, domain, kind, q, cursor, limit)

    def action_plane(self) -> ActionPlane:
        # ``get_action_plane`` reads only ``request.app.state``; this request carries nothing else
        # (no headers, no body, no path) so no request input can reach the action plane.
        return get_action_plane(Request({"type": "http", "app": self._app, "headers": []}))


class _NoEvidence:
    """The MCP server exposes no evidence tool; the PRP-19 evidence port is never reached."""

    async def get_many(
        self, scope: IdentityScope, domain_ids: Any, evidence_ids: Any
    ) -> list[EvidenceRecord]:
        return []


class _NoDrafter:
    """PRP-19 ``propose_action`` (channel ``chat``) is not exposed over MCP; ``draft_action``
    drafts through ``ActionApi`` with channel ``mcp`` instead."""

    async def draft(self, scope: IdentityScope, request: DraftRequest, *, domain_id: str) -> Any:
        raise ToolNotRegisteredError


# -- action tools --------------------------------------------------------------------------------


def _entity_domain(entity: object) -> str | None:
    """A catalog entity's domain: its ``domain_id``, or its own id when it is a Domain."""
    domain: Any = getattr(entity, "domain_id", None)
    if domain is not None:
        return str(getattr(domain, "root", domain))
    if getattr(entity, "entity_type", None) == "domain":
        return str(getattr(entity, "id"))  # noqa: B009 - attribute presence checked above
    return None


def _derived_idempotency_key(args: DraftActionArgs) -> str:
    digest = sha256_digest(
        {
            "channel": "mcp",
            "action_kind": args.action_kind,
            "target": args.target.model_dump(mode="json"),
            "target_version": args.target_version,
            "proposed_diff": args.proposed_diff.model_dump(mode="json"),
            "evidence": [e.model_dump(mode="json") for e in args.evidence],
        }
    )
    return "mcp-" + digest.removeprefix("sha256:")[:32]


def _next_step(state: str) -> str:
    match state:
        case "drafted":
            return "validate_action"
        case "validated":
            return "present_action_confirmation"
        case "awaiting_confirmation":
            return "human_confirms_in_ui_or_rest"
        case _:
            return "none"


def _intent_result(
    tool: str, view: ActionView, domain: str, now: datetime, *, created: bool | None = None
) -> ToolResult:
    rendered = view.model_dump(mode="json", exclude_unset=True)
    intent: dict[str, Any] = rendered["intent"]
    intent_id = str(intent["intent_id"])
    state = str(intent["state"])
    data: dict[str, Any] = {
        "action": rendered,
        "intent_id": intent_id,
        "domain_id": domain,
        "state": state,
        "target": intent["target"],
        "target_version": intent["target_version"],
        "proposed_diff": intent["proposed_diff"],
        "intent_hash": compute_confirmation_hash(view.intent),
        "confirmation_hash": intent.get("confirmation_hash"),
        "confirmation_expires_at": intent.get("confirmation_expires_at"),
        "next_step": _next_step(state),
        "confirm_path": f"/api/v1/actions/domains/{domain}/intents/{intent_id}/confirm",
        "confirmed_by": "human_in_ui_or_rest",
    }
    if created is not None:
        data["created"] = created
    as_of = intent.get("state_changed_at")
    as_of_text = as_of if isinstance(as_of, str) else None
    return ToolResult(
        tool=tool,
        records=(ToolRecord(record_id=intent_id, kind="action_intent", data=data),),
        citations=(
            Citation(
                record_id=intent_id,
                kind="action_intent",
                source="action_service",
                as_of=as_of_text,
                freshness=_FRESHNESS.state(as_of_text, now),
            ),
        ),
    )


async def _locate(
    plane: ActionPlane, scope: IdentityScope, intent_id: str, permission: Permission, now: datetime
) -> IntentKey:
    for domain in sorted(domains_with_permission(scope, permission, now=now)):
        key = IntentKey(scope.customer_id, domain, intent_id)
        try:
            await plane.actions.get(key)
        except IntentNotFoundError:
            continue
        return key
    raise IntentNotVisibleError(intent_id)


def _action_specs(ports: StatePorts, correlation_id: str, clock: Clock) -> list[ToolSpec]:
    async def draft_action(scope: IdentityScope, args: DraftActionArgs) -> ToolResult:
        now = clock()
        # The domain is a server fact about the target; an entity outside the caller's scope is
        # indistinguishable from a missing one.
        entity = await ports.get_entity(scope, args.target.canonical_id)
        domain = None if entity is None else _entity_domain(entity)
        if domain is None:
            raise ForbiddenError(
                "target is outside the caller's scope", reason="target_out_of_scope"
            )
        if not permits(scope, Permission.ACTION_PROPOSE, now=now, domain_id=domain):
            raise ToolPermissionError(Permission.ACTION_PROPOSE.value)
        body = DraftIntentBody(
            action_kind=args.action_kind,
            target=args.target,
            target_version=args.target_version,
            proposed_diff=args.proposed_diff,
            evidence=list(args.evidence),
            idempotency_key=args.idempotency_key or _derived_idempotency_key(args),
            channel="mcp",
        )
        view, created = await ActionApi(ports.action_plane()).draft(
            scope, domain, body, correlation_id
        )
        return _intent_result("draft_action", view, domain, now, created=created)

    async def validate_action(scope: IdentityScope, args: IntentRefArgs) -> ToolResult:
        now = clock()
        plane = ports.action_plane()
        key = await _locate(plane, scope, args.intent_id, Permission.ACTION_PROPOSE, now)
        view = await ActionApi(plane).validate(scope, key, correlation_id)
        return _intent_result("validate_action", view, key.domain_id, now)

    async def present_action_confirmation(scope: IdentityScope, args: IntentRefArgs) -> ToolResult:
        now = clock()
        plane = ports.action_plane()
        key = await _locate(plane, scope, args.intent_id, Permission.ACTION_PROPOSE, now)
        view = await ActionApi(plane).present_confirmation(scope, key, correlation_id)
        return _intent_result("present_action_confirmation", view, key.domain_id, now)

    async def get_action_status(scope: IdentityScope, args: IntentRefArgs) -> ToolResult:
        now = clock()
        plane = ports.action_plane()
        key = await _locate(plane, scope, args.intent_id, Permission.DATA_READ, now)
        view = await ActionApi(plane).get(key)
        return _intent_result("get_action_status", view, key.domain_id, now)

    return [
        ToolSpec(
            "draft_action",
            _ACTION_DESCRIPTIONS["draft_action"],
            DraftActionArgs,
            Permission.ACTION_PROPOSE,
            draft_action,
        ),
        ToolSpec(
            "validate_action",
            _ACTION_DESCRIPTIONS["validate_action"],
            IntentRefArgs,
            Permission.ACTION_PROPOSE,
            validate_action,
        ),
        ToolSpec(
            "present_action_confirmation",
            _ACTION_DESCRIPTIONS["present_action_confirmation"],
            IntentRefArgs,
            Permission.ACTION_PROPOSE,
            present_action_confirmation,
        ),
        ToolSpec(
            "get_action_status",
            _ACTION_DESCRIPTIONS["get_action_status"],
            IntentRefArgs,
            Permission.DATA_READ,
            get_action_status,
        ),
    ]


def build_mcp_registry(
    ports: StatePorts,
    *,
    correlation_id: str,
    clock: Clock,
    sink: RefusalSink | None = None,
) -> ToolRegistry:
    """The MCP allowlist: three PRP-19 read specs plus the four action-plane specs."""
    if not set(READ_TOOL_NAMES) <= set(TOOL_NAMES):  # pragma: no cover - PRP-19 contract drift
        raise RuntimeError("PRP-19 registry no longer provides the MCP read tools")
    base = build_default_registry(
        ToolDependencies(
            catalog=ports,
            metrics=ports,
            recommendations=ports,
            evidence=_NoEvidence(),
            drafter=_NoDrafter(),
            clock=clock,
        )
    )
    read_specs = [
        ToolSpec(
            spec.name,
            _READ_DESCRIPTIONS[spec.name] + _SCOPE_NOTE,
            spec.args_model,
            spec.permission,
            spec.handler,
        )
        for spec in base.manifest()
        if spec.name in READ_TOOL_NAMES
    ]
    action_specs = [
        ToolSpec(s.name, s.description + _SCOPE_NOTE, s.args_model, s.permission, s.handler)
        for s in _action_specs(ports, correlation_id, clock)
    ]
    return ToolRegistry([*read_specs, *action_specs], sink=sink)
