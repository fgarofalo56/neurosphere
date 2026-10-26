"""Data-plane builder (PRP-29 item 7): the stores and readers the read-side routes need.

Components (each reported through ``ctx``; a failure is a reason code, never a value):

========================  =====================================================================
Component                 ``app.state`` keys
========================  =====================================================================
``catalog``               ``catalog_repository``, ``catalog_graph``, ``catalog_review_queue``,
                          ``catalog_clock``
``aggregates``            ``aggregate_reader``
``ledger``                ``ledger_store``
``federation``            ``federation`` (this deployment's cell, served in-process)
``evaluation``            ``evaluation_store``, ``evaluation_pilot_dataset_ids``
``recommendations``       ``recommendation_store``
``audit``                 ``audit_repository``
``review_router``         ``review_router`` (HITL-backed; also builds and publishes the
                          ``HitlService``)
``replay``                ``trace_reader``, ``replay_payload_policy``
``map``                   ``map_pseudonymizer``, ``map_viewport_limits``
``realtime``              ``app.state.realtime`` through ``configure_realtime``
========================  =====================================================================

Also installed, with no component of their own: ``sandbox_repository`` (``NS_ENV=local`` only,
the sandbox keeps its own emulator database; elsewhere the route answers 503 as before).

Published for the planes builder: ``AUDIT_REPOSITORY``, ``HITL_SERVICE``, ``AGGREGATE_READER``,
``CATALOG_REPOSITORY``.

Containers are never created here (the composition provisions them locally; IaC elsewhere). Names
come from each store's constants, the projection sink names and the ingestion ledger settings, and
``tests/runtime_data`` pins every one of them to the registry in ``neurosphere_core.stores``.

Test fakes enter through ``ctx.overrides.backend(<app.state key>)`` (and ``blob_client`` for the
archive container), so CI composes the whole data plane with no emulator.

Known gap: catalog free-text search has no Azure AI Search index to call, so ``catalog_graph``
answers ``get``/``neighbors``/``impact`` and fails closed (503 ``search_unavailable``) on
``search`` rather than returning an empty result that looks like "nothing matched".
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Annotated, Any, Final

from neurosphere_core.actions.recheck import PolicyPermissionRechecker
from neurosphere_core.aggregates import AggregateReader
from neurosphere_core.aggregates.cosmos import CosmosAggregateStore
from neurosphere_core.audit import AuditRepository
from neurosphere_core.audit.cosmos_store import CosmosAuditStore
from neurosphere_core.auth.scope import PrincipalPseudonymizer
from neurosphere_core.catalog import CatalogRepository, GraphQuery
from neurosphere_core.catalog.graph import RepositoryGraphQuery
from neurosphere_core.catalog.repo.cosmos import CosmosCatalogRepository
from neurosphere_core.catalog.review_queue import ReviewQueue
from neurosphere_core.catalog.review_queue_cosmos import (
    DEFAULT_REVIEW_QUEUE_CONTAINER,
    CosmosReviewQueue,
)
from neurosphere_core.errors import (
    DependencyTransientError,
    InvalidSchemaError,
)
from neurosphere_core.evaluation.cosmos_store import CosmosEvaluationStore
from neurosphere_core.evaluation.store import EvaluationStore
from neurosphere_core.hitl import DecisionLog, HitlService, ReviewPolicyRegistry
from neurosphere_core.hitl_cosmos.store import CosmosDecisionStore, CosmosHitlStore
from neurosphere_core.ledger import LedgerStore
from neurosphere_core.ledger.cosmos import CosmosLedgerStore
from neurosphere_core.recommendations import RecommendationStore
from neurosphere_core.recommendations.cosmos_store import CosmosRecommendationStore
from neurosphere_workers.federation import CellRef, CellRegistry
from neurosphere_workers.ingestion.wiring import LedgerSettings
from neurosphere_workers.projections.outbox.reader import SINK_AGGREGATES, SINK_CATALOG
from pydantic import Field, ValidationError, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from neurosphere_api.federation.cache import SummaryCache
from neurosphere_api.federation.client import InProcessCellClient
from neurosphere_api.federation.service import FederationState, Federator
from neurosphere_api.hitl.ports import RecheckerReviewerAuthorizer
from neurosphere_api.map.dependencies import ViewportLimits
from neurosphere_api.realtime import configure_realtime
from neurosphere_api.recommendations.review import ReviewRouter
from neurosphere_api.recommendations.review_hitl import HitlReviewRouter
from neurosphere_api.replay.dependencies import PayloadPolicy
from neurosphere_api.replay.reader import ArchiveTraceReader, TraceReader
from neurosphere_api.runtime.builders import (
    AGGREGATE_READER,
    AUDIT_REPOSITORY,
    AUTH_SETTINGS,
    AUTHENTICATOR,
    CATALOG_REPOSITORY,
    HITL_SERVICE,
    POLICY_REPOSITORY,
    PSEUDONYMIZER,
    REVOCATION_CHECKER,
    REVOCATION_HOOKS,
    SCOPE_SOURCE,
    BuildContext,
    BuilderSpec,
    ComponentUnavailableError,
)
from neurosphere_api.runtime.builders.blob import archive_container
from neurosphere_api.runtime.pseudonym import resolve_pseudonym_key
from neurosphere_api.runtime.settings import AuthSettings
from neurosphere_api.sandbox.repository import CosmosSandboxStore, SandboxRepository

__all__ = [
    "AUDIT_CHAIN_CONTAINER",
    "AUDIT_TAIL_CONTAINER",
    "BUILDER",
    "COMPONENTS",
    "EvaluationSettings",
    "FederationSettings",
    "build",
]

COMPONENTS: Final = (
    "catalog",
    "aggregates",
    "ledger",
    "federation",
    "evaluation",
    "recommendations",
    "review_router",
    "replay",
    "map",
    "audit",
    "realtime",
)

AUDIT_CHAIN_CONTAINER: Final = "audit"
AUDIT_TAIL_CONTAINER: Final = "audit_tail"

#: The containers this module names itself (the rest come from the stores' own constants).
CATALOG_CONTAINER: Final = SINK_CATALOG
AGGREGATES_CONTAINER: Final = SINK_AGGREGATES


class FederationSettings(BaseSettings):
    """``NS_FEDERATION_*``: this deployment's own cell and the merged-summary cache."""

    model_config = SettingsConfigDict(env_prefix="NS_FEDERATION_", frozen=True, extra="forbid")

    cell_id: str = "local"
    #: Cells of other boundaries are never contacted; defaults to ``<cloud>-local``.
    boundary_id: str | None = None
    cache_ttl_seconds: float = 30.0


class EvaluationSettings(BaseSettings):
    """``NS_EVALUATION_*``: dataset ids that count as the pilot (empty = rate not estimable)."""

    model_config = SettingsConfigDict(env_prefix="NS_EVALUATION_", frozen=True, extra="forbid")

    pilot_dataset_ids: Annotated[tuple[str, ...], NoDecode] = Field(default=(), max_length=64)

    @field_validator("pilot_dataset_ids", mode="before")
    @classmethod
    def _comma_ids(cls, value: Any) -> Any:
        if isinstance(value, str):
            return tuple(part.strip() for part in value.split(",") if part.strip())
        return value


# -- helpers --------------------------------------------------------------------------------


def _backend[T](ctx: BuildContext, name: str, kind: type[T]) -> T | None:
    """A test-supplied backend of ``kind`` named ``name``; a wrong type is a failure."""
    value = ctx.overrides.backend(name)
    if value is None:
        return None
    if not isinstance(value, kind):
        raise ComponentUnavailableError(f"{name}_override_invalid")
    return value


def _utc_now() -> datetime:
    return datetime.now(UTC)


class _NoSearch:
    """No search index is composed (see the module docstring): fail closed, never empty."""

    async def search(self, *_args: Any, **_kwargs: Any) -> Any:
        raise DependencyTransientError("search is not configured", reason="search_unavailable")


def _database(ctx: BuildContext) -> Any:
    return ctx.cosmos_database()


# -- catalog --------------------------------------------------------------------------------


def _catalog(ctx: BuildContext) -> None:
    repository = _backend(ctx, "catalog_repository", CatalogRepository)
    if repository is None:
        repository = CosmosCatalogRepository(_database(ctx).get_container_client(CATALOG_CONTAINER))
    queue = _backend(ctx, "catalog_review_queue", ReviewQueue)
    if queue is None:
        queue = CosmosReviewQueue(
            _database(ctx).get_container_client(DEFAULT_REVIEW_QUEUE_CONTAINER)
        )
    graph = _backend(ctx, "catalog_graph", GraphQuery)
    if graph is None:
        graph = RepositoryGraphQuery(repository, _NoSearch())  # type: ignore[arg-type]
    state = ctx.app.state
    state.catalog_repository = repository
    state.catalog_graph = graph
    state.catalog_review_queue = queue
    state.catalog_clock = _utc_now
    ctx.publish(CATALOG_REPOSITORY, repository)


# -- aggregates, ledger ---------------------------------------------------------------------


def _aggregates(ctx: BuildContext) -> None:
    reader = _backend(ctx, "aggregate_reader", AggregateReader)
    if reader is None:
        reader = CosmosAggregateStore(_database(ctx).get_container_client(AGGREGATES_CONTAINER))
    ctx.app.state.aggregate_reader = reader
    ctx.publish(AGGREGATE_READER, reader)


def _ledger(ctx: BuildContext) -> None:
    store = _backend(ctx, "ledger_store", LedgerStore)
    if store is None:
        try:
            container = LedgerSettings().ledger_container
        except ValidationError:
            raise ComponentUnavailableError("ledger_settings_invalid") from None
        store = CosmosLedgerStore(_database(ctx).get_container_client(container))
    ctx.app.state.ledger_store = store


# -- federation -----------------------------------------------------------------------------


def _federation(ctx: BuildContext) -> None:
    try:
        conf = FederationSettings()
    except ValidationError:
        raise ComponentUnavailableError("federation_settings_invalid") from None
    authenticator = ctx.shared(AUTHENTICATOR)
    scope_source = ctx.shared(SCOPE_SOURCE)
    reader = ctx.shared(AGGREGATE_READER)
    if not isinstance(reader, AggregateReader):
        raise ComponentUnavailableError("aggregate_reader_unavailable")
    cloud = ctx.settings.cloud_profile.cloud.value
    if cloud not in ("commercial", "government"):
        raise ComponentUnavailableError("federation_cloud_invalid")
    boundary = conf.boundary_id or f"{cloud}-local"
    try:
        # The endpoint is never contacted: the local cell is served in-process.
        cell = CellRef(
            cell_id=conf.cell_id,
            cloud=cloud,  # type: ignore[arg-type]
            boundary_id=boundary,
            endpoint="https://local-cell.invalid/",
        )
        registry = CellRegistry(cells=(cell,))
        cache = SummaryCache(conf.cache_ttl_seconds)
    except (ValidationError, ValueError):
        raise ComponentUnavailableError("federation_settings_invalid") from None
    client = InProcessCellClient(
        authenticator=authenticator, scope_source=scope_source, reader=reader
    )
    ctx.app.state.federation = FederationState(
        federator=Federator(
            serving_cloud=cell.cloud,
            boundary_id=boundary,
            registry=registry,
            clients={cell.cell_id: client},
        ),
        cache=cache,
        local_cell=cell,
    )


# -- evaluation, recommendations ------------------------------------------------------------


def _evaluation(ctx: BuildContext) -> None:
    try:
        pilot = EvaluationSettings().pilot_dataset_ids
    except ValidationError:
        raise ComponentUnavailableError("evaluation_settings_invalid") from None
    store = _backend(ctx, "evaluation_store", EvaluationStore)
    if store is None:
        client = ctx.cosmos_client()
        store = CosmosEvaluationStore.from_client(client, database=ctx.store_settings().database)
    ctx.app.state.evaluation_store = store
    ctx.app.state.evaluation_pilot_dataset_ids = frozenset(pilot)


def _recommendations(ctx: BuildContext) -> None:
    store = _backend(ctx, "recommendation_store", RecommendationStore)
    if store is None:
        store = CosmosRecommendationStore.from_client(
            ctx.cosmos_client(), database=ctx.store_settings().database
        )
    ctx.app.state.recommendation_store = store


# -- audit, HITL review router --------------------------------------------------------------


def _audit(ctx: BuildContext) -> None:
    repository = _backend(ctx, "audit_repository", AuditRepository)
    if repository is None:
        repository = AuditRepository(
            CosmosAuditStore.from_client(
                ctx.cosmos_client(),
                database=ctx.store_settings().database,
                container=AUDIT_CHAIN_CONTAINER,
                tail_container=AUDIT_TAIL_CONTAINER,
            )
        )
    ctx.app.state.audit_repository = repository
    ctx.publish(AUDIT_REPOSITORY, repository)


def _hitl_service(ctx: BuildContext) -> HitlService:
    override = _backend(ctx, "hitl_service", HitlService)
    if override is not None:
        return override
    audit = ctx.shared(AUDIT_REPOSITORY)
    policies = ctx.shared(POLICY_REPOSITORY)
    revocation = ctx.shared(REVOCATION_CHECKER)
    client = ctx.cosmos_client()
    database = ctx.store_settings().database
    clock: Callable[[], float] = ctx.overrides.clock or time.time

    def now() -> datetime:
        return datetime.fromtimestamp(clock(), UTC)

    rechecker = PolicyPermissionRechecker(
        cloud=ctx.settings.cloud_profile.cloud,
        policy_repository=policies,
        revocation_checker=revocation,
        clock=now,
    )
    return HitlService(
        CosmosHitlStore.from_client(client, database=database),
        DecisionLog(audit, CosmosDecisionStore.from_client(client, database=database)),
        audit,
        ReviewPolicyRegistry(),
        RecheckerReviewerAuthorizer(rechecker),
    )


def _review_router(ctx: BuildContext) -> None:
    supplied = _backend(ctx, "review_router", ReviewRouter)
    service: HitlService | None
    try:
        service = _hitl_service(ctx)
    except ComponentUnavailableError:
        if supplied is None:
            raise
        service = None  # the planes builder reports its own ``hitl`` component
    if service is not None:
        ctx.publish(HITL_SERVICE, service)
    if supplied is not None:
        ctx.app.state.review_router = supplied
    elif service is not None:
        ctx.app.state.review_router = HitlReviewRouter(service)


# -- replay ---------------------------------------------------------------------------------


def _replay(ctx: BuildContext) -> None:
    reader = _backend(ctx, "trace_reader", TraceReader)
    if reader is None:
        reader = ArchiveTraceReader(archive_container(ctx))  # type: ignore[arg-type]
    ctx.app.state.trace_reader = reader
    ctx.app.state.replay_payload_policy = PayloadPolicy()  # bodies off unless a deployment opts in


# -- map, realtime --------------------------------------------------------------------------


def _pseudonymizer(ctx: BuildContext) -> PrincipalPseudonymizer:
    shared = ctx.maybe_shared(PSEUDONYMIZER)
    if shared is not None:
        return shared
    auth: AuthSettings = ctx.maybe_shared(AUTH_SETTINGS) or ctx.auth_settings()
    try:
        return PrincipalPseudonymizer(resolve_pseudonym_key(auth, env=ctx.settings.env))
    except InvalidSchemaError as exc:
        raise ComponentUnavailableError(exc.reason or "pseudonym_key_invalid") from None


def _map(ctx: BuildContext) -> None:
    state = ctx.app.state
    for key, reason in (
        ("catalog_graph", "catalog_graph_unavailable"),
        ("catalog_repository", "catalog_repository_unavailable"),
        ("aggregate_reader", "aggregate_reader_unavailable"),
    ):
        if getattr(state, key, None) is None:
            raise ComponentUnavailableError(reason)
    state.map_pseudonymizer = _pseudonymizer(ctx)
    state.map_viewport_limits = ViewportLimits()


def _realtime(ctx: BuildContext) -> None:
    reader = ctx.shared(AGGREGATE_READER)
    if not isinstance(reader, AggregateReader):
        raise ComponentUnavailableError("aggregate_reader_unavailable")
    clock: Callable[[], float] = ctx.overrides.clock or time.time
    try:
        registry = configure_realtime(ctx.app, aggregate_reader=reader, clock=clock)
    except (ValidationError, InvalidSchemaError):
        raise ComponentUnavailableError("realtime_settings_invalid") from None
    hooks = ctx.maybe_shared(REVOCATION_HOOKS)
    if hooks is not None:
        hooks.register_push_registry("websocket", registry)


# -- sandbox --------------------------------------------------------------------------------


def _sandbox(ctx: BuildContext) -> None:
    """Best effort and local only: failure leaves the lazy 503 behaviour of the sandbox router."""
    repository: object | None = ctx.overrides.backend("sandbox_repository")
    if isinstance(repository, SandboxRepository):
        ctx.app.state.sandbox_repository = repository
        return
    if ctx.settings.env != "local":
        return
    try:
        client = ctx.cosmos_client()
    except ComponentUnavailableError:
        return
    ctx.app.state.sandbox_repository = SandboxRepository(CosmosSandboxStore(client))


def build(ctx: BuildContext) -> None:
    ctx.attempt("catalog", lambda: _catalog(ctx))
    ctx.attempt("aggregates", lambda: _aggregates(ctx))
    ctx.attempt("ledger", lambda: _ledger(ctx))
    ctx.attempt("evaluation", lambda: _evaluation(ctx))
    ctx.attempt("recommendations", lambda: _recommendations(ctx))
    ctx.attempt("audit", lambda: _audit(ctx))
    ctx.attempt("replay", lambda: _replay(ctx))
    ctx.attempt("federation", lambda: _federation(ctx))
    ctx.attempt("review_router", lambda: _review_router(ctx))
    ctx.attempt("map", lambda: _map(ctx))
    ctx.attempt("realtime", lambda: _realtime(ctx))
    _sandbox(ctx)


BUILDER: Final = BuilderSpec("data", COMPONENTS, build)
