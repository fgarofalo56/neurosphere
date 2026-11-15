/*
 * GENERATED - do not edit.
 * Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
 * Regenerate: python packages/contracts/scripts/generate.py
 * Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
 */

/**
 * A spend budget for one domain and period (PRP-44; evaluated against the cost ledger by PRP-46). Titled SpendBudget because query/v1 already exports a Budget (the query execution budget). amount is a decimal string in currency, never a float. thresholds_percent are alert points as integer percentages of amount (strictly ascending, so 50, 80, 100, 120). tags_filter narrows the budget to CostRecord rows whose tags contain every listed key and value; absent means every row of the domain. Rules JSON Schema cannot express (thresholds strictly ascending) are checked by tests/contracts/validators.py::check_budget_thresholds_ascending.
 */
export interface SpendBudget {
  /**
   * Contract version of the document, major 1 with additive minor revisions (ADR-0004).
   */
  schema_version: string;
  /**
   * Lowercase operator-chosen identifier.
   */
  budget_id: string;
  /**
   * Canonical Domain id (type segment 'domain'). No wildcard or all-domains form exists.
   */
  domain_id: string;
  period: "monthly" | "quarterly" | "annual";
  /**
   * Non-negative decimal string, up to 18 integer and 12 fractional digits; no exponent, no float.
   */
  amount: string;
  /**
   * ISO 4217 alphabetic currency code.
   */
  currency: string;
  /**
   * @minItems 1
   * @maxItems 10
   */
  thresholds_percent: [number, ...number[]];
  tags_filter?: CostTags;
}
/**
 * Absent means every cost row of the domain.
 */
export interface CostTags {
  /**
   * This interface was referenced by `CostTags`'s JSON-Schema definition
   * via the `patternProperty` "^[a-z][a-z0-9_.-]{0,62}$".
   */
  [k: string]: string | undefined;
}
