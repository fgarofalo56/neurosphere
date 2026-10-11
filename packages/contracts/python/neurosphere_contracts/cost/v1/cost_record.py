# GENERATED - do not edit.
# Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
# Regenerate: python packages/contracts/scripts/generate.py
# Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
# pyright: reportAssignmentType=false, reportInvalidTypeForm=false

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    RootModel,
    StrictFloat,
    StrictInt,
    StrictStr,
)

from ...telemetry.v1 import telemetry_event


class Identifier(RootModel[StrictStr]):
    root: Annotated[StrictStr, Field(max_length=256, min_length=1)]


class Label(RootModel[StrictStr]):
    root: Annotated[StrictStr, Field(max_length=128, min_length=1)]


class DecimalAmount(RootModel[StrictStr]):
    root: Annotated[StrictStr, Field(pattern="^-?(0|[1-9][0-9]{0,17})(\\.[0-9]{1,12})?$")]
    """
    Signed decimal string, up to 18 integer and 12 fractional digits; no exponent, no float.
    """


class NonNegativeAmount(RootModel[StrictStr]):
    root: Annotated[StrictStr, Field(pattern="^(0|[1-9][0-9]{0,17})(\\.[0-9]{1,12})?$")]
    """
    Non-negative decimal string, up to 18 integer and 12 fractional digits.
    """


class Timestamp(RootModel[StrictStr]):
    root: Annotated[
        StrictStr,
        Field(
            pattern="^[0-9]{4}-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])T([01][0-9]|2[0-3]):[0-5][0-9]:([0-5][0-9]|60)(\\.[0-9]{1,9})?Z$"
        ),
    ]
    """
    RFC 3339 timestamp in UTC (Z suffix).
    """


class Date(RootModel[StrictStr]):
    root: Annotated[StrictStr, Field(pattern="^[0-9]{4}-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])$")]
    """
    Calendar date YYYY-MM-DD.
    """


class BillingPeriod(BaseModel):
    """
    Inclusive provider billing period. start_date <= end_date is checked by validate_billing_period_order.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    start_date: Date
    end_date: Date


class CostAllocation(BaseModel):
    """
    Portion of amount per cost basis, each a non-negative decimal string in the record currency or null when not allocated/unknown.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    compute: NonNegativeAmount | None = None
    """
    Pay-as-you-go compute or token-metered spend.
    """
    ptu: NonNegativeAmount | None = None
    """
    Provisioned throughput unit allocation.
    """
    reservation: NonNegativeAmount | None = None
    """
    Reserved-capacity amortization.
    """
    license_seat: NonNegativeAmount | None = None
    """
    License or per-seat subscription cost.
    """


class CostReconciliation(BaseModel):
    """
    Reconciliation of this record against other observations of the same dedupe_key. Coverage is not a promise that all spend is observable.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    status: Literal["unreconciled", "partial", "reconciled", "unknown"]
    coverage: Annotated[StrictFloat | None, Field(ge=0.0, le=1.0)] = None
    """
    Fraction of the reference spend matched by observations, in [0, 1]. Null when unknown.
    """
    variance: DecimalAmount | None = None
    """
    This amount minus the reference amount, decimal string in the record currency. Null when unknown.
    """
    reference_cost_ids: Annotated[list[Identifier] | None, Field(max_length=1000)] = None
    """
    cost_ids this record was reconciled against. Null when none.
    """
    reconciled_at: Timestamp | None = None
    """
    When reconciliation last ran (RFC 3339 UTC). Null when never.
    """


class CostRecord(BaseModel):
    """
    One cost observation in the ledger (NS-01). Estimated and invoiced spend are always distinct records (kind). Money is a decimal string plus an ISO 4217 currency code; never a float. Missing values are null, never 0. The same spend seen by gateway, application and billing shares a dedupe_key so PRP-07 can avoid double counting. Rules JSON Schema cannot express are enforced by Python validators in tests/contracts: validate_billing_period_order (billing_period.start_date <= end_date), validate_usage_window_order (usage_start <= usage_end when both set), validate_allocation_within_amount (sum of non-null allocation components <= abs(amount)) and validate_retry_amount_within_amount (retry_amount <= abs(amount)).
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    schema_version: Annotated[StrictStr, Field(pattern="^1\\.(0|[1-9][0-9]*)\\.(0|[1-9][0-9]*)$")]
    """
    Contract version of this document, major 1 with additive minor revisions.
    """
    cost_id: Identifier
    """
    Unique identifier of this cost record.
    """
    kind: Literal["estimated", "invoiced"]
    """
    estimated: computed from usage and a price sheet (must cite price_version). invoiced: taken from a provider bill (must carry billing_period).
    """
    amount: DecimalAmount
    """
    Total cost as a decimal string in currency. Negative values represent credits or refunds.
    """
    currency: Annotated[StrictStr, Field(pattern="^[A-Z]{3}$")]
    """
    ISO 4217 alphabetic currency code.
    """
    price_version: Annotated[StrictStr | None, Field(max_length=128, min_length=1)] = None
    """
    Identifier of the price sheet used to estimate. Required (non-null) when kind is estimated.
    """
    price_effective_date: Date | None = None
    """
    Date the cited price sheet took effect (YYYY-MM-DD). Required (non-null) when kind is estimated.
    """
    billing_period: BillingPeriod | None = None
    """
    Provider billing period. Required (non-null) when kind is invoiced.
    """
    invoice_id: Identifier | None = None
    """
    Provider invoice identifier for invoiced records. Null when unknown or estimated.
    """
    usage_start: Timestamp | None = None
    """
    Start of the usage window this cost covers (RFC 3339 UTC). Null when the source reports only a billing period.
    """
    usage_end: Timestamp | None = None
    """
    End of the usage window this cost covers (RFC 3339 UTC). Null when unknown.
    """
    cloud: Literal["commercial", "government"]
    """
    Azure cloud boundary the cost belongs to. Government data is never bridged to Commercial.
    """
    customer_id: Identifier
    """
    Customer (tenant deployment) identifier.
    """
    domain_id: Identifier | None = None
    """
    Domain the cost is attributed to. Null when unattributed.
    """
    source_id: Identifier
    """
    Connector or producer that reported the cost.
    """
    canonical_agent_id: telemetry_event.CanonicalId | None = None
    """
    Canonical agent the cost is attributed to (cloud:customer:source:type:id). Null when not attributable; per-user attribution is never promised.
    """
    provider: Label | None = None
    """
    Model or service provider. Null when unknown.
    """
    model: Label | None = None
    """
    Model name. Null when unknown or not model-specific.
    """
    model_version: Label | None = None
    """
    Model version. Null when unknown.
    """
    token_breakdown: telemetry_event.TokenBreakdown | None = None
    """
    Token counts behind this cost, including cached tokens. Null when not reported.
    """
    retry_count: Annotated[StrictInt | None, Field(ge=0)] = None
    """
    Number of retries included in this cost. Null when unknown; 0 only when measured.
    """
    retry_amount: NonNegativeAmount | None = None
    """
    Portion of amount attributable to retries, decimal string in currency. Null when unknown.
    """
    allocation: CostAllocation | None = None
    """
    Breakdown of amount by cost basis. Null when no breakdown is available.
    """
    event_ids: Annotated[list[Identifier] | None, Field(max_length=1000)] = None
    """
    TelemetryEvent event_ids this cost was derived from. Null when not derived from events.
    """
    dedupe_key: Identifier
    """
    Stable key identifying the underlying spend independent of observation source. Records sharing a dedupe_key describe the same spend; PRP-07 defines key composition and source precedence.
    """
    observation_source: Literal["gateway", "application", "billing"]
    """
    Where this cost was observed. Invoiced records always come from billing.
    """
    reconciliation: CostReconciliation | None = None
    """
    Reconciliation status against other observations of the same spend. Null when not yet reconciled.
    """
    recorded_at: Timestamp
    """
    When the ledger recorded this cost (RFC 3339 UTC).
    """
