"""Ledger models (PRP-07 C11-C13). Internal to the ledger; the contract ``CostRecord`` is per
observation and is not edited. All models are frozen with ``extra="forbid"``.

Money is ``Decimal`` only (never float), quantized to 12 fractional digits (the contract limit)
and serialized as a plain decimal string (no exponent). ``None`` means unknown and is never 0.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_EVEN, Context, Decimal
from typing import Annotated, Any, Final, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    PlainSerializer,
    model_validator,
)

SCHEMA_VERSION: Final = "1"
DEFAULT_COST_CATEGORY: Final = "model_inference"
UNKNOWN_CURRENCY: Final = "XXX"  # ISO 4217 "no currency": entries whose currency is not known

ObservationKind = Literal["gateway", "application", "billing"]
AmountKind = Literal["estimated", "invoiced"]

_QUANT: Final = Decimal(1).scaleb(-12)
_CTX: Final = Context(prec=60, rounding=ROUND_HALF_EVEN)


def quantize(value: Decimal) -> Decimal:
    """Normalize to 12 fractional digits so equal amounts have one representation."""
    return value.quantize(_QUANT, context=_CTX)


def _money(value: Decimal) -> Decimal:
    if not value.is_finite():
        raise ValueError("amount must be finite")
    return quantize(value)


def _fmt_money(value: Decimal) -> str:
    return format(value, "f")


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("timestamp has no timezone")
    return value.astimezone(UTC)


def _fmt_time(value: datetime) -> str:
    # Fixed width (always microseconds) so ISO strings compare lexicographically in Cosmos SQL.
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


Money = Annotated[
    Decimal,
    AfterValidator(_money),
    PlainSerializer(_fmt_money, return_type=str, when_used="json"),
]
UtcTime = Annotated[
    datetime,
    AfterValidator(_utc),
    PlainSerializer(_fmt_time, return_type=str, when_used="json"),
]
Currency = Annotated[str, Field(pattern="^[A-Z]{3}$")]


def format_time(value: datetime) -> str:
    return _fmt_time(value)


def sha256_hex(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def entry_id(customer_id: str, request_id: str, cost_category: str) -> str:
    """One entry per (customer_id, request_id, cost_category): deterministic id (C11)."""
    return sha256_hex("entry", customer_id, request_id, cost_category)


def allocation_id(customer_id: str, observation_doc_id: str) -> str:
    return sha256_hex("allocation", customer_id, observation_doc_id)


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class TokenCounts(_Frozen):
    """Token counts; each ``None`` is unknown, never 0."""

    input: int | None = Field(default=None, ge=0)
    output: int | None = Field(default=None, ge=0)
    cached: int | None = Field(default=None, ge=0)
    reasoning: int | None = Field(default=None, ge=0)


class AllocationParts(_Frozen):
    """Cost-basis split (compute / PTU / reservation / seat). Kept apart from token cost."""

    compute: Money | None = None
    ptu: Money | None = None
    reservation: Money | None = None
    license_seat: Money | None = None


class Observation(_Frozen):
    """One accepted event's view of a request's cost, keyed by the event ``doc_id``."""

    observation_kind: ObservationKind
    doc_id: str = Field(min_length=64, max_length=64)
    kind: AmountKind
    amount: Money | None = None  # None = unknown (unknown tokens, or no resolvable price)
    currency: Currency | None = None
    price_version_id: str | None = Field(default=None, min_length=1, max_length=128)
    price_unresolved: bool = False
    observed_at: UtcTime
    period_end: date | None = None
    cloud: Literal["commercial", "government"]
    source_id: str
    domain_id: str | None = None
    provider: str | None = None
    model: str | None = None
    model_version: str | None = None
    token_breakdown: TokenCounts | None = None
    retry_count: int | None = Field(default=None, ge=0)
    retry_amount: Money | None = None
    allocation: AllocationParts | None = None

    @model_validator(mode="after")
    def _consistent(self) -> Observation:
        if self.amount is not None and self.currency is None:
            raise ValueError("a known amount needs a currency")
        if self.kind == "estimated" and not self.price_unresolved and self.price_version_id is None:
            raise ValueError("an estimated observation must cite price_version_id")
        if self.price_unresolved and self.amount is not None:
            raise ValueError("a price_unresolved observation has no amount")
        return self


class GroupSummary(_Frozen):
    """Observations of one precedence rank folded together (sum; unknown if any is unknown)."""

    rank: int
    source: ObservationKind
    kind: AmountKind
    amount: Money | None = None
    currency: Currency | None = None
    observation_count: int
    unknown_count: int
    unresolved_count: int
    currency_conflict: bool = False


class LedgerEntry(_Frozen):
    """The one record per (customer_id, request_id, cost_category). A pure function of its
    observation set: it is recomputed from ALL observations on every accept."""

    doc_type: Literal["entry"] = "entry"
    schema_version: str = SCHEMA_VERSION
    id: str
    customer_id: str
    request_id: str
    cost_category: str
    cloud: Literal["commercial", "government"]
    source_id: str
    domain_id: str | None = None
    provider: str | None = None
    model: str | None = None
    model_version: str | None = None
    observations: list[Observation]  # sorted by doc_id
    sources: list[GroupSummary]  # one per precedence rank present, best rank first
    estimated_amount: Money | None = None
    estimated_currency: Currency | None = None
    invoiced_amount: Money | None = None
    invoiced_currency: Currency | None = None
    authoritative_amount: Money | None = None
    authoritative_currency: Currency | None = None
    authoritative_source: ObservationKind | None = None
    authoritative_kind: AmountKind | None = None
    price_version_ids: list[str] = Field(default_factory=list)
    price_unresolved: bool = False
    currency_conflict: bool = False
    occurred_at: UtcTime  # earliest observation time: windows filter on this
    observed_at: UtcTime  # latest observation time: freshness
    period_end: date | None = None  # latest billing period end among observations
    retry_count: int | None = Field(default=None, ge=0)
    retry_amount: Money | None = None
    allocation: AllocationParts | None = None
    token_breakdown: TokenCounts | None = None
    content_hash: str = ""

    def with_hash(self) -> LedgerEntry:
        payload = self.model_dump(mode="json", exclude={"content_hash"})
        digest = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
        return self.model_copy(update={"content_hash": digest})


class AllocationRecord(_Frozen):
    """Vendor/period (or otherwise request-less) spend. Never merged into per-request entries."""

    doc_type: Literal["allocation"] = "allocation"
    schema_version: str = SCHEMA_VERSION
    id: str
    customer_id: str
    granularity: Literal["vendor_period", "unattributed"]
    observation_doc_id: str
    observation_kind: ObservationKind
    kind: AmountKind
    provider: str | None = None
    billing_period_start: date | None = None
    billing_period_end: date | None = None
    currency: Currency | None = None
    amount: Money | None = None
    allocation: AllocationParts | None = None  # PTU / reservation / compute / seat, separate
    retry_count: int | None = Field(default=None, ge=0)
    retry_amount: Money | None = None
    price_version_id: str | None = None
    cloud: Literal["commercial", "government"]
    source_id: str
    domain_id: str | None = None
    observed_at: UtcTime
    period_end: date | None = None
    content_hash: str = ""

    def with_hash(self) -> AllocationRecord:
        payload = self.model_dump(mode="json", exclude={"content_hash"})
        digest = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
        return self.model_copy(update={"content_hash": digest})
