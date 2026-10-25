"""Action-plane, HITL, reports and MCP-admin builder (PRP-29 item 8).

Consumes ``AUDIT_REPOSITORY``, ``HITL_SERVICE``, ``CATALOG_REPOSITORY`` and ``AGGREGATE_READER``
(data builder) and ``SCOPE_DERIVER``, ``POLICY_REPOSITORY`` and ``REVOCATION_CHECKER`` (authz
builder); publishes :data:`~neurosphere_api.runtime.builders.ACTION_SERVICE`, the ONE
``ActionService`` that buttons (REST), chat (copilot) and MCP all reach through the PRP-17
``app.state`` keys. Nothing else in the composition builds an ``ActionService``.

* ``action_plane``: :func:`configure_action_plane` with

  - ``CosmosIntentStore`` (``action_intents``) and ``CosmosExecutionControl``
    (``action_execution_control``, the kill switch) on ``NS_STORE_DATABASE``;
  - the shared ``HitlService`` and ``AuditRepository`` (``AuditRepositoryActionAuditor``);
  - the default ``ReviewPolicyRegistry`` (``default_policies()``, the same deterministic table the
    data builder's ``HitlService`` resolves from);
  - write targets: a ``WriteTargetRegistry`` holding ONLY connectors that
    ``neurosphere_core.actions.targets.ACTION_CONNECTORS`` names (``foundry-model-swap`` for
    ``model_deployment_swap``). The API image ships no connector configuration, so production
    composes an EMPTY registry: every intent is advisory (drafted, validated and reviewed, never
    executed), and nothing stands in for a change: no catalog metadata edit, no pretend swap;
  - a ``PolicyPermissionRechecker`` bound to the composed deriver: the deriver's cloud and the
    very policy repository and revocation checker it derives scope from;
  - :class:`PolicyReviewerDirectory` (assignee lookup through the same policy repository).

* ``hitl``: ``ok`` exactly when the review routes resolve the configured plane
  (``get_action_plane``); they share its keys.
* ``reports``: :func:`configure_reports` with ``CosmosReportStore`` (``reports``) and the bounded
  five-tool registry (``build_default_registry``) over the shared catalog and aggregate readers;
  report runs never draft (the drafter refuses), and evidence reads nothing.
* ``mcp_admin``: :func:`configure_mcp_admin` with an ``McpRegistry`` over
  ``CosmosMcpServerStore`` (``mcp_servers``) under the deployment's ``McpClientPolicy``, the
  SSRF-guarded ``ExternalMcpClient`` with no outbound credentials, and the shared audit.

Test code may replace a store through ``ctx.overrides.backend(name)``: ``intent_store``,
``execution_control``, ``write_targets``, ``permission_rechecker``, ``reviewer_directory``,
``review_policies``, ``report_store`` and ``mcp_server_store``. ``main.create`` passes none.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Final, cast

from fastapi import Request
from neurosphere_connector.write import WriteTargetRegistry
from neurosphere_contracts.actions.v1.action_intent import ActionIntent
from neurosphere_contracts.actions.v1.actor import Actor
from neurosphere_contracts.recommendations.v1.recommendation import Recommendation
from neurosphere_core.actions import (
    ActionService,
    AuditRepositoryActionAuditor,
    DraftRequest,
    ExecutionControl,
    IntentStore,
    PermissionRechecker,
)
from neurosphere_core.actions.cosmos_store import CosmosExecutionControl, CosmosIntentStore
from neurosphere_core.actions.recheck import PolicyPermissionRechecker
from neurosphere_core.actions.targets import ACTION_CONNECTORS
from neurosphere_core.auth.scope import PolicyRepository
from neurosphere_core.copilot.tools import (
    CatalogReader,
    MetricsReader,
    ToolDependencies,
    ToolRegistry,
    build_default_registry,
)
from neurosphere_core.errors import DependencyTransientError, ForbiddenError
from neurosphere_core.hitl import ReviewPolicyRegistry
from neurosphere_core.mcp import McpClientPolicy, McpRegistry, McpServerStore
from neurosphere_core.mcp.cosmos_store import CosmosMcpServerStore
from neurosphere_core.paging import Page
from neurosphere_core.recommendations import RecommendationStore
from neurosphere_core.scope import IdentityScope

from neurosphere_api.actions import configure_action_plane, get_action_plane
from neurosphere_api.copilot import EmptyEvidenceReader
from neurosphere_api.hitl import ReviewerDirectory
from neurosphere_api.mcp.admin import McpAdminPlane, configure_mcp_admin
from neurosphere_api.mcp.client import ExternalMcpClient
from neurosphere_api.reports import CosmosReportStore, ReportStore, configure_reports
from neurosphere_api.reports.dependencies import get_report_service
from neurosphere_api.runtime.builders import (
    ACTION_SERVICE,
    AGGREGATE_READER,
    AUDIT_REPOSITORY,
    CATALOG_REPOSITORY,
    HITL_SERVICE,
    POLICY_REPOSITORY,
    REVOCATION_CHECKER,
    SCOPE_DERIVER,
    BuildContext,
    BuilderSpec,
    ComponentUnavailableError,
)

__all__ = [
    "BUILDER",
    "COMPONENTS",
    "SUPPORTED_WRITE_CONNECTORS",
    "PolicyReviewerDirectory",
    "build",
]

COMPONENTS: Final = ("hitl", "action_plane", "reports", "mcp_admin")
#: Manifest names a composed write-target registry may hold (the shipped write connectors).
SUPPORTED_WRITE_CONNECTORS: Final = frozenset(ACTION_CONNECTORS.values())

_PRINCIPAL_KINDS: Final = {"person": "user", "principal": "service_principal"}

DateClock = Callable[[], datetime]


# -- small helpers ---------------------------------------------------------------------------


def _backend[T](ctx: BuildContext, name: str, kind: type[T]) -> T | None:
    """A test backend named ``name`` (``None`` in production); the wrong type is a failure."""
    value = ctx.overrides.backend(name)
    if value is None:
        return None
    if not isinstance(value, kind):
        raise ComponentUnavailableError(f"{name}_invalid")
    return value


def _date_clock(ctx: BuildContext) -> DateClock | None:
    """``overrides.clock`` (POSIX seconds) as an aware-datetime clock; ``None`` = UTC now."""
    clock = ctx.overrides.clock
    if clock is None:
        return None
    return lambda: datetime.fromtimestamp(clock(), UTC)


def _database(ctx: BuildContext) -> tuple[Any, str]:
    return ctx.cosmos_client(), ctx.store_settings().database


def _state_request(ctx: BuildContext) -> Request:
    """A request carrying only the app: what the route dependencies resolve collaborators from."""
    return Request({"type": "http", "app": ctx.app, "headers": []})


class PolicyReviewerDirectory:
    """:class:`~neurosphere_api.hitl.ReviewerDirectory` over the policy store.

    A principal is known when the policy store holds a document for it in that customer; the
    actor is its pseudonym (the last canonical-id segment, exactly as scope derivation sets
    ``principal_pseudonym``). Whether that principal may REVIEW the item is decided separately by
    the HITL authorizer against the current policy; this only resolves who they are.
    """

    def __init__(self, policy_repository: PolicyRepository) -> None:
        self._repo = policy_repository

    async def actor_for(self, customer_id: str, principal_id: str) -> Actor | None:
        parts = principal_id.split(":")
        if len(parts) != 5 or parts[1] != customer_id or parts[2] != "entra":
            return None
        kind = _PRINCIPAL_KINDS.get(parts[3])
        if kind is None:
            return None
        policy = await self._repo.get_principal_policy(customer_id, principal_id)
        if policy is None or policy.principal_id != principal_id:
            return None
        return Actor.model_validate(
            {"principal_pseudonym": parts[4], "principal_kind": kind, "on_behalf_of": None}
        )


# -- action plane ----------------------------------------------------------------------------


def _rechecker(ctx: BuildContext, clock: DateClock | None) -> PermissionRechecker:
    override = _backend(ctx, "permission_rechecker", PermissionRechecker)
    if override is not None:
        return override
    deriver = ctx.shared(SCOPE_DERIVER)
    extra: dict[str, Any] = {} if clock is None else {"clock": clock}
    return PolicyPermissionRechecker(
        cloud=deriver.config.cloud,
        policy_repository=ctx.shared(POLICY_REPOSITORY),
        revocation_checker=ctx.shared(REVOCATION_CHECKER),
        **extra,
    )


def _write_targets(ctx: BuildContext) -> WriteTargetRegistry:
    """Only shipped write connectors; production composes none (every intent advisory)."""
    override = _backend(ctx, "write_targets", WriteTargetRegistry)
    if override is None:
        return WriteTargetRegistry()
    if not set(override.names()) <= SUPPORTED_WRITE_CONNECTORS:
        raise ComponentUnavailableError("write_target_unsupported")
    return override


def _intent_store(ctx: BuildContext) -> IntentStore:
    override = _backend(ctx, "intent_store", IntentStore)
    if override is not None:
        return override
    client, database = _database(ctx)
    return CosmosIntentStore.from_client(client, database=database)


def _execution_control(ctx: BuildContext) -> ExecutionControl:
    override = _backend(ctx, "execution_control", ExecutionControl)
    if override is not None:
        return override
    client, database = _database(ctx)
    return CosmosExecutionControl.from_client(client, database=database)


def _reviewer_directory(ctx: BuildContext) -> ReviewerDirectory:
    override = _backend(ctx, "reviewer_directory", ReviewerDirectory)
    if override is not None:
        return override
    return PolicyReviewerDirectory(ctx.shared(POLICY_REPOSITORY))


def _action_plane(ctx: BuildContext) -> ActionService:
    audit = ctx.shared(AUDIT_REPOSITORY)
    hitl = ctx.shared(HITL_SERVICE)
    clock = _date_clock(ctx)
    rechecker = _rechecker(ctx, clock)
    intents = _intent_store(ctx)
    control = _execution_control(ctx)
    targets = _write_targets(ctx)
    policies = _backend(ctx, "review_policies", ReviewPolicyRegistry) or ReviewPolicyRegistry()
    directory = _reviewer_directory(ctx)
    extra: dict[str, Any] = {} if clock is None else {"clock": clock}
    service = ActionService(
        intents,
        auditor=AuditRepositoryActionAuditor(audit),
        rechecker=rechecker,
        execution_control=control,
        **extra,
    )
    configure_action_plane(
        ctx.app,
        action_service=service,
        intent_store=intents,
        hitl_service=hitl,
        review_policies=policies,
        write_targets=targets,
        permission_rechecker=rechecker,
        execution_control=control,
        audit_repository=audit,
        clock=clock,
        reviewer_directory=directory,
    )
    try:
        plane = get_action_plane(_state_request(ctx))
    except DependencyTransientError:
        raise ComponentUnavailableError("action_plane_unconfigured") from None
    if plane.actions is not service:  # pragma: no cover - configure_action_plane just set it
        raise ComponentUnavailableError("action_plane_unconfigured")
    return service


def _build_action_plane(ctx: BuildContext) -> None:
    try:
        service = _action_plane(ctx)
    except ComponentUnavailableError as exc:
        ctx.failed("action_plane", exc.reason)
        ctx.failed("hitl", exc.reason)
        return
    ctx.publish(ACTION_SERVICE, service)
    ctx.ok("action_plane")
    ctx.ok("hitl")  # the review routes resolve exactly this plane


# -- reports ---------------------------------------------------------------------------------


class _StateRecommendations:
    """``RecommendationReader`` resolved from ``app.state.recommendation_store`` per call.

    The data builder installs the store on ``app.state`` (it has no shared key); unbound fails
    closed with 503 ``reports_unconfigured``, never an empty "allowed" answer.
    """

    def __init__(self, ctx: BuildContext) -> None:
        self._app = ctx.app

    async def list(
        self,
        scope: IdentityScope,
        domain: str,
        kind: str | None = None,
        q: str | None = None,
        cursor: str | None = None,
        limit: int = 50,
    ) -> Page[Recommendation]:
        store = getattr(self._app.state, "recommendation_store", None)
        if not isinstance(store, RecommendationStore):
            raise DependencyTransientError(
                "recommendations are not configured", reason="reports_unconfigured"
            )
        return await store.list(scope, domain, kind, q, cursor, limit)


class _NoDrafter:
    """Report runs never draft an action; ``propose_action`` through this registry is refused."""

    async def draft(
        self, scope: IdentityScope, request: DraftRequest, *, domain_id: str
    ) -> ActionIntent:
        raise ForbiddenError("reports do not draft actions", reason="action_not_available")


def _tool_registry(ctx: BuildContext, clock: DateClock | None) -> ToolRegistry:
    catalog = cast(CatalogReader, ctx.shared(CATALOG_REPOSITORY))
    metrics = cast(MetricsReader, ctx.shared(AGGREGATE_READER))
    extra: dict[str, Any] = {} if clock is None else {"clock": clock}
    return build_default_registry(
        ToolDependencies(
            catalog=catalog,
            metrics=metrics,
            recommendations=_StateRecommendations(ctx),
            evidence=EmptyEvidenceReader(),
            drafter=_NoDrafter(),
            **extra,
        )
    )


def _reports(ctx: BuildContext) -> None:
    clock = _date_clock(ctx)
    registry = _tool_registry(ctx, clock)
    store = _backend(ctx, "report_store", ReportStore)
    if store is None:
        client, database = _database(ctx)
        store = CosmosReportStore.from_client(client, database=database)
    configure_reports(ctx.app, store=store, tool_registry=registry, clock=clock)
    try:
        get_report_service(_state_request(ctx))
    except DependencyTransientError:
        raise ComponentUnavailableError("reports_unconfigured") from None


# -- MCP administration ----------------------------------------------------------------------


def _mcp_admin(ctx: BuildContext) -> None:
    audit = ctx.shared(AUDIT_REPOSITORY)
    store = _backend(ctx, "mcp_server_store", McpServerStore)
    if store is None:
        client, database = _database(ctx)
        store = CosmosMcpServerStore.from_client(client, database=database)
    registry = McpRegistry(store, McpClientPolicy(cloud=ctx.settings.cloud_profile.cloud))
    # SSRF-vetted, IP-pinned transport; no outbound credentials are configured (none is read).
    external = ExternalMcpClient(registry)
    configure_mcp_admin(ctx.app, McpAdminPlane(registry=registry, client=external, audit=audit))


# -- build -----------------------------------------------------------------------------------


def build(ctx: BuildContext) -> None:
    _build_action_plane(ctx)
    ctx.attempt("reports", lambda: _reports(ctx))
    ctx.attempt("mcp_admin", lambda: _mcp_admin(ctx))


BUILDER: Final = BuilderSpec("planes", COMPONENTS, build)
