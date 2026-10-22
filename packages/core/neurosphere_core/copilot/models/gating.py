"""Adapter availability from the capability matrix: disabled-with-reason, never dropped.

``resolve_adapters`` always returns one :class:`AdapterAvailability` per adapter kind. An
adapter is enabled only when its configuration is present, its endpoint belongs to the
deployment's cloud, and every capability it needs resolves ``supported`` in the matrix for the
deployment's cloud and region (only same-cloud rows are ever consulted, so a Government
deployment cannot be satisfied by a Commercial row).

* ``approved_endpoint`` needs ``foundry.<model_feature>`` (with ``sku``).
* ``foundry_agent`` needs ``foundry.base``, ``foundry.agent_function_calling`` and the model.
* ``fixture`` is synthetic and always enabled.

``create_adapter`` refuses a disabled entry with ``capability_unavailable``.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

import httpx
from azure.core.credentials_async import AsyncTokenCredential
from pydantic import BaseModel, ConfigDict

from neurosphere_core.capabilities import (
    CapabilityMatrix,
    CapabilityResult,
    DeploymentProfile,
    FeatureRequest,
    validate_profile,
)
from neurosphere_core.copilot.models.approved_endpoint import ApprovedEndpointAdapter
from neurosphere_core.copilot.models.endpoints import AdapterConfig, Cloud, endpoint_problem
from neurosphere_core.copilot.models.foundry_agent import FoundryAgentAdapter
from neurosphere_core.copilot.models.protocol import ADAPTER_KINDS, AdapterKind, ModelAdapter
from neurosphere_core.copilot.models.recorded import FixtureAdapter
from neurosphere_core.errors import CapabilityUnavailableError

_FOUNDRY = "foundry"


class AdapterAvailability(BaseModel):
    """Whether one adapter may be used, and why not when it may not."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: AdapterKind
    enabled: bool
    reason_code: str | None = None
    reason: str | None = None
    config: AdapterConfig | None = None
    capabilities: tuple[CapabilityResult, ...] = ()


def _requests(config: AdapterConfig) -> tuple[FeatureRequest, ...]:
    requests: list[FeatureRequest] = []
    if config.kind == "foundry_agent":
        requests.append(FeatureRequest(service=_FOUNDRY, feature="base"))
        requests.append(FeatureRequest(service=_FOUNDRY, feature="agent_function_calling"))
    if config.model_feature:
        requests.append(
            FeatureRequest(service=_FOUNDRY, feature=config.model_feature, sku=config.sku)
        )
    return tuple(requests)


def _disabled(
    kind: AdapterKind,
    code: str,
    reason: str,
    config: AdapterConfig | None = None,
    capabilities: tuple[CapabilityResult, ...] = (),
) -> AdapterAvailability:
    return AdapterAvailability(
        kind=kind,
        enabled=False,
        reason_code=code,
        reason=reason,
        config=config,
        capabilities=capabilities,
    )


def _evaluate(
    config: AdapterConfig,
    cloud: Cloud,
    region: str,
    matrix: CapabilityMatrix | None,
    today: date | None,
    allow_preview: bool,
) -> AdapterAvailability:
    problem = endpoint_problem(cloud, config.endpoint)
    if problem is not None:
        return _disabled(config.kind, problem[0], problem[1], config)
    if not config.model_feature:
        return _disabled(
            config.kind,
            "model_feature_missing",
            "no capability-matrix model feature is configured, so availability is unverified",
            config,
        )
    result = validate_profile(
        DeploymentProfile(
            cloud=cloud,
            regions=(region,),
            hosting="aks",
            analytics="fabric",
            features=_requests(config),
            allow_preview=allow_preview,
        ),
        matrix,
        today,
    )
    capabilities = tuple(r for r in result.results if r.kind == "feature")
    blocked = [r for r in capabilities if r.status == "disabled"]
    if blocked:
        first = blocked[0]
        return _disabled(
            config.kind,
            first.reason_code or "capability_unavailable",
            "; ".join(r.reason or r.capability for r in blocked),
            config,
            capabilities,
        )
    return AdapterAvailability(
        kind=config.kind, enabled=True, config=config, capabilities=capabilities
    )


def resolve_adapters(
    *,
    cloud: Cloud,
    region: str,
    configs: Sequence[AdapterConfig],
    matrix: CapabilityMatrix | None = None,
    today: date | None = None,
    allow_preview: bool = False,
) -> tuple[AdapterAvailability, ...]:
    """One availability entry per adapter kind, in ``ADAPTER_KINDS`` order."""
    by_kind: dict[AdapterKind, AdapterConfig] = {}
    for config in configs:
        if config.kind in by_kind:
            raise ValueError(f"duplicate adapter config for kind {config.kind!r}")
        by_kind[config.kind] = config
    out: list[AdapterAvailability] = []
    for kind in ADAPTER_KINDS:
        if kind == "fixture":
            out.append(AdapterAvailability(kind=kind, enabled=True, config=by_kind.get(kind)))
        elif kind not in by_kind:
            out.append(_disabled(kind, "not_configured", f"{kind} is not configured"))
        else:
            out.append(_evaluate(by_kind[kind], cloud, region, matrix, today, allow_preview))
    return tuple(out)


def create_adapter(
    availability: AdapterAvailability,
    *,
    cloud: Cloud,
    credential: AsyncTokenCredential | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
    scenario: str | None = None,
) -> ModelAdapter:
    """Build the adapter for an enabled entry; a disabled one raises ``capability_unavailable``.

    ``credential`` is a managed-identity ``AsyncTokenCredential`` (required for the REST
    adapters). ``scenario`` selects the recorded conversation for the fixture adapter.
    """
    if not availability.enabled:
        raise CapabilityUnavailableError(
            availability.reason_code or "capability_unavailable", availability.reason
        )
    if availability.kind == "fixture":
        return FixtureAdapter(scenario or "text_answer")
    if availability.config is None or credential is None:
        raise CapabilityUnavailableError(
            "credential_required", "a managed-identity credential is required"
        )
    if availability.kind == "approved_endpoint":
        return ApprovedEndpointAdapter(
            availability.config, cloud=cloud, credential=credential, transport=transport
        )
    return FoundryAgentAdapter(
        availability.config, cloud=cloud, credential=credential, transport=transport
    )
