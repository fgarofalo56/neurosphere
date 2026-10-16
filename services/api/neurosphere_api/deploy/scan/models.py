"""Request and response models for the consented resource scan."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints

VISIBILITY_NOTE = (
    "Results reflect only what the calling identity can read. A subscription reported "
    "not_visible may still contain resources; absence of results is not absence of resources."
)

_GUID = r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"


def _lower(value: str) -> str:
    return value.lower()


SubscriptionId = Annotated[str, StringConstraints(pattern=_GUID), AfterValidator(_lower)]
ResourceCategory = Literal[
    "apim",
    "model_endpoint",
    "key_vault",
    "monitoring",
    "event_hubs",
    "storage",
    "analytics_workspace",
]


class ConsentRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    consent_id: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    consented_by: Annotated[str, StringConstraints(min_length=1, max_length=320)]
    consented_subscriptions: list[SubscriptionId] = Field(max_length=1000)


class ScanRequest(BaseModel):
    """``consent`` is optional in the schema so a missing record is a 403, not a 422."""

    model_config = ConfigDict(extra="forbid")

    consent: ConsentRecord | None = None
    subscription_ids: list[SubscriptionId] = Field(min_length=1, max_length=1000)


class DiscoveredResource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: ResourceCategory
    type: str
    id: str
    name: str
    location: str | None = None
    sku: str | None = None
    subscription_id: str
    tags: dict[str, str] = Field(default_factory=dict)


class SubscriptionScan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subscription_id: str
    status: Literal["visible", "not_visible"]
    resources: list[DiscoveredResource] = Field(default_factory=list)
    note: str | None = None


class ScanResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    visibility_limited: Literal[True] = True
    visibility_note: str = VISIBILITY_NOTE
    consent_id: str
    scanned_at: datetime
    subscriptions: list[SubscriptionScan]
