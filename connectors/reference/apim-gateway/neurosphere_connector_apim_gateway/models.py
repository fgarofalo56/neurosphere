"""Plan and apply models for the APIM write connector (PRP-34 item 1).

A ``PublishPlan`` is the reviewed, immutable description of one change to one gateway: ordered
steps, each naming a resource, the operation, what the planner expected to find (``create`` when
the resource was absent, ``found`` when it existed) and a digest of the payload. The plan never
carries the payload itself, so a plan can be shown, stored and audited without exposing policy
XML. ``digest`` is SHA-256 over the intent facets (gateway, target, target version and every
step facet in order), so any reorder, any new or vanished resource and any payload change yields
a different digest.

``ApplyRecord`` is the ownership ledger of one apply: one ``StepRecord`` per completed step,
appended at write time. Rollback deletes only steps recorded ``created``; ``found`` resources are
restored to their captured prior document, never deleted.
"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Any, Final, Literal

from neurosphere_core.deploy.register.models import Ownership
from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "DEPENDENCY_ORDER",
    "SHA256_PATTERN",
    "ApplyRecord",
    "ApplyStatus",
    "PlanStep",
    "PublishPlan",
    "ResourceSpec",
    "ResourceType",
    "StepOperation",
    "StepOwnership",
    "StepRecord",
    "classify_path",
]

SHA256_PATTERN: Final = r"^[0-9a-f]{64}$"
_SEG: Final = r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}"


class ResourceType(StrEnum):
    """APIM child resource kinds the connector writes, in no particular order (see below)."""

    NAMED_VALUE = "named_value"
    BACKEND = "backend"
    POLICY_FRAGMENT = "policy_fragment"
    API = "api"
    API_OPERATION = "api_operation"
    API_POLICY = "api_policy"
    PRODUCT = "product"
    PRODUCT_POLICY = "product_policy"
    PRODUCT_API_LINK = "product_api_link"
    SUBSCRIPTION = "subscription"


# Load-bearing write order. A policy fragment that names a backend fails on a real gateway when
# the backend does not exist yet (MOSAIC ADR-0010 finding); an API policy includes fragments;
# product links need the product and the API; a subscription is scoped to the product. Deletes
# run in the reverse of this order. ``product_policy`` sits after ``product`` (item 5 grants).
DEPENDENCY_ORDER: Final[tuple[ResourceType, ...]] = (
    ResourceType.NAMED_VALUE,
    ResourceType.BACKEND,
    ResourceType.POLICY_FRAGMENT,
    ResourceType.API,
    ResourceType.API_OPERATION,
    ResourceType.API_POLICY,
    ResourceType.PRODUCT,
    ResourceType.PRODUCT_POLICY,
    ResourceType.PRODUCT_API_LINK,
    ResourceType.SUBSCRIPTION,
)

# Relative ARM path (below the service id) per resource type. Names are validated segments, so a
# path can never climb out of the gateway or address another provider.
_PATHS: Final[tuple[tuple[ResourceType, re.Pattern[str]], ...]] = (
    (ResourceType.NAMED_VALUE, re.compile(rf"^namedValues/{_SEG}$")),
    (ResourceType.BACKEND, re.compile(rf"^backends/{_SEG}$")),
    (ResourceType.POLICY_FRAGMENT, re.compile(rf"^policyFragments/{_SEG}$")),
    (ResourceType.API, re.compile(rf"^apis/{_SEG}$")),
    (ResourceType.API_OPERATION, re.compile(rf"^apis/{_SEG}/operations/{_SEG}$")),
    (ResourceType.API_POLICY, re.compile(rf"^apis/{_SEG}/policies/policy$")),
    (ResourceType.PRODUCT, re.compile(rf"^products/{_SEG}$")),
    (ResourceType.PRODUCT_POLICY, re.compile(rf"^products/{_SEG}/policies/policy$")),
    (ResourceType.PRODUCT_API_LINK, re.compile(rf"^products/{_SEG}/apiLinks/{_SEG}$")),
    (ResourceType.SUBSCRIPTION, re.compile(rf"^subscriptions/{_SEG}$")),
)


def classify_path(path: str) -> ResourceType | None:
    """Resource type of a relative APIM path, or None when the path is not one we write."""
    for rtype, pattern in _PATHS:
        if pattern.fullmatch(path):
            return rtype
    return None


StepOperation = Literal["upsert", "delete"]
Expected = Literal["create", "found"]


class StepOwnership(StrEnum):
    """Ownership recorded at write time. ``found`` maps to the register's ``reused``."""

    CREATED = "created"
    FOUND = "found"

    def to_register(self) -> Ownership:
        return Ownership.CREATED if self is StepOwnership.CREATED else Ownership.REUSED


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ResourceSpec(_Frozen):
    """One desired resource state: the payload lives here, never in the plan."""

    resource_type: ResourceType
    name: str = Field(min_length=1, max_length=400)
    operation: StepOperation = "upsert"
    payload: dict[str, Any] | None = None


class PlanStep(_Frozen):
    index: int = Field(ge=0)
    resource_type: ResourceType
    name: str = Field(min_length=1, max_length=400)
    operation: StepOperation
    expected: Expected
    changes: bool
    payload_digest: str | None = Field(default=None, pattern=SHA256_PATTERN)


class PublishPlan(_Frozen):
    gateway_id: str = Field(min_length=1, max_length=64)
    target: str = Field(min_length=1, max_length=512)
    target_version: str = Field(min_length=1, max_length=256)
    steps: tuple[PlanStep, ...]
    digest: str = Field(pattern=SHA256_PATTERN)

    @property
    def would_change(self) -> bool:
        return any(s.changes for s in self.steps)


ApplyStatus = Literal["applying", "succeeded", "rolled_back", "rollback_failed"]


class StepRecord(_Frozen):
    index: int = Field(ge=0)
    resource_type: ResourceType
    name: str
    operation: StepOperation
    ownership: StepOwnership
    wrote: bool
    etag_after: str | None = None
    # Prior ``properties`` of a found resource that was updated or deleted, for rollback. Stored
    # in the append-only record store only; never logged and never returned in an API result.
    prior: dict[str, Any] | None = None


class ApplyRecord(_Frozen):
    id: str = Field(min_length=1, max_length=128)
    gateway_id: str
    target: str
    plan_digest: str = Field(pattern=SHA256_PATTERN)
    status: ApplyStatus
    steps: tuple[StepRecord, ...] = ()
    orphans: tuple[str, ...] = ()
