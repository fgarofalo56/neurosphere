/*
 * GENERATED - do not edit.
 * Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
 * Regenerate: python packages/contracts/scripts/generate.py
 * Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
 */

/**
 * This interface was referenced by `PriceSheetUpload`'s JSON-Schema
 * via the `definition` "label".
 */
export type Label = string;

/**
 * An operator-uploaded price sheet (PRP-44). Maps one to one onto core pricing PriceSnapshot minus content_hash: the server builds the snapshot with build_snapshot, which stamps the hash, so an upload can never assert its own hash. Money is a decimal string, never a float. azure_retail_prices sheets apply to commercial only and their source_url host is prices.azure.com; Commercial prices are never a fallback for Government (both enforced again by PriceSnapshot). Rules JSON Schema cannot express are checked by tests/contracts/validators.py::check_price_sheet_upload: token price rows are unique per (provider, model, model_version, kind) and a token row's unit_of_measure is 1K or 1M.
 */
export interface PriceSheetUpload {
  /**
   * Contract version of the document, major 1 with additive minor revisions (ADR-0004).
   */
  schema_version: string;
  /**
   * Lowercase operator-chosen identifier.
   */
  snapshot_id: string;
  source: "azure_retail_prices" | "provider_price_sheet";
  /**
   * Where the sheet was obtained. HTTPS, no query string or fragment.
   */
  source_url: string;
  /**
   * Calendar date YYYY-MM-DD.
   */
  retrieval_date: string;
  /**
   * Calendar date YYYY-MM-DD.
   */
  effective_date: string;
  /**
   * ISO 4217 alphabetic currency code.
   */
  currency: string;
  /**
   * @minItems 1
   * @maxItems 2
   *
   * Items: Azure cloud boundary. Government data is never bridged to Commercial.
   */
  clouds: ["commercial" | "government", ...("commercial" | "government")[]];
  /**
   * true for demo or test sheets; synthetic prices are labelled wherever they are shown.
   */
  synthetic: boolean;
  notes: string;
  /**
   * @minItems 1
   * @maxItems 10000
   */
  rows: [PriceSheetRow, ...PriceSheetRow[]];
}
/**
 * One price (core PriceRow; Retail Prices API Items[] field names in snake_case).
 *
 * This interface was referenced by `PriceSheetUpload`'s JSON-Schema
 * via the `definition` "price_row".
 */
export interface PriceSheetRow {
  service_name: Label;
  sku_name: Label;
  meter_id?: Label | null;
  meter_name?: Label | null;
  arm_region_name?: string | null;
  unit_of_measure: Label;
  /**
   * Non-negative decimal string, up to 18 integer and 12 fractional digits; no exponent, no float.
   */
  retail_price: string;
  unit_price?: string | null;
  price_type?: Label;
  effective_start_date?: string | null;
  token_meter?: PriceSheetTokenMeter | null;
}
/**
 * Maps a price row to a model token price (core TokenMeter).
 *
 * This interface was referenced by `PriceSheetUpload`'s JSON-Schema
 * via the `definition` "token_meter".
 */
export interface PriceSheetTokenMeter {
  provider: Label;
  model: Label;
  model_version?: Label | null;
  kind: "input" | "output" | "cached";
}
