"""Typed, bounded read models for the AWS Bedrock metadata connector.

Every model is frozen and ``extra="forbid"``. Free text is clipped, lists are capped, and no
field can carry a prompt, a response, a log line, a bucket or log-group name, or a credential:
the only strings are identifiers, display names, status words and modality names that Bedrock
list operations return. A value the source did not report is ``None``, never ``0`` or ``[]``.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

__all__ = [
    "MAX_COST_DAYS",
    "MAX_MODEL_IDS",
    "MAX_USAGE_HOURS",
    "USAGE_METRICS",
    "BedrockCostPoint",
    "BedrockCostResult",
    "BedrockInventory",
    "BedrockUsagePoint",
    "BedrockUsageResult",
    "CostWindow",
    "InventoryItem",
    "InvocationLoggingState",
    "UsageMetric",
    "UsageWindow",
    "clip",
]

#: CloudWatch metric names in the ``AWS/Bedrock`` namespace (documented, observed 2026-11-16).
UsageMetric = Literal["Invocations", "InputTokenCount", "OutputTokenCount"]
USAGE_METRICS: tuple[UsageMetric, ...] = ("Invocations", "InputTokenCount", "OutputTokenCount")

MAX_USAGE_HOURS = 24 * 7
MAX_COST_DAYS = 93
MAX_MODEL_IDS = 50
_MAX_TEXT = 256
_MAX_MODALITIES = 16


def clip(value: object, limit: int = _MAX_TEXT) -> str | None:
    """A bounded string, or None when the value is not a non-empty string."""
    if not isinstance(value, str) or not value:
        return None
    return value[:limit]


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class InventoryItem(_Frozen):
    """One Bedrock resource: a foundation model, custom model, throughput, guardrail or agent."""

    id: str = Field(max_length=_MAX_TEXT)
    name: str | None = Field(default=None, max_length=_MAX_TEXT)
    status: str | None = Field(default=None, max_length=64)
    provider: str | None = Field(default=None, max_length=_MAX_TEXT)
    input_modalities: list[str] | None = Field(default=None, max_length=_MAX_MODALITIES)
    output_modalities: list[str] | None = Field(default=None, max_length=_MAX_MODALITIES)
    created_at: datetime | None = None


class BedrockInventory(_Frozen):
    """One inventory pass. A list is ``None`` (unknown) when its call failed, never ``[]``."""

    region: str
    observed_at: datetime
    advisory: bool = True
    foundation_models: list[InventoryItem] | None = None
    custom_models: list[InventoryItem] | None = None
    provisioned_throughput: list[InventoryItem] | None = None
    guardrails: list[InventoryItem] | None = None
    agents: list[InventoryItem] | None = None
    truncated: list[str] = Field(default_factory=list)
    failed_sources: dict[str, str] = Field(default_factory=dict)


def _utc_hour(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("window bounds must be timezone-aware")
    return value.astimezone(UTC)


class UsageWindow(_Frozen):
    """Explicit hourly window ``[start, end)``, aligned to the hour, at most seven days."""

    start: datetime
    end: datetime

    @field_validator("start", "end")
    @classmethod
    def _aligned(cls, value: datetime) -> datetime:
        value = _utc_hour(value)
        if value.minute or value.second or value.microsecond:
            raise ValueError("window bounds must be aligned to the hour")
        return value

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if self.end <= self.start:
            raise ValueError("window end must be after start")
        if self.end - self.start > timedelta(hours=MAX_USAGE_HOURS):
            raise ValueError(f"usage window is capped at {MAX_USAGE_HOURS} hours")
        return self

    def hours(self) -> list[datetime]:
        count = int((self.end - self.start) / timedelta(hours=1))
        return [self.start + timedelta(hours=i) for i in range(count)]


class CostWindow(_Frozen):
    """Explicit daily window ``[start, end)`` (Cost Explorer: start inclusive, end exclusive)."""

    start: date
    end: date

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if self.end <= self.start:
            raise ValueError("window end must be after start")
        if (self.end - self.start).days > MAX_COST_DAYS:
            raise ValueError(f"cost window is capped at {MAX_COST_DAYS} days")
        return self

    def days(self) -> list[date]:
        return [self.start + timedelta(days=i) for i in range((self.end - self.start).days)]


class BedrockUsagePoint(_Frozen):
    """One hourly CloudWatch datapoint. ``value`` is None when CloudWatch returned none."""

    model_id: str = Field(max_length=_MAX_TEXT)
    metric: UsageMetric
    hour: datetime
    value: float | None = None


class BedrockUsageResult(_Frozen):
    region: str
    observed_at: datetime
    window: UsageWindow
    advisory: bool = True
    points: list[BedrockUsagePoint]
    truncated: bool = False


class BedrockCostPoint(_Frozen):
    """Daily Cost Explorer amount for one service. No price is computed here.

    ``amount_kind`` is what the API reported (``Estimated`` true is ``estimated``, false is
    ``invoiced``); None when the day had no row at all (``amount`` is then None too).
    """

    day: date
    service: str = Field(max_length=_MAX_TEXT)
    amount: Decimal | None = None
    currency: str | None = Field(default=None, max_length=16)
    amount_kind: Literal["estimated", "invoiced"] | None = None


class BedrockCostResult(_Frozen):
    region: str
    observed_at: datetime
    window: CostWindow
    advisory: bool = True
    points: list[BedrockCostPoint]
    truncated: bool = False


class InvocationLoggingState(_Frozen):
    """Whether model invocation logging is configured. Destination types only, never names."""

    region: str
    observed_at: datetime
    configured: bool
    cloudwatch: bool
    s3: bool
