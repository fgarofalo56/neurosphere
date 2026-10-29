"""APIM gateway registration and inventory snapshot models (PRP-33 item 6, observe mode).

A registration is the NeuroSphere-side record of ONE customer-owned API Management service,
addressed by its ARM resource id. Observe mode is read-only: nothing here, and nothing that
consumes these models, writes to the gateway. The inventory is a snapshot rebuilt wholesale on
every sync; it is never edited by hand and never merged.

What is deliberately NOT modelled (so it cannot be stored by accident): policy XML or fragment
bodies, subscription keys, named-value values, backend credentials.
"""

from __future__ import annotations

import hashlib
import re
from typing import Annotated, Final, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints, field_validator

__all__ = [
    "ARM_ID_PATTERN",
    "GATEWAY_ID_PATTERN",
    "TIERS",
    "ApiEntry",
    "BackendEntry",
    "CircuitBreakerRule",
    "DiagnosticsState",
    "GatewayInventory",
    "GatewayRegistration",
    "OperationEntry",
    "PolicyFragmentEntry",
    "PoolMember",
    "ProductApiLink",
    "ProductEntry",
    "SubscriptionEntry",
    "Tier",
    "gateway_id_for",
    "normalize_arm_id",
]

Tier = Literal[
    "consumption",
    "developer",
    "basic",
    "standard",
    "premium",
    "basic_v2",
    "standard_v2",
    "premium_v2",
    "unknown",
]
TIERS: Final = (
    "consumption",
    "developer",
    "basic",
    "standard",
    "premium",
    "basic_v2",
    "standard_v2",
    "premium_v2",
)

ARM_ID_PATTERN: Final = (
    r"^/subscriptions/[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
    r"/resourceGroups/[A-Za-z0-9_.()-]{1,90}"
    r"/providers/Microsoft\.ApiManagement/service/[A-Za-z][A-Za-z0-9-]{0,49}$"
)
GATEWAY_ID_PATTERN: Final = r"^gw-[0-9a-f]{32}$"
_ARM_ID_RE: Final = re.compile(ARM_ID_PATTERN, re.IGNORECASE)
_GUID_RE: Final = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)

Short = Annotated[str, StringConstraints(max_length=512)]


def normalize_arm_id(arm_resource_id: str) -> str:
    """Validated ARM id (shape only); ARM ids compare case-insensitively, so identity uses lower."""
    if not _ARM_ID_RE.fullmatch(arm_resource_id):
        raise ValueError("arm_resource_id is not an API Management service resource id")
    return arm_resource_id


def gateway_id_for(customer_id: str, domain_id: str, arm_resource_id: str) -> str:
    """Deterministic id: registering the same service twice in one domain is a conflict."""
    digest = hashlib.sha256(
        f"{customer_id}\n{domain_id}\n{arm_resource_id.lower()}".encode()
    ).hexdigest()
    return f"gw-{digest[:32]}"


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DiagnosticsState(_Model):
    gateway_logs: bool = False
    gateway_llm_logs: bool = False
    gateway_mcp_logs: bool = False
    workspace_resource_id: str | None = Field(default=None, max_length=1024)


class GatewayRegistration(_Model):
    id: Annotated[str, StringConstraints(pattern=GATEWAY_ID_PATTERN)]
    customer_id: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    domain_id: Annotated[str, StringConstraints(min_length=1, max_length=512)]
    cloud: Literal["commercial", "government"]
    arm_resource_id: str
    name: Annotated[str, StringConstraints(min_length=1, max_length=50)]
    tier: Tier
    sku_name_raw: str | None = Field(default=None, max_length=64)
    mode: Literal["observe"] = "observe"
    workspace_id: str | None = None
    diagnostics: DiagnosticsState = Field(default_factory=DiagnosticsState)
    capabilities: dict[str, str] = Field(default_factory=dict)
    last_sync_at: AwareDatetime | None = None
    last_sync_status: Literal["ok", "failed", "never"] = "never"
    freshness_seconds: int | None = Field(default=None, ge=0)
    coverage: float | None = Field(default=None, ge=0.0, le=1.0)
    # Written only by the gateway_poll worker role (PRP-33 item 4): the end of the last fully
    # answered log slice, and a short machine code for the outcome of the latest poll.
    poll_watermark: AwareDatetime | None = None
    poll_status: str | None = Field(default=None, max_length=64)
    etag: str | None = None
    created_at: AwareDatetime
    updated_at: AwareDatetime
    registered_by: Annotated[str, StringConstraints(min_length=1, max_length=256)]

    @field_validator("arm_resource_id")
    @classmethod
    def _arm_id(cls, value: str) -> str:
        return normalize_arm_id(value)

    @field_validator("workspace_id")
    @classmethod
    def _workspace(cls, value: str | None) -> str | None:
        if value is not None and not _GUID_RE.fullmatch(value):
            raise ValueError("workspace_id must be a Log Analytics workspace GUID")
        return value

    def sort_key(self) -> str:
        return f"{self.created_at.isoformat()}#{self.id}"


# -- inventory ------------------------------------------------------------------------------------


class ApiEntry(_Model):
    id: Short
    name: Short | None = None
    path: Short | None = None
    protocols: list[str] = Field(default_factory=list, max_length=8)
    api_type: str | None = Field(default=None, max_length=64)
    subscription_required: bool | None = None
    revision: str | None = Field(default=None, max_length=64)


class OperationEntry(_Model):
    api_id: Short
    id: Short
    method: str | None = Field(default=None, max_length=16)
    url_template: Short | None = None


class ProductEntry(_Model):
    id: Short
    name: Short | None = None
    state: str | None = Field(default=None, max_length=32)
    subscription_required: bool | None = None
    approval_required: bool | None = None


class ProductApiLink(_Model):
    product_id: Short
    api_id: Short


class PoolMember(_Model):
    backend_id: Short
    weight: int | None = None
    priority: int | None = None


class CircuitBreakerRule(_Model):
    name: Short | None = None
    trip_duration: str | None = Field(default=None, max_length=64)
    failure_count: int | None = None
    failure_interval: str | None = Field(default=None, max_length=64)
    status_codes: list[str] = Field(default_factory=list, max_length=64)


class BackendEntry(_Model):
    id: Short
    type: Literal["Single", "Pool"]
    url: Short | None = None
    pool_members: list[PoolMember] = Field(default_factory=list)
    circuit_breaker_rules: list[CircuitBreakerRule] = Field(default_factory=list)


class PolicyFragmentEntry(_Model):
    """Name and description only. The fragment XML is never read into the snapshot."""

    name: Short
    description: str | None = Field(default=None, max_length=1024)


class SubscriptionEntry(_Model):
    """APIM subscription metadata. Keys are never requested (no ``listSecrets``)."""

    id: Short
    display_name: Short | None = None
    scope: Short | None = None
    state: str | None = Field(default=None, max_length=32)


class GatewayInventory(_Model):
    gateway_id: Annotated[str, StringConstraints(pattern=GATEWAY_ID_PATTERN)]
    taken_at: AwareDatetime
    apis: list[ApiEntry] = Field(default_factory=list)
    operations: list[OperationEntry] = Field(default_factory=list)
    products: list[ProductEntry] = Field(default_factory=list)
    product_api_links: list[ProductApiLink] = Field(default_factory=list)
    backends: list[BackendEntry] = Field(default_factory=list)
    policy_fragments: list[PolicyFragmentEntry] = Field(default_factory=list)
    subscriptions: list[SubscriptionEntry] = Field(default_factory=list)

    def counts(self) -> dict[str, int]:
        return {
            "apis": len(self.apis),
            "operations": len(self.operations),
            "products": len(self.products),
            "backends": len(self.backends),
            "policy_fragments": len(self.policy_fragments),
            "subscriptions": len(self.subscriptions),
        }
