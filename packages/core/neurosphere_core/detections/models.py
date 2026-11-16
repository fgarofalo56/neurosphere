"""Detection value types and reader protocols (PRP-61 item 2).

Everything here is metadata: resource names, policy names, fragment names, counts and ids. No
prompt, response, request body, policy XML or key has a field to live in. Readers return these
types; the worker readers (item 3) copy allowlisted fields out of raw payloads and drop the rest.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Final, Literal, Protocol, runtime_checkable

__all__ = [
    "CROSS_CLOUD_REASON",
    "KIND_CONFIGURATION_FINDING",
    "KIND_UNREGISTERED_AI_RESOURCE",
    "RULE_CONTENT_FILTER",
    "RULE_CONTENT_FILTER_UNSET_ONLY",
    "RULE_GATEWAY_FRAGMENT",
    "RULE_SHADOW_AI",
    "RULE_VERSION",
    "AccountRead",
    "AiAccount",
    "AiAccountInventory",
    "CatalogDeploymentReader",
    "CatalogRead",
    "CoverageStatus",
    "DeploymentConfig",
    "DeploymentConfigRead",
    "DeploymentConfigReader",
    "DetectionRule",
    "Finding",
    "GatewayFragments",
    "GatewayInventoryReader",
    "GatewayRead",
    "ReadStatus",
    "RuleResult",
    "digest",
    "opaque",
    "segment",
]

RULE_VERSION: Final = "1.0.0"
RULE_CONTENT_FILTER: Final = "detect.content_filter_policy"
#: Used as the generator id when no acceptable list is configured (only ``unset`` is reported).
RULE_CONTENT_FILTER_UNSET_ONLY: Final = "detect.content_filter_policy.unset_only"
RULE_GATEWAY_FRAGMENT: Final = "detect.gateway_policy_fragment"
RULE_SHADOW_AI: Final = "detect.shadow_ai_account"

KIND_CONFIGURATION_FINDING: Final = "configuration_finding"
KIND_UNREGISTERED_AI_RESOURCE: Final = "unregistered_ai_resource"

#: Reason code a reader reports when a target belongs to another cloud than the deployment.
CROSS_CLOUD_REASON: Final = "cross_cloud_refused"

_SEGMENT: Final = re.compile(r"[a-z0-9._-]+")
_OPAQUE_BAD: Final = re.compile(r"[^a-z0-9._:/=-]")


def segment(value: str | None) -> str | None:
    """A lowercase canonical-id segment (no ``/``), or ``None`` when the value cannot form one."""
    if value is None:
        return None
    lowered = value.strip().lower()
    return lowered if _SEGMENT.fullmatch(lowered) and len(lowered) <= 200 else None


def opaque(prefix: str, value: str) -> str:
    """An ``opaque_id`` evidence token: lowercase, restricted alphabet, bounded length."""
    cleaned = _OPAQUE_BAD.sub("_", f"{prefix}{value}".strip().lower())
    cleaned = cleaned.lstrip("._:/=-") or "x"
    return cleaned[:200]


def digest(value: str, length: int = 16) -> str:
    """Hex SHA-256 prefix: identifies a resource without carrying its id."""
    return hashlib.sha256(value.strip().lower().encode("utf-8")).hexdigest()[:length]


class CoverageStatus(StrEnum):
    FULL = "full"
    PARTIAL = "partial"
    UNKNOWN = "unknown"
    NOT_EVALUATED = "not_evaluated"
    CAPABILITY_UNAVAILABLE = "capability_unavailable"


#: ``ok`` the read finished; ``unreadable`` it failed (never a pass); ``capability_unavailable``
#: the capability matrix says the read does not exist in this cloud; ``cross_cloud`` refused.
ReadStatus = Literal["ok", "unreadable", "capability_unavailable", "cross_cloud"]


@dataclass(frozen=True, slots=True)
class Finding:
    """One rule violation, before it becomes a recommendation."""

    rule_id: str
    rule_version: str
    kind: str
    subject_id: str
    observed: str
    evidence: tuple[str, ...] = ()
    coverage: Literal["full", "partial"] = "full"
    domain_id: str | None = None


@dataclass(frozen=True, slots=True)
class RuleResult:
    rule_id: str
    coverage: CoverageStatus
    reason: str | None = None
    findings: tuple[Finding, ...] = ()
    truncated: bool = False
    unknown_targets: int = 0
    skipped_invalid: int = 0


@runtime_checkable
class DetectionRule(Protocol):
    rule_id: str

    async def evaluate(self) -> RuleResult: ...


# -------------------------------------------------------------------------------- readers


@dataclass(frozen=True, slots=True)
class DeploymentConfig:
    account: str
    name: str
    #: The deployment's content-filter (RAI) policy name, or ``None`` when unset.
    rai_policy: str | None


@dataclass(frozen=True, slots=True)
class DeploymentConfigRead:
    account: str
    status: ReadStatus = "ok"
    deployments: tuple[DeploymentConfig, ...] = ()
    truncated: bool = False
    reason: str | None = None


@runtime_checkable
class DeploymentConfigReader(Protocol):
    async def read(self) -> Sequence[DeploymentConfigRead]: ...


@dataclass(frozen=True, slots=True)
class GatewayFragments:
    gateway_id: str
    fragment_names: frozenset[str]
    domain_id: str | None = None
    #: Inventory lists ARM refused (for example ``policy_fragments``): not a pass.
    unreadable_lists: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class GatewayRead:
    status: ReadStatus = "ok"
    gateways: tuple[GatewayFragments, ...] = ()
    truncated: bool = False
    reason: str | None = None


@runtime_checkable
class GatewayInventoryReader(Protocol):
    async def read(self) -> GatewayRead: ...


@dataclass(frozen=True, slots=True)
class AiAccount:
    name: str
    resource_id: str
    location: str
    subscription_id: str
    tag_keys: tuple[str, ...] = field(default=())


@dataclass(frozen=True, slots=True)
class AccountRead:
    status: ReadStatus = "ok"
    accounts: tuple[AiAccount, ...] = ()
    truncated: bool = False
    reason: str | None = None


@runtime_checkable
class AiAccountInventory(Protocol):
    async def read(self) -> AccountRead: ...


@dataclass(frozen=True, slots=True)
class CatalogRead:
    """The ``foundry_project`` attribute values (``resource/project``) of model deployments."""

    ok: bool = True
    projects: frozenset[str] = frozenset()
    truncated: bool = False
    reason: str | None = None


@runtime_checkable
class CatalogDeploymentReader(Protocol):
    async def read(self) -> CatalogRead: ...
