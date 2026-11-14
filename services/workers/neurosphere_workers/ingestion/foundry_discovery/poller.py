"""``FoundryDiscoveryPoller``: one tick discovers Foundry agents and deployments into the catalog.

Per configured project the connector lists agents and model deployments. Each becomes a ``draft``
catalog entity marked ``attributes.discovered_from = "foundry"``, created ONLY if absent: an
existing entity (curated, declared or telemetry-discovered) is never read back into an update,
so a re-poll never overwrites a steward's work. A create race is success (same as the telemetry
projection). Canonical ids: ``{cloud}:{customer}:foundry:model_deployment:{deployment}`` (the
scheme PRP-17 swap targets use) and ``{cloud}:{customer}:foundry:agent:{project}.{agent}``.

Capabilities the cloud's matrix lists as unavailable (Government) are logged as ``unavailable``
and kept in ``last_status``; no catalog entity is ever created for a capability.

An upstream failure (429, 5xx, auth) never raises out of :meth:`tick`: it is logged, recorded in
``last_status`` and the next tick retries. A store outage propagates so the supervisor restarts
the role, the same as ``gateway_poll``.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Final, Protocol

from neurosphere_connector_foundry import (
    CapabilityStatus,
    DiscoveredAgent,
    DiscoveredDeployment,
    DiscoveryResult,
)
from neurosphere_contracts.catalog.v1.agent import Agent
from neurosphere_contracts.catalog.v1.model_deployment import ModelDeployment
from neurosphere_core.catalog.protocol import CatalogEntity, CatalogRepository
from neurosphere_core.catalog.rules import format_timestamp
from neurosphere_core.errors import InvalidSchemaError
from pydantic import ValidationError

from neurosphere_workers.projections.catalog.scope import ScopeProvider

__all__ = [
    "DISCOVERED_FROM",
    "DiscoveryPort",
    "FoundryDiscoveryPoller",
    "ProjectTarget",
    "TickStats",
]

logger = logging.getLogger("neurosphere.workers.foundry_discovery")

DISCOVERED_FROM: Final = "foundry"
_ID_SEGMENT: Final = re.compile(r"[a-z0-9._/=-]+")
_TOKEN: Final = re.compile(r"[a-z0-9][a-z0-9._-]*")
_NAME_MAX: Final = 256


class DiscoveryPort(Protocol):
    async def discover(self) -> DiscoveryResult: ...


@dataclass(frozen=True, slots=True)
class ProjectTarget:
    """One configured project and the connector that reads it."""

    project: str
    connector: DiscoveryPort


@dataclass(slots=True)
class TickStats:
    created: int = 0
    existing: int = 0
    skipped_invalid: int = 0
    projects_failed: int = 0
    #: Per project: ``ok`` / ``partial`` / ``failed:<ErrorClass>``.
    status: dict[str, str] = field(default_factory=lambda: dict[str, str]())
    #: Per project: capabilities documented as unavailable in this cloud (never empty-as-none).
    unavailable: dict[str, tuple[str, ...]] = field(
        default_factory=lambda: dict[str, tuple[str, ...]]()
    )


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _segment(value: str | None) -> str | None:
    """A lowercase canonical-id segment, or None when the value cannot form one."""
    if value is None:
        return None
    lowered = value.strip().lower()
    return lowered if _ID_SEGMENT.fullmatch(lowered) else None


def _token(value: str | None) -> str:
    lowered = (value or "").strip().lower()
    return lowered if _TOKEN.fullmatch(lowered) and len(lowered) <= 128 else "unknown"


class FoundryDiscoveryPoller:
    def __init__(
        self,
        *,
        targets: Sequence[ProjectTarget],
        repository: CatalogRepository,
        scope_provider: ScopeProvider,
        customer_id: str,
        domain_id: str,
        cloud: str,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._targets = tuple(targets)
        self._repo = repository
        self._scopes = scope_provider
        self._customer = customer_id
        self._domain = domain_id
        self._cloud = cloud
        self._clock = clock
        self.last_status = TickStats()

    async def tick(self) -> None:
        stats = TickStats()
        scope = await self._scopes.get()
        now_text = format_timestamp(self._clock())
        for target in self._targets:
            await self._one(scope, target, now_text, stats)
        self.last_status = stats
        logger.info(
            "foundry discovery tick",
            extra={
                "event": "worker.foundry_discovery_tick",
                "entities_created": stats.created,
                "entities_existing": stats.existing,
                "skipped_invalid": stats.skipped_invalid,
                "projects_failed": stats.projects_failed,
            },
        )

    async def _one(
        self, scope: Any, target: ProjectTarget, now_text: str, stats: TickStats
    ) -> None:
        try:
            result = await target.connector.discover()
        except Exception as exc:  # upstream 429/5xx/auth must never crash the role
            stats.projects_failed += 1
            stats.status[target.project] = f"failed:{type(exc).__name__}"[:64]
            logger.warning(
                "foundry discovery failed; next tick retries",
                extra={
                    "event": "worker.foundry_discovery_failed",
                    "project": target.project,
                    "error": type(exc).__name__,
                },
            )
            return
        unavailable = tuple(
            c.capability for c in result.capabilities if c.status is CapabilityStatus.UNAVAILABLE
        )
        stats.unavailable[target.project] = unavailable
        partial = bool(
            result.failed_sources or result.agents_truncated or result.deployments_truncated
        )
        stats.status[target.project] = "partial" if partial else "ok"
        logger.info(
            "foundry capabilities",
            extra={
                "event": "worker.foundry_discovery_capabilities",
                "project": target.project,
                "unavailable": list(unavailable),
                "failed_sources": dict(result.failed_sources),
            },
        )
        for agent in result.agents or []:  # None = unknown (call failed): nothing to create
            await self._ensure(scope, self._agent(target.project, agent, now_text), stats)
        for deployment in result.deployments or []:
            await self._ensure(scope, self._deployment(target.project, deployment, now_text), stats)

    def _base(
        self, entity_id: str, entity_type: str, now_text: str, project: str
    ) -> dict[str, Any]:
        return {
            "schema_version": "1.0.0",
            "id": entity_id,
            "entity_type": entity_type,
            "version": 1,
            "etag": "pending",  # the repository assigns the real ETag
            "lifecycle_status": "draft",
            "created_at": now_text,
            "updated_at": now_text,
            "cloud": self._cloud,
            "customer_id": self._customer,
            "domain_id": self._domain,
            "attributes": {"discovered_from": DISCOVERED_FROM, "foundry_project": project[:256]},
        }

    def _agent(self, project: str, raw: DiscoveredAgent, now_text: str) -> CatalogEntity | None:
        label = raw.name or raw.id
        name = _segment(label)
        proj = _segment(project.replace("/", "."))
        if label is None or name is None or proj is None:
            return None
        entity_id = f"{self._cloud}:{self._customer}:foundry:agent:{proj}.{name}"
        doc = self._base(entity_id, "agent", now_text, project)
        doc.update(
            display_name=label[:_NAME_MAX],
            agent_kind="unknown",
            platform="foundry",
            source_id="foundry",
        )
        if raw.id is not None:
            doc["external_agent_id"] = raw.id[:512]
        return _validated(Agent, doc)

    def _deployment(
        self, _project: str, raw: DiscoveredDeployment, now_text: str
    ) -> CatalogEntity | None:
        name = _segment(raw.name)
        if raw.name is None or name is None:
            return None
        entity_id = f"{self._cloud}:{self._customer}:foundry:model_deployment:{name}"
        doc = self._base(entity_id, "model_deployment", now_text, _project)
        sku = raw.sku.get("name") if raw.sku else None
        doc.update(
            provider=_token(raw.model_publisher),
            model_name=(raw.model_name or "unknown")[:_NAME_MAX],
            deployment_name=raw.name[:_NAME_MAX],
        )
        if raw.model_version:
            doc["model_version"] = raw.model_version[:128]
        if isinstance(sku, str) and sku:
            doc["sku"] = sku[:128]
        return _validated(ModelDeployment, doc)

    async def _ensure(self, scope: Any, entity: CatalogEntity | None, stats: TickStats) -> None:
        """Create-if-absent. Never updates; a create race counts as existing."""
        if entity is None:
            stats.skipped_invalid += 1
            return
        entity_id: str = entity.id
        if await self._repo.get_entity(scope, entity_id) is not None:
            stats.existing += 1
            return
        try:
            await self._repo.create_entity(scope, entity)
            stats.created += 1
        except InvalidSchemaError:
            if await self._repo.get_entity(scope, entity_id) is None:
                raise
            stats.existing += 1


def _validated(model: Any, doc: Mapping[str, Any]) -> CatalogEntity | None:
    try:
        return model.model_validate(dict(doc))
    except ValidationError:
        return None
