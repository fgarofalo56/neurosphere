"""The ``detections`` worker role (PRP-61 item 4).

Read-only: one :class:`PeriodicTick` evaluates the three rules and ``put``s each finding as a
recommendation. Unconfigured (``NS_WORKER_DETECT_ENABLED`` unset) it idles with one info log, so
``NS_WORKER_ROLES=all`` stays safe. Bad configuration fails this role with a machine reason, not
the process. Logs carry counts and reason codes only.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import httpx
from neurosphere_connector_foundry_actions.endpoints import AccountRef
from neurosphere_core.capabilities import load_matrix
from neurosphere_core.capabilities.loader import CapabilityMatrix
from neurosphere_core.cloud.profile import CloudName
from neurosphere_core.detections import (
    ContentFilterRule,
    CoverageStatus,
    DetectionRule,
    GatewayFragmentRule,
    RuleResult,
    ShadowAiRule,
    finding_to_recommendation,
    read_unavailable,
)
from neurosphere_core.recommendations.store import RecommendationStore

from neurosphere_workers.detections.settings import DetectionSettings
from neurosphere_workers.runtime.roles import RoleConfigError

if TYPE_CHECKING:
    from neurosphere_core.clients import ClientLifetime

    from neurosphere_workers.runtime.factories import RuntimeConfig
    from neurosphere_workers.runtime.supervisor import RoleRunnable

__all__ = ["DetectionRunner", "TickSummary", "build_detections"]

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class TickSummary:
    stored: int = 0
    put_failures: int = 0
    rules_failed: int = 0
    coverage: dict[str, str] = field(default_factory=lambda: {})
    findings: dict[str, int] = field(default_factory=lambda: {})


class DetectionRunner:
    """Evaluate rules and store their findings. No I/O of its own beyond the injected seams."""

    def __init__(
        self,
        *,
        rules: Sequence[DetectionRule],
        store: RecommendationStore,
        cloud: str,
        customer_id: str,
        domain_id: str,
        interval_seconds: float,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._rules = tuple(rules)
        self._store = store
        self._cloud = cloud
        self._customer = customer_id
        self._domain = domain_id
        self._interval = interval_seconds
        self._clock = clock

    async def tick(self) -> TickSummary:
        summary = TickSummary()
        now = self._clock()
        for rule in self._rules:
            try:
                result: RuleResult = await rule.evaluate()
            except Exception as exc:  # one failing rule must not starve the others
                summary.rules_failed += 1
                summary.coverage[rule.rule_id] = CoverageStatus.UNKNOWN.value
                logger.warning(
                    "detection rule failed",
                    extra={
                        "event": "worker.detections_rule_failed",
                        "rule": rule.rule_id,
                        "error": type(exc).__name__,
                    },
                )
                continue
            summary.coverage[result.rule_id] = result.coverage.value
            summary.findings[result.rule_id] = len(result.findings)
            for finding in result.findings:
                recommendation = finding_to_recommendation(
                    finding,
                    cloud=self._cloud,
                    customer_id=self._customer,
                    domain_id=self._domain,
                    now=now,
                    interval_seconds=self._interval,
                )
                try:
                    await self._store.put(recommendation)
                except Exception as exc:
                    summary.put_failures += 1
                    logger.warning(
                        "finding not stored",
                        extra={
                            "event": "worker.detections_put_failed",
                            "error": type(exc).__name__,
                        },
                    )
                    continue
                summary.stored += 1
        logger.info(
            "detections tick finished",
            extra={
                "event": "worker.detections_tick",
                "stored": summary.stored,
                "put_failures": summary.put_failures,
                "rules_failed": summary.rules_failed,
                "coverage": dict(summary.coverage),
                "findings": dict(summary.findings),
            },
        )
        return summary


def _account_refs(settings: DetectionSettings, cloud: CloudName) -> tuple[AccountRef, ...]:
    refs: list[AccountRef] = []
    for entry_cloud, raw in settings.account_entries():
        if entry_cloud is not None and entry_cloud != cloud.value:
            raise RoleConfigError("detections_account_cloud_mismatch")
        parts = raw.split("/")
        if len(parts) != 4:
            raise RoleConfigError("detections_foundry_accounts_invalid")
        try:
            refs.append(AccountRef(cloud, parts[0], parts[1], parts[2], parts[3]))
        except ValueError:
            raise RoleConfigError("detections_foundry_accounts_invalid") from None
    return tuple(dict.fromkeys(refs))


def _subscriptions(settings: DetectionSettings, cloud: CloudName) -> tuple[tuple[str, str], ...]:
    from neurosphere_workers.detections.readers.common import GUID

    out: list[tuple[str, str]] = []
    for entry_cloud, sub in settings.subscription_refs():
        if entry_cloud is not None and entry_cloud != cloud.value:
            raise RoleConfigError("detections_subscription_cloud_mismatch")
        if not GUID.fullmatch(sub):
            raise RoleConfigError("detections_subscriptions_invalid")
        out.append((cloud.value, sub))
    return tuple(dict.fromkeys(out))


@dataclass(frozen=True, slots=True)
class ValidatedConfig:
    accounts: tuple[AccountRef, ...]
    subscriptions: tuple[tuple[str, str], ...]
    policies: tuple[str, ...]
    fragments: tuple[str, ...]


def validate(settings: DetectionSettings, cloud: CloudName) -> ValidatedConfig:
    """Raise :class:`RoleConfigError` (machine reason) for anything missing or malformed."""
    if settings.domain_id is None:
        raise RoleConfigError("detections_domain_id_missing")
    if not settings.domain_id_valid:
        raise RoleConfigError("detections_domain_id_invalid")
    accounts = _account_refs(settings, cloud)
    subscriptions = _subscriptions(settings, cloud)
    try:
        policies = settings.acceptable_policies()
    except ValueError:
        raise RoleConfigError("detections_rai_policies_invalid") from None
    try:
        fragments = settings.required_fragments()
    except ValueError:
        raise RoleConfigError("detections_fragments_invalid") from None
    if not accounts and not subscriptions and not fragments:
        raise RoleConfigError("detections_no_rules_configured")
    return ValidatedConfig(accounts, subscriptions, policies, fragments)


async def build_detections(cfg: RuntimeConfig, lifetime: ClientLifetime) -> RoleRunnable:
    # Imported here: ``factories`` imports this module for its BUILDERS table.
    from azure.identity.aio import DefaultAzureCredential
    from neurosphere_core.catalog.repo.cosmos import CosmosCatalogRepository
    from neurosphere_core.gateway import CosmosGatewayStore
    from neurosphere_core.recommendations.cosmos_store import CosmosRecommendationStore

    from neurosphere_workers.detections.readers import (
        ArmDeploymentReader,
        CatalogProjectReader,
        ResourceGraphAccountReader,
        StoreGatewayReader,
    )
    from neurosphere_workers.runtime.factories import (
        _CATALOG_CONTAINER,  # pyright: ignore[reportPrivateUsage]
        _ClosableHttp,  # pyright: ignore[reportPrivateUsage]
        _cosmos,  # pyright: ignore[reportPrivateUsage]
        _database,  # pyright: ignore[reportPrivateUsage]
        _tick_role,  # pyright: ignore[reportPrivateUsage]
    )
    from neurosphere_workers.runtime.identity import build_identity, build_policy_stack

    settings = DetectionSettings()
    if settings.unconfigured:
        logger.info(
            "detections not configured; role idles",
            extra={"event": "worker.detections_unconfigured"},
        )

        async def _noop() -> None:
            return None

        return _tick_role("detections", _noop, cfg)
    cloud = CloudName(cfg.cloud)
    config = validate(settings, cloud)
    domain_id = settings.domain_id
    assert domain_id is not None  # validate() refused a missing domain
    profile = cfg.settings.cloud_profile
    matrix: CapabilityMatrix = load_matrix()
    credential = lifetime.register(DefaultAzureCredential(authority=profile.login_host))
    http = lifetime.register(_ClosableHttp(httpx.AsyncClient(timeout=httpx.Timeout(30.0)))).client
    customer = cfg.customer_id
    cosmos = await _cosmos(cfg, lifetime)
    db = _database(cfg, cosmos)
    stack = build_policy_stack(
        cfg.settings, cosmos=cosmos, auth=cfg.auth, store=cfg.store, tenant_id=cfg.tenant_id
    )
    identity = build_identity(cfg.settings, stack=stack, worker=cfg.worker, customer_id=customer)
    catalog = CatalogProjectReader(
        CosmosCatalogRepository(db.get_container_client(_CATALOG_CONTAINER)),
        identity.scope_provider.get,
        [domain_id],
    )
    known = await _discovery_targets(cfg, lifetime)
    rules: list[DetectionRule] = []
    if config.accounts:
        rules.append(
            ContentFilterRule(
                cloud=cfg.cloud,
                customer_id=customer,
                reader=ArmDeploymentReader(
                    config.accounts,
                    credential,
                    profile,
                    client=http,
                    max_items=settings.max_items,
                    capability_unavailable=read_unavailable(
                        matrix, "foundry", "deployment_read", cfg.cloud
                    ),
                ),
                acceptable_policies=config.policies,
            )
        )
    if config.fragments:
        rules.append(
            GatewayFragmentRule(
                cloud=cfg.cloud,
                customer_id=customer,
                reader=StoreGatewayReader(
                    CosmosGatewayStore.from_client(cosmos, database=cfg.store.database),
                    customer,
                    [domain_id],
                    max_items=settings.max_items,
                ),
                required_fragments=config.fragments,
            )
        )
    if config.subscriptions:
        rules.append(
            ShadowAiRule(
                cloud=cfg.cloud,
                customer_id=customer,
                inventory=ResourceGraphAccountReader(
                    config.subscriptions,
                    credential,
                    profile,
                    client=http,
                    max_items=settings.max_items,
                    capability_unavailable=read_unavailable(
                        matrix, "resource_graph", "base", cfg.cloud
                    ),
                ),
                catalog=catalog,
                configured_accounts=(*(a.account for a in config.accounts), *known),
            )
        )
    runner = DetectionRunner(
        rules=rules,
        store=CosmosRecommendationStore.from_client(cosmos, database=cfg.store.database),
        cloud=cfg.cloud,
        customer_id=customer,
        domain_id=domain_id,
        interval_seconds=settings.interval_seconds,
    )
    from neurosphere_workers.runtime.adapters import PeriodicTick

    async def job() -> None:
        await runner.tick()

    return _tick_role("detections", PeriodicTick(job, settings.interval_seconds), cfg)


async def _discovery_targets(cfg: RuntimeConfig, lifetime: ClientLifetime) -> tuple[str, ...]:
    """Foundry resource names the ``foundry_discovery`` role is configured with (the known set)."""
    from neurosphere_workers.connector_config import (
        ConnectorIdle,
        resolve_foundry_discovery_settings,
    )

    try:
        disc = await resolve_foundry_discovery_settings(cfg, lifetime)
        if isinstance(disc, ConnectorIdle):
            return ()
        return tuple(resource for resource, _project in disc.parse_projects())
    except Exception:  # an unreadable or malformed discovery config adds nothing to the set
        return ()
