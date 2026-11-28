"""Governance policy engine builder (PRP-105 item 6): installs ``app.state.governance_policy``.

Component ``governance_policy`` is OPTIONAL. Rules, in order:

1. ``GovernancePolicySettings`` (``NS_GOVPOLICY_*``) invalid -> ``failed``
   ``govpolicy_settings_invalid`` (a misconfiguration blocks readiness).
2. ``NS_GOVPOLICY_ENABLED=false`` -> ``disabled`` (reason ``setting_off``); every route answers
   503 ``capability_unavailable``. Nothing else is read or built.
3. Startup REFUSALS (``StartupRefusedError``, the app does not start): the in-memory backend
   outside ``NS_ENV=local`` (``govpolicy_memory_not_local``: a production deployment must never
   keep policies in process memory) and a seed file outside ``NS_ENV=local``
   (``govpolicy_seed_not_local``: outside local, nothing but an approved action publishes).
4. Upstream pieces the data builder published (audit repository, HITL service, catalog
   repository) or the Cosmos client missing -> ``disabled`` with the reason code logged and on
   ``app.state.governance_policy_off_reason``.
5. Otherwise the :class:`GovernancePolicyPlane` is installed and the component is ``ok``.

The rule registry is built through :func:`build_rule_registry` (builtins, then
``RuleEvaluatorRegistry.discover`` over the plugin package), exactly as the ``policy_eval`` worker
builds it, so the API's publish dry run refuses (``rule_kind_unavailable``) the same kinds the
worker cannot evaluate. :func:`interaction_finding_reader` is the API binding point of the
``InteractionFindingReader`` port: it returns ``None`` (so ``content_rule`` is
``evaluator_unavailable``) until PRP-104 item 8 binds the reader here. Nobody else binds it.

Local seed (clarification 11): under ``NS_ENV=local`` only, ``NS_GOVPOLICY_LOCAL_SEED_FILE`` names
a JSON file ``{"policies": [{policy_id, domain_id, display_name, severity, mode?, document_url?,
rules}]}`` (at most 50 synthetic policies). It is parsed at build time (``failed``
``govpolicy_seed_invalid`` when malformed) and, in a startup hook, each entry is written as a
draft (audited ``govpolicy.draft_create``) and published through ``PolicyLifecycle.publish``
(audited ``govpolicy.seed``) under a local-only seed scope that covers exactly the seed's domains.
A seed whose content is already published is skipped, so a restart publishes nothing twice.

Settings: ``NS_GOVPOLICY_ENABLED`` (default true), ``NS_GOVPOLICY_BACKEND`` (``cosmos`` default,
``memory`` under ``NS_ENV=local`` only), ``NS_GOVPOLICY_EXCEPTION_MAX_DAYS`` (default 90, 1..365),
``NS_GOVPOLICY_LOCAL_SEED_FILE`` (unset by default).
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, Literal

from neurosphere_contracts.scope.v1.identity_scope import IdentityScope as ContractScope
from neurosphere_core.admin import (
    AdminConfigRepository,
    CosmosAdminConfigRepository,
    InMemoryAdminConfigRepository,
)
from neurosphere_core.aggregates.subject import SubjectLookup, SubjectMetricsReader
from neurosphere_core.audit import AuditRepository
from neurosphere_core.audit.canonical import sha256_digest
from neurosphere_core.auth.scope.hashing import compute_scope_hash
from neurosphere_core.catalog import CatalogRepository, GraphQuery
from neurosphere_core.catalog.graph.access import AccessEngine
from neurosphere_core.catalog.graph.query import RepositoryGraphQuery
from neurosphere_core.errors import CapabilityUnavailableError, ForbiddenError
from neurosphere_core.governance.policy import (
    AuditDecisionRecorder,
    BindingStore,
    CosmosBindingStore,
    CosmosEvaluationStatusStore,
    CosmosExceptionStore,
    CosmosPolicyDefinitionStore,
    CosmosViolationStore,
    EvaluationStatusStore,
    ExceptionRequester,
    ExceptionStore,
    InMemoryDocumentBackend,
    InMemoryEvaluationStatusStore,
    InMemoryExceptionStore,
    InMemoryPolicyDefinitionStore,
    InMemoryViolationStore,
    LifecycleAuditContext,
    PolicyDecider,
    PolicyDefinitionStore,
    PolicyLifecycle,
    StoredPolicy,
    ViolationStore,
    validate_draft,
)
from neurosphere_core.governance.policy.models import PolicyDefinition
from neurosphere_core.governance.policy.readers import InteractionFindingReaderAdapter
from neurosphere_core.governance.policy.rules import (
    InteractionFindingReader,
    RuleBuildContext,
    RuleEvaluatorRegistry,
    build_rule_registry,
)
from neurosphere_core.hitl import HitlService
from neurosphere_core.scope import IdentityScope
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from neurosphere_api.governance.policy.deps import (
    GovernancePolicyPlane,
    configure_governance_policy,
)
from neurosphere_api.governance.policy.models import PolicyCreateBody
from neurosphere_api.governance.policy.service import GovernancePolicyService, principal_id_of
from neurosphere_api.runtime.builders import (
    AGGREGATE_READER,
    AUDIT_REPOSITORY,
    CATALOG_REPOSITORY,
    HITL_SERVICE,
    BuildContext,
    BuilderSpec,
    ComponentUnavailableError,
)
from neurosphere_api.runtime.builders.interactions import interaction_store
from neurosphere_api.runtime.errors import StartupRefusedError

__all__ = [
    "BUILDER",
    "COMPONENTS",
    "MAX_SEED_POLICIES",
    "SEED_NOT_LOCAL",
    "GovPolicyMemoryNotLocalError",
    "GovPolicySeedNotLocalError",
    "GovernancePolicySettings",
    "SeedFile",
    "SeedPolicy",
    "build",
    "interaction_finding_reader",
    "load_seed_file",
    "local_seed_scope",
    "seed_policies",
]

COMPONENTS: Final = ("governance_policy",)
_COMPONENT: Final = "governance_policy"
MAX_SEED_POLICIES: Final = 50
SEED_NOT_LOCAL: Final = "govpolicy_seed_not_local"
MEMORY_NOT_LOCAL: Final = "govpolicy_memory_not_local"
SEED_INVALID: Final = "govpolicy_seed_invalid"
SETTINGS_INVALID: Final = "govpolicy_settings_invalid"
_SEED_POLICY_VERSION: Final = "govpolicy-local-seed"
_SEED_PSEUDONYM: Final = "govpolicy-local-seed"
#: Fixed namespace of the deterministic seed intent ids (never change).
_SEED_NAMESPACE: Final = uuid.UUID("3e8a1f5c-9b2d-4c7e-a6f0-1d4b8c2e7a95")

_log = logging.getLogger("neurosphere_api.runtime")


class GovPolicyMemoryNotLocalError(StartupRefusedError):
    """``NS_GOVPOLICY_BACKEND=memory`` outside ``NS_ENV=local``: startup is refused."""

    def __init__(self) -> None:
        super().__init__(MEMORY_NOT_LOCAL)
        self.reason = MEMORY_NOT_LOCAL


class GovPolicySeedNotLocalError(StartupRefusedError):
    """``NS_GOVPOLICY_LOCAL_SEED_FILE`` outside ``NS_ENV=local``: startup is refused."""

    def __init__(self) -> None:
        super().__init__(SEED_NOT_LOCAL)
        self.reason = SEED_NOT_LOCAL


class GovernancePolicySettings(BaseSettings):
    """``NS_GOVPOLICY_*`` (see the module docstring)."""

    model_config = SettingsConfigDict(
        env_prefix="NS_GOVPOLICY_", frozen=True, extra="forbid", hide_input_in_errors=True
    )

    enabled: bool = True
    backend: Literal["cosmos", "memory"] = "cosmos"
    exception_max_days: int = Field(default=90, ge=1, le=365)
    local_seed_file: Path | None = None

    @field_validator("local_seed_file", mode="before")
    @classmethod
    def _blank_is_unset(cls, value: Any) -> Any:
        if isinstance(value, str) and not value.strip():
            return None
        return value


class SeedPolicy(PolicyCreateBody):
    """One seed entry: a draft body plus the (synthetic) domain it lives in."""

    domain_id: str = Field(min_length=1, max_length=512)


class SeedFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    policies: list[SeedPolicy] = Field(min_length=1, max_length=MAX_SEED_POLICIES)


# --- binding point and small adapters ------------------------------------------------------------


def interaction_finding_reader(ctx: BuildContext) -> InteractionFindingReader | None:
    """The API binding point of the PRP-105 ``InteractionFindingReader`` port (PRP-104 item 8).

    Returns :class:`InteractionFindingReaderAdapter` (finding counts and interaction ids from the
    metadata index; never content, never a decrypt) over the composition's shared interaction
    store from the interactions builder's memoized ``interaction_store`` factory, when that store
    can be built (an ``interaction_capture`` stored setting exists and retention opts in to
    bodies; the same gate as the interaction explorer). Otherwise ``None``: the ``content_rule``
    kind is ``evaluator_unavailable`` and a policy using it is refused at publish dry run
    (``rule_kind_unavailable``). This module is the one API binding owner.
    """
    try:
        store = interaction_store(ctx)
    except ComponentUnavailableError as exc:
        _log.info("content_rule finding reader unbound: %s", exc.reason)
        return None
    except Exception as exc:
        # Optional: an unexpected store error leaves content_rule unavailable, nothing else.
        _log.warning("content_rule finding reader unbound: %s", type(exc).__name__)
        return None
    return InteractionFindingReaderAdapter(store)


class _NoSubjectMetrics:
    """Used when the aggregate reader has no subject metrics: every lookup is empty."""

    async def latest_subject_points(self, *_args: Any, **_kwargs: Any) -> SubjectLookup:
        return SubjectLookup(points={})

    async def newest_subject_points(self, *_args: Any, **_kwargs: Any) -> SubjectLookup:
        return SubjectLookup(points={})


class _NoSearch:
    """Graph search for the access engine when no graph was composed: fails closed."""

    async def search(self, *_args: Any, **_kwargs: Any) -> Any:
        raise CapabilityUnavailableError("search_unavailable", "catalog search is not composed")


class _ApiScopeProvider:
    """The API runs no evaluation of its own: a plugin asking for an API scope is refused."""

    async def get(self) -> IdentityScope:
        raise ForbiddenError(
            "the API evaluates no rule under its own scope", reason="api_scope_unavailable"
        )


def _clock(ctx: BuildContext) -> Callable[[], datetime]:
    """The composition clock (tests pass one through the overrides), else UTC now."""
    source = ctx.overrides.clock
    if source is None:
        return _utc_now

    def now() -> datetime:
        return datetime.fromtimestamp(source(), UTC)

    return now


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _off(ctx: BuildContext, reason: str) -> None:
    configure_governance_policy(ctx.app, None, off_reason=reason)
    level = logging.INFO if reason == "setting_off" else logging.WARNING
    _log.log(level, "component %s disabled: %s", _COMPONENT, reason)
    ctx.disabled(_COMPONENT)


def _fail(ctx: BuildContext, reason: str) -> None:
    configure_governance_policy(ctx.app, None, off_reason=reason)
    ctx.failed(_COMPONENT, reason)


# --- stores --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Stores:
    policies: PolicyDefinitionStore
    violations: ViolationStore
    exceptions: ExceptionStore
    bindings: BindingStore
    statuses: EvaluationStatusStore
    cosmos_client: object | None


def _binding_repository(ctx: BuildContext, fallback: AdminConfigRepository) -> BindingStore:
    override = ctx.overrides.backend("admin_config_repository")
    if override is not None:
        if not isinstance(override, AdminConfigRepository):
            raise ComponentUnavailableError("admin_config_override_invalid")
        return BindingStore(override)
    return BindingStore(fallback)


def _memory_stores(ctx: BuildContext) -> _Stores:
    cloud = ctx.settings.cloud_profile.cloud.value
    definitions = InMemoryDocumentBackend()
    return _Stores(
        policies=InMemoryPolicyDefinitionStore(definitions),
        violations=InMemoryViolationStore(),
        exceptions=InMemoryExceptionStore(),
        bindings=_binding_repository(
            ctx,
            InMemoryAdminConfigRepository(cloud=cloud),  # type: ignore[arg-type]
        ),
        statuses=InMemoryEvaluationStatusStore(definitions),
        cosmos_client=None,
    )


def _cosmos_stores(ctx: BuildContext) -> _Stores:
    client = ctx.cosmos_client()  # ComponentUnavailableError("cosmos_unconfigured")
    database = ctx.store_settings().database
    cloud = ctx.settings.cloud_profile.cloud.value
    admin = CosmosAdminConfigRepository.from_client(
        client,
        database=database,
        cloud=cloud,  # type: ignore[arg-type]
    )
    override = ctx.overrides.backend("admin_config_repository")
    bindings = (
        _binding_repository(ctx, admin) if override is not None else CosmosBindingStore(admin)
    )
    return _Stores(
        policies=CosmosPolicyDefinitionStore.from_client(client, database=database),
        violations=CosmosViolationStore.from_client(client, database=database),
        exceptions=CosmosExceptionStore.from_client(client, database=database),
        bindings=bindings,
        statuses=CosmosEvaluationStatusStore.from_client(client, database=database),
        cosmos_client=client,
    )


# --- the plane -----------------------------------------------------------------------------------


def _registry(
    ctx: BuildContext,
    catalog: CatalogRepository,
    cosmos_client: object | None,
    clock: Callable[[], datetime],
) -> RuleEvaluatorRegistry:
    reader = ctx.maybe_shared(AGGREGATE_READER)
    metrics: SubjectMetricsReader = (
        reader if isinstance(reader, SubjectMetricsReader) else _NoSubjectMetrics()  # type: ignore[assignment]
    )
    graph = getattr(ctx.app.state, "catalog_graph", None)
    if not isinstance(graph, GraphQuery):
        graph = RepositoryGraphQuery(catalog, _NoSearch())  # type: ignore[arg-type]
    build_ctx = RuleBuildContext(
        catalog=catalog,
        metrics=metrics,
        access=AccessEngine(catalog, graph),
        cosmos_client=cosmos_client,
        cloud=ctx.settings.cloud_profile.cloud.value,
        scope_provider=_ApiScopeProvider(),
        clock=clock,
    )
    return build_rule_registry(build_ctx, finding_reader=interaction_finding_reader(ctx))


def _plane(ctx: BuildContext, settings: GovernancePolicySettings) -> GovernancePolicyPlane:
    audit = ctx.maybe_shared(AUDIT_REPOSITORY)
    if not isinstance(audit, AuditRepository):
        raise ComponentUnavailableError("audit_unavailable")
    hitl = ctx.maybe_shared(HITL_SERVICE)
    if not isinstance(hitl, HitlService):
        raise ComponentUnavailableError("hitl_unavailable")
    catalog = ctx.maybe_shared(CATALOG_REPOSITORY)
    if not isinstance(catalog, CatalogRepository):
        raise ComponentUnavailableError("catalog_repository_unavailable")
    stores = _memory_stores(ctx) if settings.backend == "memory" else _cosmos_stores(ctx)
    clock = _clock(ctx)
    registry = _registry(ctx, catalog, stores.cosmos_client, clock)
    lifecycle = PolicyLifecycle(
        stores.policies, stores.bindings, audit, registry, catalog, clock=clock
    )
    decider = PolicyDecider(
        stores.policies,
        stores.bindings,
        stores.exceptions,
        catalog=catalog,
        recorder=AuditDecisionRecorder(audit),
    )
    requester = ExceptionRequester(
        stores.violations,
        stores.exceptions,
        hitl,
        audit,
        max_days=settings.exception_max_days,
        clock=clock,
    )
    return GovernancePolicyPlane(
        policies=stores.policies,
        violations=stores.violations,
        exceptions=stores.exceptions,
        bindings=stores.bindings,
        statuses=stores.statuses,
        lifecycle=lifecycle,
        decider=decider,
        registry=registry,
        exception_requester=requester,
        audit=audit,
        clock=clock,
        backend=settings.backend,
        exception_max_days=settings.exception_max_days,
    )


# --- local seed ----------------------------------------------------------------------------------


def load_seed_file(path: Path) -> SeedFile:
    """Parse the seed file; ``ComponentUnavailableError(govpolicy_seed_invalid)`` when it cannot
    be read or does not have the documented shape (the reason only, never the content)."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return SeedFile.model_validate(raw)
    except (OSError, UnicodeError, ValueError, ValidationError):
        raise ComponentUnavailableError(SEED_INVALID) from None


def local_seed_scope(cloud: str, customer_id: str, domains: Sequence[str]) -> IdentityScope:
    """The ``NS_ENV=local`` seed principal's scope: exactly the seed's domains, nothing else.

    Synthetic and local only (the same shape as the analytics fixture workload scope): a
    service principal with no role and no resource grant. The caller has already refused to
    start outside ``NS_ENV=local``.
    """
    principal_hex = sha256_digest({"seed": _SEED_PSEUDONYM, "customer": customer_id})
    principal_id = f"{cloud}:{customer_id}:entra:principal:p-{principal_hex.split(':', 1)[1]}"
    document: dict[str, Any] = {
        "schema_version": "1.0.0",
        "cloud": cloud,
        "customer_id": customer_id,
        "principal": {
            "principal_id": principal_id,
            "principal_pseudonym": _SEED_PSEUDONYM,
            "principal_kind": "service_principal",
        },
        "roles": [],
        "allowed_domains": sorted(set(domains)),
        "allowed_resources": [],
        "policy_version": _SEED_POLICY_VERSION,
        "derived_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    document["scope_hash"] = compute_scope_hash(document)
    contract = ContractScope.model_validate(document)
    return IdentityScope._from_verified_contract(contract)  # pyright: ignore[reportPrivateUsage]


def _seed_intent_id(customer_id: str, policy_id: str, version: int) -> str:
    """Deterministic id recorded as ``published_intent_id`` of a seeded version (no stored
    intent exists: the seed IS the local-only publish path, audited ``govpolicy.seed``)."""
    return str(uuid.uuid5(_SEED_NAMESPACE, f"govpolicy-seed|{customer_id}|{policy_id}|{version}"))


def _already_published(latest: StoredPolicy, preview: PolicyDefinition, entry: SeedPolicy) -> bool:
    policy = latest.policy
    return (
        policy.status == "published"
        and policy.content_sha256 == preview.content_sha256
        and policy.display_name.root == entry.display_name
        and policy.severity.root == entry.severity
        and (policy.mode.root if policy.mode is not None else "audit") == entry.mode
    )


async def seed_policies(
    plane: GovernancePolicyPlane,
    seed: SeedFile,
    *,
    cloud: str,
    customer_id: str,
    correlation_id: str = "corr-govpolicy-local-seed",
) -> list[str]:
    """Write and publish every seed policy; returns the policy ids published by this call."""
    scope = local_seed_scope(cloud, customer_id, [p.domain_id for p in seed.policies])
    service = GovernancePolicyService(plane)
    now = plane.clock().astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    published: list[str] = []
    for entry in seed.policies:
        latest = await plane.policies.get(customer_id, entry.policy_id)
        preview = validate_draft(
            service.draft_document(
                scope,
                entry.domain_id,
                entry.policy_id,
                entry,
                version=1,
                previous=None,
                created_by=principal_id_of(scope),
                created_at=now,
            )
        )
        if latest is not None and _already_published(latest, preview, entry):
            continue
        if latest is not None and latest.policy.status == "draft":
            stored = await service.replace_draft(
                scope,
                entry.domain_id,
                entry.policy_id,
                entry,
                if_match=latest.etag,
                correlation_id=correlation_id,
            )
        else:
            stored = await service.create_draft(scope, entry.domain_id, entry, correlation_id)
        version = stored.policy.policy_version
        await plane.lifecycle.publish(
            entry.policy_id,
            version,
            expected_etag=stored.etag,
            audit_ctx=LifecycleAuditContext(
                scope=scope,
                correlation_id=correlation_id,
                intent_id=_seed_intent_id(customer_id, entry.policy_id, version),
                channel="worker",
                seed=True,
            ),
        )
        published.append(entry.policy_id)
    return published


# --- build ---------------------------------------------------------------------------------------


def _customer(ctx: BuildContext) -> str:
    try:
        customer = ctx.auth_settings().resolved_customer_id(ctx.settings.env)
    except ComponentUnavailableError:
        customer = None
    if customer is None:
        raise ComponentUnavailableError("customer_unconfigured")
    return customer


def _schedule_seed(
    ctx: BuildContext, plane: GovernancePolicyPlane, seed: SeedFile, customer: str
) -> None:
    cloud = ctx.settings.cloud_profile.cloud.value

    async def run_seed() -> None:
        ids = await seed_policies(plane, seed, cloud=cloud, customer_id=customer)
        _log.info("governance policy local seed published %d policies", len(ids))

    ctx.on_startup(run_seed)


def build(ctx: BuildContext) -> None:
    configure_governance_policy(ctx.app, None, off_reason="not_built")
    try:
        settings = GovernancePolicySettings()
    except ValidationError:
        _fail(ctx, SETTINGS_INVALID)
        return
    if not settings.enabled:
        _off(ctx, "setting_off")
        return
    local = ctx.settings.env == "local"
    if settings.backend == "memory" and not local:
        raise GovPolicyMemoryNotLocalError()
    if settings.local_seed_file is not None and not local:
        raise GovPolicySeedNotLocalError()
    seed: SeedFile | None = None
    if settings.local_seed_file is not None:
        try:
            seed = load_seed_file(settings.local_seed_file)
        except ComponentUnavailableError as exc:
            _fail(ctx, exc.reason)
            return
    try:
        plane = _plane(ctx, settings)
        customer = _customer(ctx) if seed is not None else ""
    except ComponentUnavailableError as exc:
        _off(ctx, exc.reason)
        return
    configure_governance_policy(ctx.app, plane)
    if seed is not None:
        _schedule_seed(ctx, plane, seed, customer)
    ctx.ok(_COMPONENT)


BUILDER: Final = BuilderSpec("governance", COMPONENTS, build)
