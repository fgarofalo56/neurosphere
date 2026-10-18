"""The normalized analytics record: the one row shape every adapter serves (PRP-11).

Fields are projected from the PRP-07 normalized model: the ledger ``Observation`` (cost and
tokens) and the PRP-01 ``TelemetryEvent`` (duration, span kind, outcome). Anything not
reported stays ``None`` (unknown), never 0. ``domain_id`` holds the canonical Domain ID
string, the same form as ``IdentityScope.allowed_domains``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Final

from neurosphere_contracts.telemetry.v1.telemetry_event import TelemetryEvent
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from neurosphere_core.analytics.base.models import Cloud
from neurosphere_core.ledger.models import Observation

ANALYTICS_TABLE: Final = "ns_analytics_events"
TIMESTAMP_FORMAT: Final = "%Y-%m-%dT%H:%M:%S.%fZ"  # fixed width: sorts as text


def format_timestamp(value: datetime) -> str:
    return value.astimezone(UTC).strftime(TIMESTAMP_FORMAT)


class AnalyticsRecord(BaseModel):
    """One row of the analytics table. Frozen; ``None`` means unknown."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str = Field(min_length=1, max_length=256)
    event_time: AwareDatetime
    cloud: Cloud
    customer_id: str = Field(min_length=1, max_length=128)
    domain_id: str | None = None
    provider: str | None = None
    model: str | None = None
    span_kind: str | None = None
    outcome: str | None = None
    currency: str | None = None
    duration_ms: int | None = Field(default=None, ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    cost_amount: Decimal | None = None


def record_from_observation(
    observation: Observation, *, customer_id: str, span_kind: str | None = None
) -> AnalyticsRecord:
    """Project a ledger ``Observation``. The observation carries no customer id: pass the
    owning ``LedgerEntry.customer_id``. Duration and outcome are not on the observation."""
    tokens = observation.token_breakdown
    return AnalyticsRecord(
        event_id=observation.doc_id,
        event_time=observation.observed_at,
        cloud=observation.cloud,
        customer_id=customer_id,
        domain_id=observation.domain_id,
        provider=observation.provider,
        model=observation.model,
        span_kind=span_kind,
        currency=observation.currency,
        input_tokens=tokens.input if tokens else None,
        output_tokens=tokens.output if tokens else None,
        cost_amount=observation.amount,
    )


def record_from_telemetry_event(event: TelemetryEvent) -> AnalyticsRecord:
    """Project a PRP-01 ``TelemetryEvent`` (no cost: amount and currency stay unknown)."""
    tokens = event.token_breakdown
    return AnalyticsRecord(
        event_id=event.event_id.root,
        event_time=datetime.fromisoformat(event.event_time.root),
        cloud=event.cloud,
        customer_id=event.customer_id.root,
        domain_id=event.domain_id.root if event.domain_id else None,
        provider=event.provider.root if event.provider else None,
        model=event.model.root if event.model else None,
        span_kind=event.span_kind,
        outcome=event.outcome,
        duration_ms=event.duration_ms,
        input_tokens=tokens.input if tokens else None,
        output_tokens=tokens.output if tokens else None,
    )
