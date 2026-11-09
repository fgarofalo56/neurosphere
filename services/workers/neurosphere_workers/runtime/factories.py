"""Role registry: each role name maps to a builder that wires it from settings.

A builder receives the process :class:`RuntimeConfig` and a per-attempt ``ClientLifetime`` and
returns a :class:`~neurosphere_workers.runtime.supervisor.RoleRunnable`. Everything is built
against the Cosmos/Blob/Event Hubs factories in ``neurosphere_core.clients``; no role imports
``services/api``. Missing role-specific configuration raises ``RoleConfigError`` (terminal for
that role only); infrastructure errors propagate and the supervisor retries with backoff.

Role -> class:

* ``ingestion``       ``IngestionConsumer`` (Event Hubs -> ledger/archive/outbox)
* ``projections``     ``OutboxReader`` -> ``CatalogProjection`` (sink ``catalog``)
* ``aggregates``      ``OutboxReader`` -> ``AggregateProjection`` (sink ``aggregates``)
* ``actions``         ``ActionExecutorWorker`` (only intents in ``executing``); write targets
                      from ``NS_FOUNDRY_*``/``NS_APIM_*`` (:func:`register_write_targets`),
                      plus ``ReviewReconcileWorker`` (closes stale maker-checker items) in the
                      same process on the same services (:func:`actions_role`)
* ``hitl_timers``     ``HitlTimerWorker``
* ``lifecycle``       ``LifecycleWorker``
* ``recommendations`` periodic ``run_pipeline``
* ``evaluation``      periodic online ``EvaluationService`` run
* ``gateway_poll``    ``GatewayPoller`` (APIM gateway logs -> ingest API; idles if unconfigured)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import socket
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from functools import partial
from pathlib import Path
from typing import Any, Final

import httpx
from azure.core.credentials_async import AsyncTokenCredential
from azure.cosmos import CosmosClient as SyncCosmosClient
from azure.cosmos.aio import CosmosClient, DatabaseProxy
from azure.identity import DefaultAzureCredential as SyncDefaultAzureCredential
from azure.identity.aio import DefaultAzureCredential
from azure.storage.blob.aio import ContainerClient
from neurosphere_connector.write import WriteTargetRegistry
from neurosphere_connector_foundry_actions import create_swap_connector
from neurosphere_core.actions import ActionAuditor, ActionService
from neurosphere_core.actions.audit import AuditRepositoryActionAuditor
from neurosphere_core.actions.cosmos_store import CosmosExecutionControl, CosmosIntentStore
from neurosphere_core.actions.recheck import PolicyPermissionRechecker
from neurosphere_core.actions.targets import ACTION_CONNECTORS, APIM_GATEWAY_CONNECTOR
from neurosphere_core.aggregates.cosmos import CosmosAggregateStore
from neurosphere_core.audit.cosmos_store import CosmosAuditStore
from neurosphere_core.audit.repository import AuditRepository
from neurosphere_core.capabilities import load_matrix
from neurosphere_core.catalog.repo.cosmos import CosmosCatalogRepository
from neurosphere_core.catalog.review_queue_cosmos import CosmosReviewQueue
from neurosphere_core.clients import (
    ClientLifetime,
    arm_client,
    blob_account_url,
    create_checkpoint_store,
    create_cosmos_client,
    create_eventhub_consumer,
)
from neurosphere_core.clients.factories import (
    ENV_BLOB_CONNECTION_STRING,
    ENV_COSMOS_ENDPOINT,
    ENV_COSMOS_KEY,
)
from neurosphere_core.cloud import Settings, load_settings
from neurosphere_core.copilot.models.endpoints import AdapterConfig, endpoint_problem
from neurosphere_core.deploy.register import CustomerScopedRegister, LiveInventory, RegisterStore
from neurosphere_core.errors import CapabilityUnavailableError, InvalidSchemaError, ValidationIssue
from neurosphere_core.evaluation.calibration import LabelSet, ingest_labels
from neurosphere_core.evaluation.cosmos_store import CosmosEvaluationStore
from neurosphere_core.evaluation.endpoint_judge import EndpointJudge
from neurosphere_core.evaluation.judge import Judge, RecordedFixtureJudge
from neurosphere_core.evaluation.registry import (
    DatasetItem,
    DatasetVersion,
    Dimension,
    EvaluationRegistry,
    JudgeConfig,
    RubricVersion,
)
from neurosphere_core.evaluation.store import EvaluationStore
from neurosphere_core.gateway import (
    CosmosGatewayStore,
    GatewayRegistration,
    GatewayStore,
    create_gateway_container,
)
from neurosphere_core.gateway.models import GATEWAY_ID_PATTERN
from neurosphere_core.hitl import HitlService, ReviewPolicyRegistry
from neurosphere_core.hitl.decisions import DecisionLog
from neurosphere_core.hitl_cosmos.store import CosmosDecisionStore, CosmosHitlStore
from neurosphere_core.ledger import PriceTable
from neurosphere_core.ledger.cosmos import CosmosLedgerStore
from neurosphere_core.lifecycle import LifecycleEngine, TargetRegistry
from neurosphere_core.lifecycle.cosmos import (
    CosmosHoldRegistry,
    CosmosMappingStore,
    CosmosRequestQueue,
)
from neurosphere_core.pricing import InMemoryPriceSnapshotStore
from neurosphere_core.pricing.cosmos_store import CosmosPriceSnapshotStore
from neurosphere_core.pricing.models import PriceSnapshot
from neurosphere_core.recommendations.cosmos_store import CosmosRecommendationStore
from neurosphere_core.scope import IdentityScope
from neurosphere_core.stores import ensure_local_containers
from pydantic import ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

from neurosphere_workers.actions import (
    ActionExecutor,
    ActionExecutorWorker,
    ReviewItemCompletion,
    ReviewReconcileWorker,
)
from neurosphere_workers.actions.apim import (
    ApplyRecords,
    GatewayArm,
    PublicationRecorder,
    PublicationRecordingExecutor,
    apim_record_store,
    build_apim_gateway_connector,
    build_http_apim_gateway_connector,
)
from neurosphere_workers.actions.deploy import DeployConnector, PlanApprovals
from neurosphere_workers.aggregates.handler import AggregateProjection
from neurosphere_workers.aggregates.sources import StoreLedgerSource
from neurosphere_workers.archive.settings import ArchiveSettings
from neurosphere_workers.evaluation.budget import BudgetLedger, BudgetLimits
from neurosphere_workers.evaluation.labels import (
    HitlLabelSource,
    SampleConfig,
    open_calibration_sample,
)
from neurosphere_workers.evaluation.models import ItemOutcome
from neurosphere_workers.evaluation.pipeline import (
    CalibrationSettings,
    OfflineStage,
    PipelineSummary,
)
from neurosphere_workers.evaluation.pipeline import (
    run_pipeline as run_evaluation_pipeline,
)
from neurosphere_workers.evaluation.service import (
    EvaluationService,
    OfflineRunConfig,
    OnlineRunConfig,
)
from neurosphere_workers.hitl_timers.worker import HitlTimerWorker
from neurosphere_workers.ingestion.consumer import IngestionConsumer
from neurosphere_workers.ingestion.gateway_poll import (
    GatewayPoller,
    GatewayPollSettings,
    IngestClient,
    default_connector_factory,
)
from neurosphere_workers.ingestion.settings import IngestionSettings
from neurosphere_workers.ingestion.wiring import build_pipeline_deps
from neurosphere_workers.lifecycle.worker import JobSource, LifecycleWorker
from neurosphere_workers.projections.catalog import CatalogProjection
from neurosphere_workers.projections.outbox import (
    SINK_AGGREGATES,
    SINK_CATALOG,
    CosmosCheckpointStore,
    CosmosOutboxStore,
    OutboxReader,
    SinkHandler,
)
from neurosphere_workers.publication import CatalogPublicationRecorder, CosmosApplyRecordLookup
from neurosphere_workers.recommendations.pipeline import run_pipeline
from neurosphere_workers.recommendations.projection.models import CandidatePairConfig
from neurosphere_workers.runtime.adapters import (
    IdleRole,
    IngestionRole,
    MultiWorkerRole,
    PeriodicTick,
    TickWorker,
    WorkerRole,
)
from neurosphere_workers.runtime.archive_reader import (
    ArchiveReader,
    ArchiveRecordSource,
    ArchiveTraceEventSource,
)
from neurosphere_workers.runtime.checkpoint import CheckpointStore, CosmosRuntimeCheckpointStore
from neurosphere_workers.runtime.identity import PolicyStack, build_identity, build_policy_stack
from neurosphere_workers.runtime.price_refresh import PriceTableRefresher
from neurosphere_workers.runtime.roles import RoleConfigError
from neurosphere_workers.runtime.settings import (
    ApimWriteSettings,
    AuthSettings,
    EvalSettings,
    FoundryWriteSettings,
    RecommendationSettings,
    StoreSettings,
    WorkerSettings,
)
from neurosphere_workers.runtime.supervisor import RoleFactory, RoleRunnable

__all__ = [
    "BUILDERS",
    "SUPPORTED_WRITE_CONNECTORS",
    "DeploySources",
    "DeployWriteSettings",
    "RoleBuilder",
    "RuntimeConfig",
    "WriteTargetSeams",
    "WriteTargetSources",
    "compose_action_executor",
    "load_deploy_write_settings",
    "load_write_target_settings",
    "register_deploy_target",
    "register_write_targets",
    "role_factories",
]

logger = logging.getLogger("neurosphere.workers.runtime")

_CATALOG_CONTAINER: Final = "catalog"
_AGGREGATES_CONTAINER: Final = "aggregates"
_LEDGER_CONTAINER: Final = "cost-ledger"
_OUTBOX_CONTAINER: Final = "outbox"
_OUTBOX_CHECKPOINT_CONTAINER: Final = "outbox-checkpoints"
_AUDIT_CONTAINER: Final = "audit"
_AUDIT_TAIL_CONTAINER: Final = "audit_tail"
_LOCAL_COSMOS_DEFAULT: Final = "http://localhost:8081"
_PRUNE_INTERVAL_SECONDS: Final = 3600.0
_LIFECYCLE_NO_SOURCE: Final = "lifecycle_no_job_source"


@dataclass(frozen=True, slots=True)
class RuntimeConfig:
    """Everything a role builder reads (settings objects, never raw environment)."""

    settings: Settings
    worker: WorkerSettings
    store: StoreSettings
    auth: AuthSettings

    @classmethod
    def from_env(cls) -> RuntimeConfig:
        return cls(load_settings(), WorkerSettings(), StoreSettings(), AuthSettings())

    @property
    def customer_id(self) -> str:
        customer = self.auth.resolved_customer_id(self.settings.env)
        if customer is None:
            raise RoleConfigError("customer_id_missing")
        return customer

    @property
    def tenant_id(self) -> str | None:
        return self.worker.tenant_id or self.auth.tenant_id

    @property
    def cloud(self) -> str:
        return self.settings.cloud_profile.cloud.value


RoleBuilder = Callable[[RuntimeConfig, ClientLifetime], Awaitable[RoleRunnable]]


# --------------------------------------------------------------------------------------------
# shared plumbing


async def _cosmos(cfg: RuntimeConfig, lifetime: ClientLifetime) -> CosmosClient:
    client = create_cosmos_client(cfg.settings, lifetime=lifetime, account=cfg.store.cosmos_account)
    if cfg.settings.env == "local":
        await ensure_local_containers(client, cfg.settings, database=cfg.store.database)
    return client


def _database(cfg: RuntimeConfig, client: CosmosClient) -> DatabaseProxy:
    return client.get_database_client(cfg.store.database)


def _runtime_checkpoints(cfg: RuntimeConfig, client: CosmosClient) -> CosmosRuntimeCheckpointStore:
    """Durable checkpoints for batch roles: the shared ``outbox-checkpoints`` container."""
    return CosmosRuntimeCheckpointStore(
        _database(cfg, client).get_container_client(_OUTBOX_CHECKPOINT_CONTAINER),
        customer_id=cfg.customer_id,
    )


def _archive_container(cfg: RuntimeConfig, lifetime: ClientLifetime) -> ContainerClient:
    archive = ArchiveSettings()
    if cfg.settings.env == "local":
        conn = os.environ.get(ENV_BLOB_CONNECTION_STRING)
        if not conn:
            raise RoleConfigError("blob_connection_string_missing")
        return lifetime.register(ContainerClient.from_connection_string(conn, archive.container))
    if not archive.storage_account:
        raise RoleConfigError("archive_storage_account_missing")
    credential = lifetime.register(
        DefaultAzureCredential(authority=cfg.settings.cloud_profile.login_host)
    )
    url = blob_account_url(cfg.settings.cloud_profile, archive.storage_account)
    return lifetime.register(ContainerClient(url, archive.container, credential=credential))


def _tick_role(name: str, tick: Callable[[], Awaitable[None]], cfg: RuntimeConfig) -> WorkerRole:
    return WorkerRole(TickWorker(name, tick), idle_seconds=cfg.worker.poll_seconds)


def _drain_tick(
    reader: OutboxReader, sink: str, customer_id: str, handler: SinkHandler
) -> Callable[[], Awaitable[None]]:
    async def tick() -> None:
        result = await reader.drain(sink, customer_id, handler)
        if not result.ok:
            # Exception class name only. The entry stays at the checkpoint and is retried.
            logger.warning(
                "outbox sink stopped at a failing entry",
                extra={"event": "worker.sink_stalled", "sink": sink, "error": result.error},
            )

    return tick


def _sync_cosmos(cfg: RuntimeConfig) -> SyncCosmosClient:
    """The sync client the price snapshot protocol requires (always used off the event loop)."""
    if cfg.settings.env == "local":
        key = os.environ.get(ENV_COSMOS_KEY)
        if not key:
            raise RoleConfigError("cosmos_key_missing")
        endpoint = os.environ.get(ENV_COSMOS_ENDPOINT, _LOCAL_COSMOS_DEFAULT)
        return SyncCosmosClient(endpoint, key, enable_endpoint_discovery=False)
    account = cfg.store.cosmos_account
    if not account:
        raise RoleConfigError("cosmos_account_missing")
    url = cfg.settings.cloud_profile.cosmos_endpoint(account)
    return SyncCosmosClient(
        url, SyncDefaultAzureCredential(authority=cfg.settings.cloud_profile.login_host)
    )


async def _price_snapshots(cfg: RuntimeConfig) -> InMemoryPriceSnapshotStore:
    """Load every price snapshot through the sync Cosmos store in a thread (never on the loop)."""

    def load() -> InMemoryPriceSnapshotStore:
        client = _sync_cosmos(cfg)
        try:
            store = CosmosPriceSnapshotStore.from_client(client, database=cfg.store.database)
            return InMemoryPriceSnapshotStore(store.list_snapshots())
        finally:
            close = getattr(client, "close", None)
            if callable(close):
                close()

    return await asyncio.to_thread(load)


async def _list_price_snapshots(cfg: RuntimeConfig) -> list[PriceSnapshot]:
    return (await _price_snapshots(cfg)).list_snapshots()


def _config_error(pointer: str, detail: str) -> InvalidSchemaError:
    return InvalidSchemaError(detail, errors=[ValidationIssue(pointer, detail)], reason="config")


# --------------------------------------------------------------------------------------------
# ingestion


async def build_ingestion(cfg: RuntimeConfig, lifetime: ClientLifetime) -> RoleRunnable:
    base = IngestionSettings()
    ingestion = base.model_copy(
        update={
            "cosmos_database": cfg.store.database,
            "cosmos_account": base.cosmos_account or cfg.store.cosmos_account,
        }
    )
    deps = await build_pipeline_deps(cfg.settings, lifetime=lifetime, ingestion=ingestion)
    checkpoint_store = create_checkpoint_store(
        cfg.settings,
        lifetime=lifetime,
        container=ingestion.checkpoint_container,
        account=ingestion.storage_account,
    )
    client = create_eventhub_consumer(
        cfg.settings,
        lifetime=lifetime,
        eventhub_name=ingestion.eventhub_name,
        consumer_group=ingestion.consumer_group,
        namespace=ingestion.eventhubs_namespace,
        checkpoint_store=checkpoint_store,
    )
    return IngestionRole(IngestionConsumer(client, deps, ingestion))


# --------------------------------------------------------------------------------------------
# projections and aggregates


def _outbox_reader(db: DatabaseProxy) -> OutboxReader:
    return OutboxReader(
        CosmosOutboxStore(db.get_container_client(_OUTBOX_CONTAINER)),
        CosmosCheckpointStore(db.get_container_client(_OUTBOX_CHECKPOINT_CONTAINER)),
    )


async def build_projections(cfg: RuntimeConfig, lifetime: ClientLifetime) -> RoleRunnable:
    customer = cfg.customer_id
    cosmos = await _cosmos(cfg, lifetime)
    db = _database(cfg, cosmos)
    stack = build_policy_stack(
        cfg.settings, cosmos=cosmos, auth=cfg.auth, store=cfg.store, tenant_id=cfg.tenant_id
    )
    identity = build_identity(cfg.settings, stack=stack, worker=cfg.worker, customer_id=customer)
    source = ArchiveTraceEventSource(ArchiveReader(_archive_container(cfg, lifetime)))
    projection = CatalogProjection(
        repository=CosmosCatalogRepository(db.get_container_client(_CATALOG_CONTAINER)),
        review_queue=CosmosReviewQueue.from_client(cosmos, database=cfg.store.database),
        source=source,
        scope_provider=identity.scope_provider,
    )
    tick = _drain_tick(_outbox_reader(db), SINK_CATALOG, customer, projection.handle)
    return _tick_role("projections", tick, cfg)


async def build_aggregates(cfg: RuntimeConfig, lifetime: ClientLifetime) -> RoleRunnable:
    customer = cfg.customer_id
    cosmos = await _cosmos(cfg, lifetime)
    db = _database(cfg, cosmos)
    initial = await _list_price_snapshots(cfg)
    refresher = PriceTableRefresher(
        partial(_list_price_snapshots, cfg), initial, cfg.worker.price_refresh_seconds
    )
    reader = _outbox_reader(db)
    store = CosmosAggregateStore(db.get_container_client(_AGGREGATES_CONTAINER))
    ledger = StoreLedgerSource(CosmosLedgerStore(db.get_container_client(_LEDGER_CONTAINER)))
    events = ArchiveTraceEventSource(ArchiveReader(_archive_container(cfg, lifetime)))

    def make_projection(prices: PriceTable) -> AggregateProjection:
        return AggregateProjection(store=store, ledger=ledger, events=events, prices=prices)

    projection = make_projection(refresher.table)

    async def prune_job() -> None:
        await _prune(projection, customer)

    prune = PeriodicTick(prune_job, _PRUNE_INTERVAL_SECONDS)

    async def tick() -> None:
        nonlocal projection
        # Swap only here, between drains, so an entry never sees two price tables.
        if await refresher.refresh_if_due():
            projection = make_projection(refresher.table)
        await _drain_tick(reader, SINK_AGGREGATES, customer, projection.handle)()
        await prune()

    return _tick_role("aggregates", tick, cfg)


async def _prune(projection: AggregateProjection, customer_id: str) -> None:
    await projection.prune(customer_id)


# --------------------------------------------------------------------------------------------
# actions, hitl timers, lifecycle


class _NoReviewerAuthorizer:
    """Timers never authorize a reviewer; this fails closed if anything ever asks."""

    async def can_review(
        self, principal_id: str, customer_id: str, domain_id: str, permission: Any
    ) -> bool:
        return False


def _audit(cfg: RuntimeConfig, cosmos: CosmosClient) -> AuditRepository:
    return AuditRepository(
        CosmosAuditStore.from_client(
            cosmos,
            database=cfg.store.database,
            container=_AUDIT_CONTAINER,
            tail_container=_AUDIT_TAIL_CONTAINER,
        )
    )


def _hitl_service(cfg: RuntimeConfig, cosmos: CosmosClient, audit: AuditRepository) -> HitlService:
    return HitlService(
        CosmosHitlStore.from_client(cosmos, database=cfg.store.database),
        DecisionLog(audit, CosmosDecisionStore.from_client(cosmos, database=cfg.store.database)),
        audit,
        ReviewPolicyRegistry(),
        _NoReviewerAuthorizer(),
    )


def warn_if_actions_idle(registry: WriteTargetRegistry) -> bool:
    """Log one structured warning when no write target is registered; returns True if idle.

    An empty registry is the designed fail-closed state (per-connector ENABLED flags default off),
    but the role must never start and silently do nothing. Only the warning is emitted: the
    ``actions`` role also runs the review-reconcile sweep (real work that needs no write target),
    so the role stays ``running`` rather than ``idle``.
    """
    if registry.names():
        return False
    logger.warning(
        "actions role is idle by configuration: no write target is enabled; "
        "set NS_FOUNDRY_ENABLED and/or NS_APIM_ENABLED (with their target settings)",
        extra={
            "event": "worker.actions_idle_by_config",
            "enable_flags": ["NS_FOUNDRY_ENABLED", "NS_APIM_ENABLED"],
        },
    )
    return True


async def build_actions(cfg: RuntimeConfig, lifetime: ClientLifetime) -> RoleRunnable:
    cosmos = await _cosmos(cfg, lifetime)
    stack = build_policy_stack(
        cfg.settings, cosmos=cosmos, auth=cfg.auth, store=cfg.store, tenant_id=cfg.tenant_id
    )
    audit = _audit(cfg, cosmos)
    auditor = AuditRepositoryActionAuditor(audit)
    store = CosmosIntentStore.from_client(cosmos, database=cfg.store.database)
    control = CosmosExecutionControl.from_client(cosmos, database=cfg.store.database)
    rechecker = PolicyPermissionRechecker(
        cloud=cfg.settings.cloud_profile.cloud,
        policy_repository=stack.policy,
        revocation_checker=stack.revocation,
    )
    service = ActionService(store, auditor=auditor, rechecker=rechecker, execution_control=control)
    # Write connectors come ONLY from NS_FOUNDRY_*/NS_APIM_* (see register_write_targets). With
    # neither configured the registry is empty and every intent fails closed with
    # capability_unavailable (no connector call, no pretend change).
    registry, gateways = await _action_write_targets(cfg, lifetime, cosmos)
    hitl = _hitl_service(cfg, cosmos, audit)
    executor = compose_action_executor(
        service,
        registry,
        auditor=auditor,
        recorder=_publication_recorder(cfg, cosmos, audit, stack, registry),
        execution_control=control,
        worker_id=cfg.worker.worker_id or f"{socket.gethostname()}-{os.getpid()}",
        on_finished=ReviewItemCompletion(hitl, auditor=auditor),
        gateways=gateways,
    )
    warn_if_actions_idle(registry)
    return actions_role(
        cfg,
        executor_worker=ActionExecutorWorker(executor, store),
        hitl=hitl,
        actions=service,
        auditor=auditor,
        checkpoints=_runtime_checkpoints(cfg, cosmos),
    )


def compose_action_executor(
    service: ActionService,
    registry: WriteTargetRegistry,
    *,
    auditor: ActionAuditor,
    recorder: PublicationRecorder | None,
    **options: Any,
) -> ActionExecutor:
    """The plain executor, or (with a ``recorder``) the one that hands a succeeded, verified
    Grant/McpServer publication to the catalog after the executor has returned (PRP-34 item 10)."""
    if recorder is None:
        return ActionExecutor(service, registry, **options)
    return PublicationRecordingExecutor(
        service, registry, recorder=recorder, auditor=auditor, **options
    )


def _publication_recorder(
    cfg: RuntimeConfig,
    cosmos: CosmosClient,
    audit: AuditRepository,
    stack: PolicyStack,
    registry: WriteTargetRegistry,
) -> CatalogPublicationRecorder | None:
    """The catalog recorder, only when an APIM gateway connector is registered.

    The recorder writes with the worker's OWN derived workload scope (it needs ``catalog.curate``
    in the entity's domain); ``RoleConfigError`` when that identity is not configured, so a
    publishing worker never silently runs without its provenance hand-off.
    """
    if APIM_GATEWAY_CONNECTOR not in registry.names():
        return None
    identity = build_identity(
        cfg.settings, stack=stack, worker=cfg.worker, customer_id=cfg.customer_id
    )
    return CatalogPublicationRecorder(
        CosmosCatalogRepository(_database(cfg, cosmos).get_container_client(_CATALOG_CONTAINER)),
        audit,
        identity.scope_provider,
        records=CosmosApplyRecordLookup(cosmos, database=cfg.store.database),
    )


def actions_role(
    cfg: RuntimeConfig,
    *,
    executor_worker: ActionExecutorWorker,
    hitl: HitlService,
    actions: ActionService,
    auditor: ActionAuditor,
    checkpoints: CheckpointStore | None = None,
) -> MultiWorkerRole:
    """The ``actions`` role: the executor plus the review-reconcile sweep, on shared services.

    The sweep (PRP-17 audit close-out) closes review items the executor's completion hook could
    not reach; it uses the very HitlService/ActionService/auditor the executor was built with and
    never touches a target system.
    """
    reconcile = ReviewReconcileWorker(
        hitl,
        actions,
        auditor=auditor,
        # cfg.customer_id raises RoleConfigError rather than yielding None: the runtime must never
        # build an unscoped (all-customer) sweep.
        customer_id=cfg.customer_id,
    )
    return MultiWorkerRole(
        [executor_worker, reconcile],
        idle_seconds=cfg.worker.poll_seconds,
        checkpoints=checkpoints,
    )


async def _action_write_targets(
    cfg: RuntimeConfig, lifetime: ClientLifetime, cosmos: CosmosClient
) -> tuple[WriteTargetRegistry, CosmosGatewayStore | None]:
    """The executor's registry, plus the gateway registry its APIM binding check reads."""
    try:
        foundry, apim = load_write_target_settings()
        deploy = load_deploy_write_settings()
    except ValueError:
        raise RoleConfigError("write_target_settings_invalid") from None
    gateways: CosmosGatewayStore | None = None
    sources = WriteTargetSources()
    if apim.enabled:
        gateways = CosmosGatewayStore.from_client(cosmos, database=cfg.store.database)

        def records_for(registration: GatewayRegistration) -> ApplyRecords:
            return apim_record_store(cosmos, database=cfg.store.database, registration=registration)

        sources = WriteTargetSources(gateway_store=gateways, records_for=records_for)
    registry = WriteTargetRegistry()
    await register_write_targets(
        registry,
        settings=cfg.settings,
        customer_id=cfg.auth.resolved_customer_id(cfg.settings.env),
        lifetime=lifetime,
        foundry=foundry,
        apim=apim,
        sources=sources,
        # No durable PlanApprovals exists yet (the approval store is per API process), so an
        # enabled deploy target is skipped here with `deploy_sources_unconfigured`: fail closed.
        deploy=deploy,
    )
    return registry, gateways


async def build_hitl_timers(cfg: RuntimeConfig, lifetime: ClientLifetime) -> RoleRunnable:
    cosmos = await _cosmos(cfg, lifetime)
    service = _hitl_service(cfg, cosmos, _audit(cfg, cosmos))
    return WorkerRole(
        HitlTimerWorker(service),
        idle_seconds=cfg.worker.poll_seconds,
        checkpoints=_runtime_checkpoints(cfg, cosmos),
    )


def _lifecycle_job_source() -> JobSource | None:
    """Where requested lifecycle jobs come from; ``None`` when no store holds them.

    The Cosmos request queue only holds requests the engine already blocked (it is drained by
    ``process_queue``); nothing persists a freshly *requested* job for a worker to pick up, and
    inventing that contract is out of scope. Until one exists the role cannot do any work.
    """
    return None


def _lifecycle_targets() -> TargetRegistry:
    """Lifecycle targets (catalog, archive, ledger, conversations) bound by the owning deployment;
    none are bound by the runtime today, so every request would fail closed."""
    return TargetRegistry()


async def build_lifecycle(cfg: RuntimeConfig, lifetime: ClientLifetime) -> RoleRunnable:
    source = _lifecycle_job_source()
    if source is None:
        # Explicitly idle by configuration: reported `idle` with this reason on /healthz and
        # /readyz, never polling, and not counted against readiness.
        logger.warning(
            "lifecycle role is idle: no source of requested jobs is wired",
            extra={"event": "worker.lifecycle_inert", "reason": _LIFECYCLE_NO_SOURCE},
        )
        return IdleRole(_LIFECYCLE_NO_SOURCE)
    customer = cfg.customer_id
    cosmos = await _cosmos(cfg, lifetime)
    database = cfg.store.database
    engine = LifecycleEngine(
        targets=_lifecycle_targets(),
        holds=CosmosHoldRegistry.from_client(cosmos, database=database, customer_id=customer),
        queue=CosmosRequestQueue.from_client(cosmos, database=database, customer_id=customer),
        audit=_audit(cfg, cosmos),
        audit_chain_id=f"lifecycle.{customer}",
        cloud=cfg.cloud,  # type: ignore[arg-type]
        customer_id=customer,
        mappings=CosmosMappingStore.from_client(cosmos, database=database, customer_id=customer),
    )
    return WorkerRole(
        LifecycleWorker(engine, source),
        idle_seconds=cfg.worker.poll_seconds,
        checkpoints=_runtime_checkpoints(cfg, cosmos),
    )


# --------------------------------------------------------------------------------------------
# recommendations and evaluation


def _pairs(path: Path | None) -> CandidatePairConfig:
    if path is None:
        return CandidatePairConfig(config_id="pairs-none", version="0", pairs=())
    try:
        return CandidatePairConfig.model_validate(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        raise RoleConfigError("pairs_file_invalid") from None


async def build_recommendations(cfg: RuntimeConfig, lifetime: ClientLifetime) -> RoleRunnable:
    rec = RecommendationSettings()
    if rec.data_dir is None:
        raise RoleConfigError("recommendations_data_dir_missing")
    if not rec.data_dir.is_dir():
        raise RoleConfigError("recommendations_data_dir_invalid")
    customer = cfg.customer_id
    cosmos = await _cosmos(cfg, lifetime)
    stack = build_policy_stack(
        cfg.settings, cosmos=cosmos, auth=cfg.auth, store=cfg.store, tenant_id=cfg.tenant_id
    )
    identity = build_identity(cfg.settings, stack=stack, worker=cfg.worker, customer_id=customer)
    store = CosmosRecommendationStore.from_client(cosmos, database=cfg.store.database)
    pairs = _pairs(rec.pairs_file)
    data_dir = rec.data_dir

    async def job() -> None:
        scope = await identity.scope_provider.get()
        prices = await _price_snapshots(cfg)
        summary = await run_pipeline(
            data_dir,
            scope=scope,
            store=store,
            prices=prices,
            pairs=pairs,
            created_at=datetime.now(UTC),
        )
        logger.info(
            "recommendations pipeline finished",
            extra={"event": "worker.recommendations", "stored": summary.stored},
        )

    tick = PeriodicTick(job, rec.interval_seconds)
    return _tick_role("recommendations", tick, cfg)


def _read_json(directory: Path, name: str, key: str) -> list[Any]:
    try:
        doc = json.loads((directory / name).read_text(encoding="utf-8"))
        return list(doc[key])
    except (OSError, ValueError, KeyError, TypeError):
        raise RoleConfigError("evaluation_data_invalid") from None


def _evaluation_registry(
    directory: Path, evaluation: EvalSettings
) -> tuple[EvaluationRegistry, RubricVersion, JudgeConfig]:
    registry = EvaluationRegistry()
    try:
        for raw in _read_json(directory, "datasets.json", "datasets"):
            registry.datasets.register(DatasetVersion.model_validate(raw))
        for raw in _read_json(directory, "rubrics.json", "rubrics"):
            registry.rubrics.register(RubricVersion.model_validate(raw))
        for raw in _read_json(directory, "judge_configs.json", "judge_configs"):
            registry.judge_configs.register(JudgeConfig.model_validate(raw))
    except ValueError:
        raise RoleConfigError("evaluation_data_invalid") from None
    rubric = registry.rubrics.get(evaluation.rubric_id, evaluation.rubric_version)
    judge = registry.judge_configs.get(evaluation.judge_config_id, evaluation.judge_config_version)
    if rubric is None:
        raise RoleConfigError("evaluation_rubric_unregistered")
    if judge is None:
        raise RoleConfigError("evaluation_judge_unregistered")
    if registry.datasets.get(evaluation.frame_dataset_id, evaluation.frame_dataset_version) is None:
        # The sampling frame describes the archive itself (redacted spans); it carries no items
        # of its own beyond this descriptor.
        registry.datasets.register(
            DatasetVersion.build(
                dataset_id=evaluation.frame_dataset_id,
                version=evaluation.frame_dataset_version,
                kind="sampling_frame",
                dimensions=rubric.dimensions,
                items=(
                    DatasetItem(
                        item_id="frame-archive",
                        dimension=rubric.dimensions[0],
                        classification="public",
                        payload={"frame": "redacted archive spans"},
                    ),
                ),
                data_state="redacted",
                created_at="2026-01-01T00:00:00Z",
            )
        )
    return registry, rubric, judge


def _evaluation_judge(
    cfg: RuntimeConfig,
    evaluation: EvalSettings,
    directory: Path,
    credential: Callable[[], AsyncTokenCredential],
) -> Judge:
    """The judge for both stages. ``endpoint`` fails closed (never falls back to fixtures) and
    builds the credential only when selected; no request is made at build time."""
    if evaluation.judge == "fixture":
        try:
            return RecordedFixtureJudge.from_file(directory / "judge_fixtures.json")
        except (OSError, ValueError):
            raise RoleConfigError("evaluation_fixtures_invalid") from None
    cloud: Any = cfg.cloud
    problem = endpoint_problem(cloud, evaluation.judge_endpoint)
    if problem is not None:
        raise RoleConfigError(f"evaluation_judge_{problem[0]}")
    try:
        adapter = AdapterConfig(
            kind="approved_endpoint",
            endpoint=evaluation.judge_endpoint,
            deployment=evaluation.judge_deployment,
            api_version=evaluation.judge_api_version,
        )
    except ValidationError:
        raise RoleConfigError("evaluation_judge_config_invalid") from None
    try:
        return EndpointJudge(adapter, cloud=cloud, credential=credential())
    except CapabilityUnavailableError as exc:
        raise RoleConfigError(f"evaluation_judge_{exc.reason or 'unavailable'}") from None


def _pilot_datasets(registry: EvaluationRegistry, evaluation: EvalSettings) -> list[DatasetVersion]:
    """Registered pilot datasets (latest version each); misconfiguration fails the role build."""
    ids = evaluation.pilot_ids
    if not ids:
        return []
    if evaluation.pilot_domain_id is None:
        raise RoleConfigError("evaluation_pilot_domain_missing")
    if evaluation.pilot_subject_id is None:
        raise RoleConfigError("evaluation_pilot_subject_missing")
    found: list[DatasetVersion] = []
    for ident in ids:
        dataset = registry.datasets.latest(ident)
        if dataset is None:
            raise RoleConfigError("evaluation_pilot_dataset_unregistered")
        found.append(dataset)
    return found


@dataclass(frozen=True)
class _OfflineEvaluation:
    """Offline pilot + calibration + HITL label loop for the ``evaluation`` role (PRP-16 item 10).

    Per dataset: run the pipeline with a fresh ledger; the labels come from the SAME run's
    per-item outcomes (decided calibration review items); afterwards a new calibration sample is
    opened so the next run has items to label. Everything is authorized under the worker scope.
    """

    registry: EvaluationRegistry
    rubric: RubricVersion
    judge_config: JudgeConfig
    judge: Judge
    store: EvaluationStore
    hitl: HitlService
    datasets: tuple[DatasetVersion, ...]
    settings: EvalSettings
    customer_id: str
    cloud: str
    clock: Callable[[], datetime] = field(default=lambda: datetime.now(UTC))

    def _ledger(self) -> BudgetLedger:
        ev = self.settings
        return BudgetLedger(
            run_limits=BudgetLimits(tokens=ev.run_token_budget, cost=Decimal(ev.run_cost_budget)),
            domain_limits=BudgetLimits(
                tokens=ev.domain_token_budget, cost=Decimal(ev.domain_cost_budget)
            ),
        )

    def _require_scope(self, scope: IdentityScope) -> str:
        domain = self.settings.pilot_domain_id
        if (
            domain is None
            or scope.customer_id != self.customer_id
            or domain not in set(scope.allowed_domains)
        ):
            raise RoleConfigError("evaluation_pilot_domain_out_of_scope")
        return domain

    async def run(self, scope: IdentityScope) -> list[PipelineSummary]:
        domain = self._require_scope(scope)
        subject = self.settings.pilot_subject_id
        if subject is None:
            raise RoleConfigError("evaluation_pilot_subject_missing")
        now = self.clock()
        return [
            await self._run_dataset(scope, domain, subject, f"offline-{now:%Y%m%dt%H%M%Sz}-{n}", d)
            for n, d in enumerate(self.datasets)
        ]

    async def _run_dataset(
        self, scope: IdentityScope, domain: str, subject: str, run_id: str, dataset: DatasetVersion
    ) -> PipelineSummary:
        judges: dict[Dimension, JudgeConfig] = {
            d: self.judge_config for d in dataset.dimensions if d in self.rubric.dimensions
        }
        sources: list[HitlLabelSource] = []

        async def labels_for(outcomes: Sequence[ItemOutcome]) -> LabelSet | None:
            source = await HitlLabelSource(
                scope=scope, outcomes=outcomes, rubric=self.rubric, hitl=self.hitl
            ).load()
            sources.append(source)
            return ingest_labels(source) if source.labels() else None

        summary = await run_evaluation_pipeline(
            registry=self.registry,
            judge=self.judge,
            matrix=load_matrix(),
            store=self.store,
            ledger=self._ledger(),
            clock=self.clock,
            offline=OfflineStage(
                dataset=dataset,
                config=OfflineRunConfig(
                    run_id=run_id,
                    cloud=self.cloud,  # type: ignore[arg-type]
                    rubric=self.rubric,
                    judges=judges,
                    customer_id=self.customer_id,
                    domain_id=domain,
                    subject_id=subject,
                ),
            ),
            labels_for=labels_for,
            calibration=CalibrationSettings(seed=self.settings.seed),
        )
        sample = await open_calibration_sample(
            scope=scope,
            outcomes=summary.offline.outcomes,
            rubric=self.rubric,
            hitl=self.hitl,
            clock=self.clock,
            config=SampleConfig(
                seed=self.settings.seed,
                max_per_call=self.settings.calibration_sample_cap,
                per_stratum=self.settings.calibration_sample_cap,
            ),
        )
        logger.info(
            "offline evaluation finished",
            extra={
                "event": "worker.evaluation_offline",
                "dataset": dataset.dataset_id,
                "status": summary.offline.status,
                "results_stored": summary.results_stored,
                "calibrations_stored": summary.calibrations_stored,
                "uncalibrated_judges": len(summary.uncalibrated_judges),
                "labels": len(sources[0].labels()) if sources else 0,
                "labels_unmatched": sources[0].unmatched if sources else 0,
                "sample_eligible": sample.eligible,
                "sample_opened": len(sample.opened),
                "sample_already_open": sample.already_open,
            },
        )
        return summary


async def build_evaluation(cfg: RuntimeConfig, lifetime: ClientLifetime) -> RoleRunnable:
    evaluation = EvalSettings()
    if evaluation.data_dir is None:
        raise RoleConfigError("evaluation_data_dir_missing")
    directory = evaluation.data_dir
    registry, rubric, judge_config = _evaluation_registry(directory, evaluation)
    judge = _evaluation_judge(
        cfg, evaluation, directory, _LazyCredential(cfg.settings, lifetime).get
    )
    pilot = _pilot_datasets(registry, evaluation)
    customer = cfg.customer_id
    cosmos = await _cosmos(cfg, lifetime)
    results = CosmosEvaluationStore.from_client(cosmos, database=cfg.store.database)
    source = ArchiveRecordSource(ArchiveReader(_archive_container(cfg, lifetime)), customer)
    matrix = load_matrix()
    cloud = cfg.cloud

    async def online_job() -> None:
        # A fresh ledger per run: the run budget is the bound; the domain budget is per process.
        ledger = BudgetLedger(
            run_limits=BudgetLimits(
                tokens=evaluation.run_token_budget, cost=Decimal(evaluation.run_cost_budget)
            ),
            domain_limits=BudgetLimits(
                tokens=evaluation.domain_token_budget, cost=Decimal(evaluation.domain_cost_budget)
            ),
        )
        service = EvaluationService(judge=judge, matrix=matrix, registry=registry, ledger=ledger)
        now = datetime.now(UTC)
        report = await service.run_online(
            source,
            OnlineRunConfig(
                run_id=f"online-{now:%Y%m%dt%H%M%Sz}",
                cloud=cloud,  # type: ignore[arg-type]
                rubric=rubric,
                judges=dict.fromkeys(rubric.dimensions, judge_config),
                frame_dataset_id=evaluation.frame_dataset_id,
                frame_dataset_version=evaluation.frame_dataset_version,
                rate=evaluation.rate,
                seed=evaluation.seed,
            ),
        )
        for result in report.results:
            await results.put_result(result)
        logger.info(
            "online evaluation finished",
            extra={"event": "worker.evaluation", "status": report.status},
        )

    online_tick = PeriodicTick(online_job, evaluation.interval_seconds)
    if not pilot:
        logger.info(
            "offline evaluation stage idles: no pilot datasets configured",
            extra={"event": "worker.evaluation_offline_idle"},
        )
        return _tick_role("evaluation", online_tick, cfg)

    stack = build_policy_stack(
        cfg.settings, cosmos=cosmos, auth=cfg.auth, store=cfg.store, tenant_id=cfg.tenant_id
    )
    identity = build_identity(cfg.settings, stack=stack, worker=cfg.worker, customer_id=customer)
    offline = _OfflineEvaluation(
        registry=registry,
        rubric=rubric,
        judge_config=judge_config,
        judge=judge,
        store=results,
        hitl=_hitl_service(cfg, cosmos, _audit(cfg, cosmos)),
        datasets=tuple(pilot),
        settings=evaluation,
        customer_id=customer,
        cloud=cloud,
    )

    async def offline_job() -> None:
        await offline.run(await identity.scope_provider.get())

    offline_tick = PeriodicTick(offline_job, evaluation.offline_interval_seconds)

    async def tick() -> None:
        # Independent stages: one failing must not starve the other; the first error surfaces.
        failure: Exception | None = None
        for stage in (online_tick, offline_tick):
            try:
                await stage()
            except Exception as exc:
                failure = failure or exc
        if failure is not None:
            raise failure

    return _tick_role("evaluation", tick, cfg)


# --------------------------------------------------------------------------------------------
# gateway_poll (part of ``all``; a no-op until NS_GATEWAY_POLL_* is configured)


class _ClosableHttp:
    """``ClientLifetime.register`` closes with ``close()``; httpx spells it ``aclose()``."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self.client = client

    async def close(self) -> None:
        await self.client.aclose()


async def build_gateway_poll(cfg: RuntimeConfig, lifetime: ClientLifetime) -> RoleRunnable:
    poll = GatewayPollSettings()
    if poll.unconfigured:
        # Part of ``all``: with no gateway polling configured, idle gracefully (one info line).
        logger.info(
            "gateway_poll not configured; role idles",
            extra={"event": "worker.gateway_poll_unconfigured"},
        )

        async def _noop() -> None:
            return None

        return _tick_role("gateway_poll", _noop, cfg)
    if not poll.domains:
        raise RoleConfigError("gateway_poll_domain_ids_missing")
    if poll.api_base_url is None:
        raise RoleConfigError("gateway_poll_api_base_url_missing")
    if poll.producer_secret is None:
        raise RoleConfigError("gateway_poll_producer_secret_missing")
    customer = cfg.customer_id
    cosmos = await _cosmos(cfg, lifetime)
    if cfg.settings.env == "local":
        await create_gateway_container(_database(cfg, cosmos))
    http = lifetime.register(_ClosableHttp(httpx.AsyncClient(timeout=httpx.Timeout(30.0))))
    metrics_app_id = poll.metrics_app_id
    if metrics_app_id is not None and cfg.cloud == "government":
        # No App Insights Government host is verified, so the metrics poll stays commercial-only.
        logger.warning(
            "gateway_poll metrics poll skipped: unsupported in Government",
            extra={"event": "worker.gateway_poll_metrics_government_skipped"},
        )
        metrics_app_id = None
    poller = GatewayPoller(
        metrics_app_id=metrics_app_id,
        store=CosmosGatewayStore.from_client(cosmos, database=cfg.store.database),
        ingest=IngestClient(
            http.client,
            base_url=poll.api_base_url,
            producer_id=poll.producer_id,
            secret=poll.producer_secret.get_secret_value(),
        ),
        settings=poll,
        customer_id=customer,
        domain_ids=poll.domains,
        cloud=cfg.cloud,
        connector_factory=default_connector_factory(poll.allow_unverified_government),
    )
    return _tick_role("gateway_poll", PeriodicTick(poller.tick, poll.interval_seconds), cfg)


# --------------------------------------------------------------------------------------------
# write targets (PRP-35 item 4; shared with the API composition, which imports these names)
#
# A connector reaches a WriteTargetRegistry only when its own ENABLED flag is set, its target
# reference is complete and valid, and its factory returned the WRITE connector. Advisory
# results (Government, a permission shortfall, manage disabled) are skipped with a logged reason
# code and never registered; the registry's own refusal rules (``_check_capable``) still run on
# everything that is registered. One connector per manifest name: a second connector under a
# name already held is skipped (first wins, logged ``write_target_duplicate``), so exactly one
# Foundry account and one APIM gateway can be managed per process.

#: Manifest names a composed registry may hold (``foundry-model-swap``, ``apim-gateway``).
SUPPORTED_WRITE_CONNECTORS: Final = frozenset(ACTION_CONNECTORS.values())
_ARM_TIMEOUT: Final = httpx.Timeout(30.0)
_GATEWAY_ID: Final = re.compile(GATEWAY_ID_PATTERN)


@dataclass(frozen=True, slots=True)
class WriteTargetSources:
    """Where the APIM connector's registration and durable apply records come from."""

    gateway_store: GatewayStore | None = None
    records_for: Callable[[GatewayRegistration], ApplyRecords] | None = None
    deploy: DeploySources | None = None


@dataclass(frozen=True, slots=True)
class WriteTargetSeams:
    """Injected collaborators (tests). Production passes none: every one is built here."""

    credential: AsyncTokenCredential | None = None
    foundry_http: httpx.AsyncClient | None = None
    apim_arm: GatewayArm | None = None
    apim_records: ApplyRecords | None = None


class DeployWriteSettings(BaseSettings):
    """``NS_DEPLOY_APPLY_ENABLED`` (PRP-08 item 14): opt-in for the deploy write connector.

    OFF by default. Even when set, the connector is registered only when its collaborators
    (:class:`DeploySources`) are supplied; there is no secret in this setting.
    """

    model_config = SettingsConfigDict(env_prefix="NS_DEPLOY_APPLY_", frozen=True, extra="ignore")

    enabled: bool = False


@dataclass(frozen=True, slots=True)
class DeploySources:
    """Collaborators of the deploy connector. ``approvals`` must be readable by the process that
    executes (a per-process in-memory store is only valid where API and executor share it);
    ``register`` is wrapped to the deployment's customer here, never used unscoped."""

    approvals: PlanApprovals | None = None
    register: RegisterStore | None = None
    inventory: LiveInventory | None = None


def load_deploy_write_settings() -> DeployWriteSettings:
    """``NS_DEPLOY_APPLY_*``; a malformed value raises ``ValueError``."""
    try:
        return DeployWriteSettings()
    except ValidationError:
        raise ValueError("deploy write settings are invalid") from None


def load_write_target_settings() -> tuple[FoundryWriteSettings, ApimWriteSettings]:
    """``NS_FOUNDRY_*`` and ``NS_APIM_*``; a malformed value raises ``ValueError``."""
    try:
        return FoundryWriteSettings(), ApimWriteSettings()
    except ValidationError:
        raise ValueError("write target settings are invalid") from None


def _skipped(target: str, reason: str, detail: str | None = None) -> None:
    # Reason codes and fixed connector texts only; never a setting value or an ARM response.
    extra: dict[str, Any] = {"event": "write_target.skipped", "target": target, "reason": reason}
    if detail:
        extra["detail"] = detail
    logger.warning("write target not registered: %s (%s)", target, reason, extra=extra)


def _register(registry: WriteTargetRegistry, target: str, connector: object) -> bool:
    if getattr(connector, "advisory", False):
        _skipped(target, "connector_advisory", str(getattr(connector, "reason", "")) or None)
        return False
    manifest = getattr(connector, "manifest", None)
    name = getattr(manifest, "name", None)
    if name not in SUPPORTED_WRITE_CONNECTORS:
        _skipped(target, "write_target_unsupported")
        return False
    if name in registry.names():
        _skipped(target, "write_target_duplicate")
        return False
    try:
        registry.register(connector)
    except CapabilityUnavailableError as exc:
        _skipped(target, str(exc.reason or "write_target_refused"))
        return False
    logger.info(
        "write target registered: %s",
        name,
        extra={"event": "write_target.registered", "target": target, "connector": name},
    )
    return True


class _LazyCredential:
    """One ``DefaultAzureCredential`` per composition, created on first use and closed with the
    lifetime (the ``_archive_container`` pattern); never created when nothing is enabled."""

    def __init__(self, settings: Settings, lifetime: ClientLifetime) -> None:
        self._settings = settings
        self._lifetime = lifetime
        self._value: AsyncTokenCredential | None = None

    def get(self) -> AsyncTokenCredential:
        if self._value is None:
            self._value = self._lifetime.register(
                DefaultAzureCredential(authority=self._settings.cloud_profile.login_host)
            )
        return self._value


async def _foundry_target(
    foundry: FoundryWriteSettings,
    settings: Settings,
    lifetime: ClientLifetime,
    seams: WriteTargetSeams,
    credential: Callable[[], AsyncTokenCredential],
) -> object | None:
    if not foundry.enabled:
        return None
    try:
        # The account lives in the DEPLOYMENT's cloud; Government yields the advisory connector.
        account = foundry.account_ref(settings.cloud_profile.cloud)
    except ValueError:
        _skipped("foundry", "foundry_config_invalid")
        return None
    if account is None:
        _skipped("foundry", "foundry_config_incomplete")
        return None
    http = seams.foundry_http
    if http is None:
        http = lifetime.register(_ClosableHttp(httpx.AsyncClient(timeout=_ARM_TIMEOUT))).client
    # Reads permissions only (Permissions - List For Resource); write access unproven -> advisory.
    return await create_swap_connector(account, seams.credential or credential(), client=http)


async def _apim_target(
    apim: ApimWriteSettings,
    settings: Settings,
    customer_id: str | None,
    lifetime: ClientLifetime,
    sources: WriteTargetSources,
    seams: WriteTargetSeams,
    credential: Callable[[], AsyncTokenCredential],
) -> object | None:
    if not apim.enabled:
        return None
    if apim.gateway_id is None or apim.domain_id is None:
        _skipped("apim", "apim_config_incomplete")
        return None
    if not _GATEWAY_ID.fullmatch(apim.gateway_id):
        _skipped("apim", "apim_config_invalid")
        return None
    if customer_id is None:
        _skipped("apim", "customer_id_missing")
        return None
    store = sources.gateway_store
    if store is None:
        _skipped("apim", "gateway_store_unconfigured")
        return None
    registration = await store.get(customer_id, apim.domain_id, apim.gateway_id)
    if registration is None:
        _skipped("apim", "gateway_not_registered")
        return None
    if registration.cloud != settings.cloud_profile.cloud.value:
        # Never manage a gateway in another cloud than the deployment's (no bridging).
        _skipped("apim", "gateway_cloud_mismatch")
        return None
    records = seams.apim_records
    if records is None and sources.records_for is not None:
        records = sources.records_for(registration)
    if records is None:
        _skipped("apim", "apim_records_unconfigured")
        return None
    if seams.apim_arm is not None:
        return build_apim_gateway_connector(
            registration, seams.apim_arm, store=store, records=records
        )
    profile = settings.cloud_profile
    http = lifetime.register(_ClosableHttp(arm_client(profile, credential())))
    return build_http_apim_gateway_connector(
        registration, http.client, profile=profile, store=store, records=records
    )


def register_deploy_target(
    registry: WriteTargetRegistry,
    *,
    settings: Settings,
    customer_id: str | None,
    deploy: DeployWriteSettings,
    sources: DeploySources | None,
) -> bool:
    """Register the deploy connector when opted in and fully wired; True when registered.

    Fail closed: disabled is silent; enabled without a customer or without approvals/register
    collaborators is skipped with a logged reason (the deploy intents stay advisory and nothing
    acts). The register is wrapped to ``customer_id`` so the connector can neither read nor write
    another customer's rows. No Fabric/ARM provisioner is supplied here, so an apply of a
    resource that needs one stays ``capability_unavailable``; uninstall is dry-run only.
    """
    if not deploy.enabled:
        return False
    if customer_id is None:
        _skipped("deploy", "customer_id_missing")
        return False
    if sources is None or sources.approvals is None or sources.register is None:
        _skipped("deploy", "deploy_sources_unconfigured")
        return False
    connector = DeployConnector(
        cloud=settings.cloud_profile.cloud,
        approvals=sources.approvals,
        register=CustomerScopedRegister(sources.register, customer_id),
        inventory=sources.inventory,
    )
    return _register(registry, "deploy", connector)


async def register_write_targets(
    registry: WriteTargetRegistry,
    *,
    settings: Settings,
    customer_id: str | None,
    lifetime: ClientLifetime,
    foundry: FoundryWriteSettings,
    apim: ApimWriteSettings,
    sources: WriteTargetSources | None = None,
    seams: WriteTargetSeams | None = None,
    deploy: DeployWriteSettings | None = None,
) -> tuple[str, ...]:
    """Register the configured write connectors into ``registry``; returns its names.

    Foundry first, then APIM, then deploy (deterministic; ``deploy`` None = off). Disabled
    targets are silent; enabled ones that cannot be registered are skipped with a logged reason.
    Infrastructure errors from a factory (ARM or the gateway registry unreachable) propagate:
    the worker supervisor retries the role, and the API startup hook logs them and leaves the
    registry without that target.
    """
    seams = seams or WriteTargetSeams()
    sources = sources or WriteTargetSources()
    lazy = _LazyCredential(settings, lifetime)
    connector = await _foundry_target(foundry, settings, lifetime, seams, lazy.get)
    if connector is not None:
        _register(registry, "foundry", connector)
    connector = await _apim_target(apim, settings, customer_id, lifetime, sources, seams, lazy.get)
    if connector is not None:
        _register(registry, "apim", connector)
    if deploy is not None:
        register_deploy_target(
            registry,
            settings=settings,
            customer_id=customer_id,
            deploy=deploy,
            sources=sources.deploy,
        )
    return registry.names()


# --------------------------------------------------------------------------------------------

BUILDERS: Final[Mapping[str, RoleBuilder]] = {
    "ingestion": build_ingestion,
    "projections": build_projections,
    "aggregates": build_aggregates,
    "actions": build_actions,
    "hitl_timers": build_hitl_timers,
    "lifecycle": build_lifecycle,
    "recommendations": build_recommendations,
    "evaluation": build_evaluation,
    "gateway_poll": build_gateway_poll,
}


def role_factories(
    cfg: RuntimeConfig,
    roles: tuple[str, ...],
    builders: Mapping[str, RoleBuilder] = BUILDERS,
) -> dict[str, RoleFactory]:
    """One supervisor factory per role, bound to ``cfg``."""
    return {name: partial(builders[name], cfg) for name in roles}
