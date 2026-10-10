/*
 * GENERATED - do not edit.
 * Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
 * Regenerate: python packages/contracts/scripts/generate.py
 * Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
 */

/**
 * Calendar date YYYY-MM-DD.
 *
 * This interface was referenced by `CostRecord`'s JSON-Schema
 * via the `definition` "date".
 */
export type Date = string;
/**
 * This interface was referenced by `CostRecord`'s JSON-Schema
 * via the `definition` "identifier".
 */
export type Identifier = string;
/**
 * RFC 3339 timestamp in UTC (Z suffix).
 *
 * This interface was referenced by `CostRecord`'s JSON-Schema
 * via the `definition` "timestamp".
 */
export type Timestamp = string;
/**
 * This interface was referenced by `CostRecord`'s JSON-Schema
 * via the `definition` "label".
 */
export type Label = string;
/**
 * Non-negative decimal string, up to 18 integer and 12 fractional digits.
 *
 * This interface was referenced by `CostRecord`'s JSON-Schema
 * via the `definition` "non_negative_amount".
 */
export type NonNegativeAmount = string;
/**
 * Signed decimal string, up to 18 integer and 12 fractional digits; no exponent, no float.
 *
 * This interface was referenced by `CostRecord`'s JSON-Schema
 * via the `definition` "decimal_amount".
 */
export type DecimalAmount = string;

/**
 * One cost observation in the ledger (NS-01). Estimated and invoiced spend are always distinct records (kind). Money is a decimal string plus an ISO 4217 currency code; never a float. Missing values are null, never 0. The same spend seen by gateway, application and billing shares a dedupe_key so PRP-07 can avoid double counting. Rules JSON Schema cannot express are enforced by Python validators in tests/contracts: validate_billing_period_order (billing_period.start_date <= end_date), validate_usage_window_order (usage_start <= usage_end when both set), validate_allocation_within_amount (sum of non-null allocation components <= abs(amount)) and validate_retry_amount_within_amount (retry_amount <= abs(amount)).
 */
export interface CostRecord {
  /**
   * Contract version of this document, major 1 with additive minor revisions.
   */
  schema_version: string;
  /**
   * Unique identifier of this cost record.
   */
  cost_id: string;
  /**
   * estimated: computed from usage and a price sheet (must cite price_version). invoiced: taken from a provider bill (must carry billing_period).
   */
  kind: "estimated" | "invoiced";
  /**
   * Total cost as a decimal string in currency. Negative values represent credits or refunds.
   */
  amount: string;
  /**
   * ISO 4217 alphabetic currency code.
   */
  currency: string;
  /**
   * Identifier of the price sheet used to estimate. Required (non-null) when kind is estimated.
   */
  price_version?: string | null;
  /**
   * Date the cited price sheet took effect (YYYY-MM-DD). Required (non-null) when kind is estimated.
   */
  price_effective_date?: Date | null;
  /**
   * Provider billing period. Required (non-null) when kind is invoiced.
   */
  billing_period?: BillingPeriod | null;
  /**
   * Provider invoice identifier for invoiced records. Null when unknown or estimated.
   */
  invoice_id?: Identifier | null;
  /**
   * Start of the usage window this cost covers (RFC 3339 UTC). Null when the source reports only a billing period.
   */
  usage_start?: Timestamp | null;
  /**
   * End of the usage window this cost covers (RFC 3339 UTC). Null when unknown.
   */
  usage_end?: Timestamp | null;
  /**
   * Azure cloud boundary the cost belongs to. Government data is never bridged to Commercial.
   */
  cloud: "commercial" | "government";
  /**
   * Customer (tenant deployment) identifier.
   */
  customer_id: string;
  /**
   * Domain the cost is attributed to. Null when unattributed.
   */
  domain_id?: Identifier | null;
  /**
   * Connector or producer that reported the cost.
   */
  source_id: string;
  /**
   * Canonical agent the cost is attributed to (cloud:customer:source:type:id). Null when not attributable; per-user attribution is never promised.
   */
  canonical_agent_id?: string | null;
  /**
   * Model or service provider. Null when unknown.
   */
  provider?: Label | null;
  /**
   * Model name. Null when unknown or not model-specific.
   */
  model?: Label | null;
  /**
   * Model version. Null when unknown.
   */
  model_version?: Label | null;
  /**
   * Token counts behind this cost, including cached tokens. Null when not reported.
   */
  token_breakdown?: TokenBreakdown | null;
  /**
   * Number of retries included in this cost. Null when unknown; 0 only when measured.
   */
  retry_count?: number | null;
  /**
   * Portion of amount attributable to retries, decimal string in currency. Null when unknown.
   */
  retry_amount?: NonNegativeAmount | null;
  /**
   * Breakdown of amount by cost basis. Null when no breakdown is available.
   */
  allocation?: CostAllocation | null;
  /**
   * TelemetryEvent event_ids this cost was derived from. Null when not derived from events.
   *
   * @maxItems 1000
   */
  event_ids?: Identifier[] | null;
  /**
   * Stable key identifying the underlying spend independent of observation source. Records sharing a dedupe_key describe the same spend; PRP-07 defines key composition and source precedence.
   */
  dedupe_key: string;
  /**
   * Where this cost was observed. Invoiced records always come from billing.
   */
  observation_source: "gateway" | "application" | "billing";
  /**
   * Reconciliation status against other observations of the same spend. Null when not yet reconciled.
   */
  reconciliation?: CostReconciliation | null;
  /**
   * RFC 3339 timestamp in UTC (Z suffix).
   */
  recorded_at: string;
}
/**
 * Inclusive provider billing period. start_date <= end_date is checked by validate_billing_period_order.
 *
 * This interface was referenced by `CostRecord`'s JSON-Schema
 * via the `definition` "billing_period".
 */
export interface BillingPeriod {
  start_date: Date;
  end_date: Date;
}
/**
 * Token counts for one model interaction. Each count is nullable and defaults to null: null means not reported, 0 means a measured zero. Also referenced by cost/v1/cost-record.schema.json.
 */
export interface TokenBreakdown {
  input?: number | null;
  output?: number | null;
  /**
   * Input tokens served from a provider prompt cache.
   */
  cached?: number | null;
  /**
   * Reasoning tokens reported separately by the provider.
   */
  reasoning?: number | null;
}
/**
 * Portion of amount per cost basis, each a non-negative decimal string in the record currency or null when not allocated/unknown.
 *
 * This interface was referenced by `CostRecord`'s JSON-Schema
 * via the `definition` "allocation".
 */
export interface CostAllocation {
  /**
   * Pay-as-you-go compute or token-metered spend.
   */
  compute?: NonNegativeAmount | null;
  /**
   * Provisioned throughput unit allocation.
   */
  ptu?: NonNegativeAmount | null;
  /**
   * Reserved-capacity amortization.
   */
  reservation?: NonNegativeAmount | null;
  /**
   * License or per-seat subscription cost.
   */
  license_seat?: NonNegativeAmount | null;
}
/**
 * Reconciliation of this record against other observations of the same dedupe_key. Coverage is not a promise that all spend is observable.
 *
 * This interface was referenced by `CostRecord`'s JSON-Schema
 * via the `definition` "reconciliation".
 */
export interface CostReconciliation {
  status: "unreconciled" | "partial" | "reconciled" | "unknown";
  /**
   * Fraction of the reference spend matched by observations, in [0, 1]. Null when unknown.
   */
  coverage?: number | null;
  /**
   * This amount minus the reference amount, decimal string in the record currency. Null when unknown.
   */
  variance?: DecimalAmount | null;
  /**
   * cost_ids this record was reconciled against. Null when none.
   *
   * @maxItems 1000
   */
  reference_cost_ids?: Identifier[] | null;
  /**
   * When reconciliation last ran (RFC 3339 UTC). Null when never.
   */
  reconciled_at?: Timestamp | null;
}
