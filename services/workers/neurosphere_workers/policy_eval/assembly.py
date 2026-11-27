"""Wiring of the ``policy_eval`` role (PRP-105 item 5).

:func:`build_policy_eval` is the ``BUILDERS["policy_eval"]`` entry. It builds, from the public
client factories only (``runtime.factories`` imports this module for its ``BUILDERS`` table, so
importing its private ``_cosmos``/``_audit``/``_hitl_service`` helpers here would be circular):

* the Cosmos client (``create_cosmos_client``; the local emulator gets its containers through
  ``ensure_local_containers``, which declares the PRP-102 policy containers);
* the audit repository (``CosmosAuditStore.from_client`` on ``audit`` + ``audit_tail``);
* ``HitlService`` over ``CosmosHitlStore``/``CosmosDecisionStore`` with the stored review policy.
  The role only READS review items (clarification 8: the exception decision is read back each
  tick); its reviewer authorizer refuses every reviewer, so it can never decide anything;
* the catalog repository (search write-through when configured, for the projected ``Policy``
  entity), the aggregates store as ``SubjectMetricsReader`` and the PRP-73 ``AccessEngine`` over
  the same repository (its graph is ``RepositoryGraphQuery``; access questions use only the
  bounded impact-path walk, never search, so an empty fixture index is the search seam);
* the worker's OWN derived scope (``build_policy_stack`` + ``build_identity``, the same
  workload ``ScopeProvider`` the publication recorder, projections and detections use). It is
  never widened: the run evaluates only the domains that scope covers and lists the rest as
  skipped. A missing tenant or worker object id refuses the role (``RoleConfigError``);
* the policy stores on ``policy_definitions``/``policy_violations``/``policy_exceptions`` and the
  enforcement bindings over ``admin_config``;
* the rule registry through :func:`build_rule_registry` (the seven builtin kinds, then
  ``RuleEvaluatorRegistry.discover`` over the plugin package), so the worker sees exactly the
  kinds the API's ``rule_kind_unavailable`` check sees.

Binding points (each has ONE owner; nobody else edits them):

* :func:`violation_event_sink` - PRP-107 item 6 binds the notification publisher here;
* :func:`interaction_finding_reader` - PRP-104 item 8 binds the interaction-finding reader here
  (until then ``content_rule`` is reported ``evaluator_unavailable``/``finding_reader_unbound``).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Final

from neurosphere_core.admin import CosmosAdminConfigRepository
from neurosphere_core.aggregates.cosmos import CosmosAggregateStore
from neurosphere_core.aggregates.subject import SubjectMetricsReader
from neurosphere_core.audit.cosmos_store import CosmosAuditStore
from neurosphere_core.audit.repository import AuditRepository
from neurosphere_core.auth.scope.permissions import Permission
from neurosphere_core.catalog.graph import RepositoryGraphQuery
from neurosphere_core.catalog.graph.access import AccessEngine
from neurosphere_core.catalog.protocol import CatalogRepository
from neurosphere_core.catalog.repo.cosmos import CosmosCatalogRepository
from neurosphere_core.clients import ClientLifetime, create_cosmos_client
from neurosphere_core.governance.policy import (
    BindingStore,
    CosmosBindingStore,
    CosmosEvaluationStatusStore,
    CosmosExceptionStore,
    CosmosPolicyDefinitionStore,
    CosmosViolationStore,
    EvaluationStatusStore,
    ExceptionReconciler,
    ExceptionStore,
    NoopViolationEventSink,
    PolicyDefinitionStore,
    PolicyEvaluator,
    PolicyLifecycle,
    ViolationEventSink,
    ViolationStore,
)
from neurosphere_core.governance.policy.rules import (
    InteractionFindingReader,
    RuleBuildContext,
    RuleEvaluatorRegistry,
    ScopeProvider,
    build_rule_registry,
)
from neurosphere_core.hitl import HitlService
from neurosphere_core.hitl.decisions import DecisionLog
from neurosphere_core.hitl_cosmos.store import CosmosDecisionStore, CosmosHitlStore
from neurosphere_core.notifications.violations import ViolationNotificationSink
from neurosphere_core.search.fixture import FixtureSearchIndex
from neurosphere_core.stores import ensure_local_containers

from neurosphere_workers.admin_platform import load_review_policies
from neurosphere_workers.notifications.wiring import build_publisher, notifications_store_configured
from neurosphere_workers.policy_eval.settings import PolicyEvalSettings, load_policy_eval_settings
from neurosphere_workers.policy_eval.worker import ROLE_NAME, DueFirstPolicies, PolicyEvalWorker
from neurosphere_workers.runtime.adapters import TickWorker, WorkerRole
from neurosphere_workers.runtime.identity import build_identity, build_policy_stack
from neurosphere_workers.runtime.search_wiring import wrap_catalog_for_search

if TYPE_CHECKING:
    from azure.cosmos.aio import CosmosClient

    from neurosphere_workers.runtime.factories import RuntimeConfig
    from neurosphere_workers.runtime.supervisor import RoleRunnable

__all__ = [
    "PolicyEvalParts",
    "PolicyEvalStores",
    "assemble_policy_eval",
    "build_policy_eval",
    "interaction_finding_reader",
    "violation_event_sink",
]

AUDIT_CONTAINER: Final = "audit"
AUDIT_TAIL_CONTAINER: Final = "audit_tail"
CATALOG_CONTAINER: Final = "catalog"
AGGREGATES_CONTAINER: Final = "aggregates"


def _utc_now() -> datetime:
    return datetime.now(UTC)


# --------------------------------------------------------------------------------------------
# binding points (one owner each)


def violation_event_sink(cfg: RuntimeConfig, lifetime: ClientLifetime) -> ViolationEventSink:
    """Where violation and exception events go.

    BINDING POINT owned by PRP-107 item 6: the notification sink (ids only, event classes
    ``policy_violation_opened``, ``policy_violation_resolved`` and ``policy_exception_decided``)
    when the notifications store is configured, else the no-op sink. Nobody else binds it.
    """
    if not notifications_store_configured(cfg):
        return NoopViolationEventSink()
    client = create_cosmos_client(cfg.settings, lifetime=lifetime, account=cfg.store.cosmos_account)
    publisher = build_publisher(cfg, client)
    return (
        ViolationNotificationSink(publisher) if publisher is not None else NoopViolationEventSink()
    )


def interaction_finding_reader(
    cfg: RuntimeConfig, lifetime: ClientLifetime
) -> InteractionFindingReader | None:
    """The interaction-finding reader for ``content_rule``: unbound (``None``) in this PRP.

    BINDING POINT owned by PRP-104 item 8, which returns its ``DetectionFinding`` metadata reader
    here (counts and category names, never an interaction body). While it returns ``None`` the
    registry reports ``content_rule`` as ``evaluator_unavailable`` (``finding_reader_unbound``).
    Nobody else binds it. The API builder has the matching function in
    ``runtime/builders/governance.py``.
    """
    return None


# --------------------------------------------------------------------------------------------
# assembly


class _NoReviewerAuthorizer:
    """The role reads review items and never decides one: no principal may review through it."""

    async def can_review(
        self, principal_id: str, customer_id: str, domain_id: str, permission: Permission
    ) -> bool:
        return False


@dataclass(frozen=True, slots=True)
class PolicyEvalStores:
    """The five stores the role writes and reads."""

    policies: PolicyDefinitionStore
    statuses: EvaluationStatusStore
    violations: ViolationStore
    exceptions: ExceptionStore
    bindings: BindingStore


@dataclass(frozen=True, slots=True)
class PolicyEvalParts:
    """Everything :func:`assemble_policy_eval` wired (the tick plus what tests inspect)."""

    worker: PolicyEvalWorker
    evaluator: PolicyEvaluator
    registry: RuleEvaluatorRegistry
    lifecycle: PolicyLifecycle
    reconciler: ExceptionReconciler
    policies: DueFirstPolicies
    access: AccessEngine


def assemble_policy_eval(
    *,
    customer_id: str,
    cloud: str,
    settings: PolicyEvalSettings,
    stores: PolicyEvalStores,
    audit: AuditRepository,
    hitl: HitlService,
    catalog: CatalogRepository,
    metrics: SubjectMetricsReader,
    scope_provider: ScopeProvider,
    cosmos_client: object | None,
    events: ViolationEventSink,
    finding_reader: InteractionFindingReader | None,
    access: AccessEngine | None = None,
    clock: Callable[[], datetime] = _utc_now,
    monotonic: Callable[[], float] = time.monotonic,
) -> PolicyEvalParts:
    """Wire the engine and the tick from already-built clients (no I/O happens here)."""
    engine = access or AccessEngine(catalog, RepositoryGraphQuery(catalog, FixtureSearchIndex([])))
    ctx = RuleBuildContext(
        catalog=catalog,
        metrics=metrics,
        access=engine,
        cosmos_client=cosmos_client,
        cloud=cloud,
        scope_provider=scope_provider,
        clock=clock,
    )
    registry = build_rule_registry(ctx, finding_reader=finding_reader)
    lifecycle = PolicyLifecycle(
        stores.policies, stores.bindings, audit, registry, catalog, clock=clock
    )
    reconciler = ExceptionReconciler(
        stores.exceptions, stores.violations, hitl, audit, events=events
    )
    ordered = DueFirstPolicies(stores.policies)
    evaluator = PolicyEvaluator(
        ordered,
        stores.violations,
        stores.statuses,
        registry,
        audit,
        events=events,
        exceptions=reconciler,
        lifecycle=lifecycle,
        clock=clock,
    )
    worker = PolicyEvalWorker(
        evaluator,
        ordered,
        scope_provider,
        customer_id=customer_id,
        interval_seconds=settings.interval_seconds,
        subject_budget=settings.subject_budget,
        time_budget_seconds=settings.time_budget_seconds,
        clock=clock,
        monotonic=monotonic,
    )
    return PolicyEvalParts(
        worker=worker,
        evaluator=evaluator,
        registry=registry,
        lifecycle=lifecycle,
        reconciler=reconciler,
        policies=ordered,
        access=engine,
    )


async def _cosmos_client(cfg: RuntimeConfig, lifetime: ClientLifetime) -> CosmosClient:
    """The role's Cosmos client (the same factory ``runtime.factories`` wraps)."""
    client = create_cosmos_client(cfg.settings, lifetime=lifetime, account=cfg.store.cosmos_account)
    if cfg.settings.env == "local":
        await ensure_local_containers(client, cfg.settings, database=cfg.store.database)
    return client


def _cosmos_stores(cfg: RuntimeConfig, cosmos: Any) -> PolicyEvalStores:
    database = cfg.store.database
    return PolicyEvalStores(
        policies=CosmosPolicyDefinitionStore.from_client(cosmos, database=database),
        statuses=CosmosEvaluationStatusStore.from_client(cosmos, database=database),
        violations=CosmosViolationStore.from_client(cosmos, database=database),
        exceptions=CosmosExceptionStore.from_client(cosmos, database=database),
        bindings=CosmosBindingStore(
            CosmosAdminConfigRepository.from_client(
                cosmos,
                database=database,
                cloud=cfg.cloud,  # type: ignore[arg-type]
            )
        ),
    )


async def build_policy_eval(cfg: RuntimeConfig, lifetime: ClientLifetime) -> RoleRunnable:
    """The ``policy_eval`` role: settings first (unknown or invalid refuses), then the wiring."""
    settings = load_policy_eval_settings()
    customer = cfg.customer_id
    cosmos = await _cosmos_client(cfg, lifetime)
    database = cfg.store.database
    db = cosmos.get_database_client(database)
    audit = AuditRepository(
        CosmosAuditStore.from_client(
            cosmos,
            database=database,
            container=AUDIT_CONTAINER,
            tail_container=AUDIT_TAIL_CONTAINER,
        )
    )
    hitl = HitlService(
        CosmosHitlStore.from_client(cosmos, database=database),
        DecisionLog(audit, CosmosDecisionStore.from_client(cosmos, database=database)),
        audit,
        await load_review_policies(cfg, cosmos),
        _NoReviewerAuthorizer(),
    )
    stack = build_policy_stack(
        cfg.settings, cosmos=cosmos, auth=cfg.auth, store=cfg.store, tenant_id=cfg.tenant_id
    )
    identity = build_identity(cfg.settings, stack=stack, worker=cfg.worker, customer_id=customer)
    catalog = wrap_catalog_for_search(
        cfg.cloud,
        cfg.settings.cloud_profile,
        lifetime,
        CosmosCatalogRepository(db.get_container_client(CATALOG_CONTAINER)),
    )
    parts = assemble_policy_eval(
        customer_id=customer,
        cloud=cfg.cloud,
        settings=settings,
        stores=_cosmos_stores(cfg, cosmos),
        audit=audit,
        hitl=hitl,
        catalog=catalog,
        metrics=CosmosAggregateStore(db.get_container_client(AGGREGATES_CONTAINER)),
        scope_provider=identity.scope_provider,
        cosmos_client=cosmos,
        events=violation_event_sink(cfg, lifetime),
        finding_reader=interaction_finding_reader(cfg, lifetime),
    )
    worker = parts.worker

    async def tick() -> None:
        await worker.tick()

    return WorkerRole(TickWorker(ROLE_NAME, tick), idle_seconds=cfg.worker.poll_seconds)
