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
* ``actions``         ``ActionExecutorWorker`` (only intents in ``executing``)
* ``hitl_timers``     ``HitlTimerWorker``
* ``lifecycle``       ``LifecycleWorker``
* ``recommendations`` periodic ``run_pipeline``
* ``evaluation``      periodic online ``EvaluationService`` run
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from functools import partial
from pathlib import Path
from typing import Any, Final

from azure.cosmos import CosmosClient as SyncCosmosClient
from azure.cosmos.aio import CosmosClient, DatabaseProxy
from azure.identity import DefaultAzureCredential as SyncDefaultAzureCredential
from azure.identity.aio import DefaultAzureCredential
from azure.storage.blob.aio import ContainerClient
from neurosphere_connector.write import WriteTargetRegistry
from neurosphere_core.actions import ActionService
from neurosphere_core.actions.audit import AuditRepositoryActionAuditor
from neurosphere_core.actions.cosmos_store import CosmosExecutionControl, CosmosIntentStore
from neurosphere_core.actions.recheck import PolicyPermissionRechecker
from neurosphere_core.aggregates.cosmos import CosmosAggregateStore
from neurosphere_core.audit.cosmos_store import CosmosAuditStore
from neurosphere_core.audit.repository import AuditRepository
from neurosphere_core.capabilities import load_matrix
from neurosphere_core.catalog.repo.cosmos import CosmosCatalogRepository
from neurosphere_core.catalog.review_queue_cosmos import CosmosReviewQueue
from neurosphere_core.clients import (
    ClientLifetime,
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
from neurosphere_core.errors import InvalidSchemaError, ValidationIssue
from neurosphere_core.evaluation.cosmos_store import CosmosEvaluationStore
from neurosphere_core.evaluation.judge import RecordedFixtureJudge
from neurosphere_core.evaluation.registry import (
    DatasetItem,
    DatasetVersion,
    EvaluationRegistry,
    JudgeConfig,
    RubricVersion,
)
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
from neurosphere_core.stores import ensure_local_containers

from neurosphere_workers.actions import ActionExecutor, ActionExecutorWorker, ReviewItemCompletion
from neurosphere_workers.aggregates.handler import AggregateProjection
from neurosphere_workers.aggregates.sources import StoreLedgerSource
from neurosphere_workers.archive.settings import ArchiveSettings
from neurosphere_workers.evaluation.budget import BudgetLedger, BudgetLimits
from neurosphere_workers.evaluation.service import EvaluationService, OnlineRunConfig
from neurosphere_workers.hitl_timers.worker import HitlTimerWorker
from neurosphere_workers.ingestion.consumer import IngestionConsumer
from neurosphere_workers.ingestion.settings import IngestionSettings
from neurosphere_workers.ingestion.wiring import build_pipeline_deps
from neurosphere_workers.lifecycle.worker import LifecycleWorker, RequestedJob
from neurosphere_workers.projections.catalog import CatalogProjection
from neurosphere_workers.projections.outbox import (
    SINK_AGGREGATES,
    SINK_CATALOG,
    CosmosCheckpointStore,
    CosmosOutboxStore,
    OutboxReader,
    SinkHandler,
)
from neurosphere_workers.recommendations.pipeline import run_pipeline
from neurosphere_workers.recommendations.projection.models import CandidatePairConfig
from neurosphere_workers.runtime.adapters import IngestionRole, PeriodicTick, TickWorker, WorkerRole
from neurosphere_workers.runtime.archive_reader import (
    ArchiveReader,
    ArchiveRecordSource,
    ArchiveTraceEventSource,
)
from neurosphere_workers.runtime.identity import build_identity, build_policy_stack
from neurosphere_workers.runtime.price_refresh import PriceTableRefresher
from neurosphere_workers.runtime.roles import RoleConfigError
from neurosphere_workers.runtime.settings import (
    AuthSettings,
    EvalSettings,
    RecommendationSettings,
    StoreSettings,
    WorkerSettings,
)
from neurosphere_workers.runtime.supervisor import RoleFactory, RoleRunnable

__all__ = ["BUILDERS", "RoleBuilder", "RuntimeConfig", "role_factories"]

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
    # No write connector is registered here: connectors are deployment-specific and need an
    # authorized target. An empty registry fails every intent closed with capability_unavailable
    # (no connector call, no pretend change).
    executor = ActionExecutor(
        service,
        WriteTargetRegistry(),
        execution_control=control,
        worker_id=cfg.worker.worker_id or f"{socket.gethostname()}-{os.getpid()}",
        on_finished=ReviewItemCompletion(_hitl_service(cfg, cosmos, audit), auditor=auditor),
    )
    return WorkerRole(ActionExecutorWorker(executor, store), idle_seconds=cfg.worker.poll_seconds)


async def build_hitl_timers(cfg: RuntimeConfig, lifetime: ClientLifetime) -> RoleRunnable:
    cosmos = await _cosmos(cfg, lifetime)
    service = _hitl_service(cfg, cosmos, _audit(cfg, cosmos))
    return WorkerRole(HitlTimerWorker(service), idle_seconds=cfg.worker.poll_seconds)


class _NoRequestedJobs:
    """Requests reach the engine through the API/engine ``submit``; the queue is processed."""

    async def next_jobs(self, checkpoint: str | None, limit: int) -> list[RequestedJob]:
        return []


async def build_lifecycle(cfg: RuntimeConfig, lifetime: ClientLifetime) -> RoleRunnable:
    customer = cfg.customer_id
    cosmos = await _cosmos(cfg, lifetime)
    database = cfg.store.database
    engine = LifecycleEngine(
        # Lifecycle targets (catalog, archive, ledger, conversations) are bound by the
        # deployment that owns those stores; an empty registry fails requests closed.
        targets=TargetRegistry(),
        holds=CosmosHoldRegistry.from_client(cosmos, database=database, customer_id=customer),
        queue=CosmosRequestQueue.from_client(cosmos, database=database, customer_id=customer),
        audit=_audit(cfg, cosmos),
        audit_chain_id=f"lifecycle.{customer}",
        cloud=cfg.cloud,  # type: ignore[arg-type]
        customer_id=customer,
        mappings=CosmosMappingStore.from_client(cosmos, database=database, customer_id=customer),
    )
    return WorkerRole(
        LifecycleWorker(engine, _NoRequestedJobs()), idle_seconds=cfg.worker.poll_seconds
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


async def build_evaluation(cfg: RuntimeConfig, lifetime: ClientLifetime) -> RoleRunnable:
    evaluation = EvalSettings()
    if evaluation.data_dir is None:
        raise RoleConfigError("evaluation_data_dir_missing")
    directory = evaluation.data_dir
    registry, rubric, judge_config = _evaluation_registry(directory, evaluation)
    try:
        judge = RecordedFixtureJudge.from_file(directory / "judge_fixtures.json")
    except (OSError, ValueError):
        raise RoleConfigError("evaluation_fixtures_invalid") from None
    customer = cfg.customer_id
    cosmos = await _cosmos(cfg, lifetime)
    results = CosmosEvaluationStore.from_client(cosmos, database=cfg.store.database)
    source = ArchiveRecordSource(ArchiveReader(_archive_container(cfg, lifetime)), customer)
    matrix = load_matrix()
    cloud = cfg.cloud

    async def job() -> None:
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

    return _tick_role("evaluation", PeriodicTick(job, evaluation.interval_seconds), cfg)


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
}


def role_factories(
    cfg: RuntimeConfig,
    roles: tuple[str, ...],
    builders: Mapping[str, RoleBuilder] = BUILDERS,
) -> dict[str, RoleFactory]:
    """One supervisor factory per role, bound to ``cfg``."""
    return {name: partial(builders[name], cfg) for name in roles}
