"""Foundry discovery connector: read-only, advisory, bounded.

Lists agents and model deployments of one Foundry project and always attaches the per-cloud
capability matrix, so an absent capability (Government: hosted agents, web search, Bing
grounding, Fabric tool, agent-to-agent) is reported ``unavailable`` with a reason rather than as
an empty result. A source list is ``None`` (unknown) when the call failed; it is never ``[]``
for a failure. Each list is capped at ``max_items``; hitting the cap sets ``truncated`` and
partial coverage, and the connector never loops past it.

Documentation (observed 2026-10-17): https://learn.microsoft.com/azure/foundry/agents/overview
and https://learn.microsoft.com/azure/foundry/how-to/develop/sdk-overview. Government API
availability is documented, not live-tested here (G04 stays OPEN).
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Mapping
from datetime import datetime
from typing import Any

from neurosphere_connector import BaseConnector, build_manifest
from neurosphere_connector.health import Clock, CoverageReport, FreshnessReport, utc_now
from neurosphere_contracts.connectors.v1.connector_manifest import ConnectorManifest, Granularity
from neurosphere_core.cloud.profile import CloudName
from neurosphere_core.errors import NeuroSphereError
from pydantic import BaseModel, ConfigDict, Field

from neurosphere_connector_foundry.capabilities import CapabilityReport, capability_reports
from neurosphere_connector_foundry.reader import FoundryProjectReader

__all__ = [
    "DiscoveredAgent",
    "DiscoveredDeployment",
    "DiscoveryResult",
    "FoundryDiscoveryConnector",
]

DOCUMENTATION_URL = "https://learn.microsoft.com/azure/foundry/agents/overview"
DEFAULT_MAX_ITEMS = 500


class DiscoveredAgent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str | None = None
    name: str | None = None
    versions: dict[str, Any] | None = None


class DiscoveredDeployment(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    name: str | None = None
    type: str | None = None
    model_name: str | None = None
    model_version: str | None = None
    model_publisher: str | None = None
    sku: dict[str, Any] | None = None
    capabilities: dict[str, str] | None = None
    connection_name: str | None = None


class DiscoveryResult(BaseModel):
    """One discovery pass. ``agents``/``deployments`` None = unknown (call failed)."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    cloud: CloudName
    project_endpoint: str
    observed_at: datetime
    advisory: bool = True
    agents: list[DiscoveredAgent] | None = None
    deployments: list[DiscoveredDeployment] | None = None
    agents_truncated: bool = False
    deployments_truncated: bool = False
    failed_sources: dict[str, str] = Field(default_factory=dict)
    capabilities: list[CapabilityReport]


def _opt_str(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _opt_dict(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, Mapping):
        return {str(k): v for k, v in value.items()}  # pyright: ignore[reportUnknownVariableType]
    return None


def _agent(raw: Mapping[str, Any]) -> DiscoveredAgent:
    return DiscoveredAgent(
        id=_opt_str(raw.get("id")),
        name=_opt_str(raw.get("name")),
        versions=_opt_dict(raw.get("versions")),
    )


def _deployment(raw: Mapping[str, Any]) -> DiscoveredDeployment:
    caps = _opt_dict(raw.get("capabilities"))
    return DiscoveredDeployment(
        name=_opt_str(raw.get("name")),
        type=_opt_str(raw.get("type")),
        model_name=_opt_str(raw.get("model_name")),
        model_version=_opt_str(raw.get("model_version")),
        model_publisher=_opt_str(raw.get("model_publisher")),
        sku=_opt_dict(raw.get("sku")),
        capabilities={k: str(v) for k, v in caps.items()} if caps is not None else None,
        connection_name=_opt_str(raw.get("connection_name")),
    )


async def _bounded[T](
    source: AsyncIterator[Mapping[str, Any]], limit: int, build: Callable[[Mapping[str, Any]], T]
) -> tuple[list[T], bool]:
    """Take at most ``limit`` items; ``truncated`` is True only if at least one more existed."""
    out: list[T] = []
    async for raw in source:
        if len(out) >= limit:
            return out, True
        out.append(build(raw))
    return out, False


class FoundryDiscoveryConnector(BaseConnector):
    """Discovery for one project. The reader carries the credential; this class holds none."""

    def __init__(
        self,
        *,
        reader: FoundryProjectReader,
        cloud: CloudName,
        project_endpoint: str,
        max_items: int = DEFAULT_MAX_ITEMS,
        clock: Clock = utc_now,
    ) -> None:
        super().__init__(clock=clock)
        if max_items < 1:
            raise ValueError("max_items must be at least 1")
        self._reader = reader
        self._cloud = cloud
        self._endpoint = project_endpoint
        self._max_items = max_items
        self._clock = clock

    @property
    def manifest(self) -> ConnectorManifest:
        return build_manifest(
            name="foundry-discovery",
            version="0.1.0",
            capabilities=["catalog_discovery", "health_reporting"],
            supported_clouds=["commercial", "government"],
            granularity=Granularity(time_grain="unknown", subject_level="agent"),
            documentation_url=DOCUMENTATION_URL,
        )

    async def discover(self) -> DiscoveryResult:
        """One bounded discovery pass; raises only if every source failed."""
        return await self.guarded_call(
            self._discover,
            freshness=lambda r: FreshnessReport(lag_ms=None, observed_at=r.observed_at),
            coverage=lambda r: CoverageReport(
                expected_sources=2,
                answered_sources=2 - len(r.failed_sources),
                partial=bool(r.failed_sources or r.agents_truncated or r.deployments_truncated),
            ),
        )

    async def _discover(self) -> DiscoveryResult:
        failed: dict[str, str] = {}
        agents: list[DiscoveredAgent] | None = None
        deployments: list[DiscoveredDeployment] | None = None
        agents_cut = deployments_cut = False
        last_error: NeuroSphereError | None = None
        try:
            agents, agents_cut = await _bounded(
                self._reader.list_agents(page_size=min(self._max_items, 50)),
                self._max_items,
                _agent,
            )
        except NeuroSphereError as exc:
            failed["agents"] = exc.code
            last_error = exc
        try:
            deployments, deployments_cut = await _bounded(
                self._reader.list_deployments(), self._max_items, _deployment
            )
        except NeuroSphereError as exc:
            failed["deployments"] = exc.code
            last_error = exc
        if len(failed) == 2 and last_error is not None:
            raise last_error
        return DiscoveryResult(
            cloud=self._cloud,
            project_endpoint=self._endpoint,
            observed_at=self._clock(),
            agents=agents,
            deployments=deployments,
            agents_truncated=agents_cut,
            deployments_truncated=deployments_cut,
            failed_sources=failed,
            capabilities=capability_reports(self._cloud),
        )

    async def close(self) -> None:
        await self._reader.close()
        await super().close()
