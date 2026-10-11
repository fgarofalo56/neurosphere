/*
 * GENERATED - do not edit.
 * Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
 * Regenerate: python packages/contracts/scripts/generate.py
 * Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
 */

/**
 * One observed row of the capability matrix (NS-07, PRP-01 Clarification 17; amended in place for PRP-02 Item 0, schema_version 1.1.0): whether a service feature is offered for a cloud, region and SKU, as stated by a cited source on a given date. Contract only; data and loader belong to PRP-02. availability, ga_status and authorization_scope are three independent fields and must never be merged into one status. authorization_scope is a citation of the audit-scope text the source gives for the Azure service, or the literal none_claimed; it is never a claim that NeuroSphere or the dependency is authorized for any agency, an ATO or compliance parity. Unavailable combinations are disabled with a reason, never filled by routing to another cloud. Rules JSON Schema cannot express are checked by the Python validator check_capability_matrix in tests/contracts/validators.py (PRP-01 item 7): (service, feature, cloud, region, sku) is unique across a matrix; id is unique and equals the derived convention; observed_on is not in the future; a government wildcard region covers government regions only.
 */
export interface CapabilityMatrixEntry {
  /**
   * Contract version of this document (semver within major 1).
   */
  schema_version: string;
  /**
   * Stable canonical citation handle for this row, used by ADRs and capability_unavailable reasons. Convention (enforced by check_capability_matrix so it cannot drift from the uniqueness key): <service>.<feature>.<cloud>.<region>.<sku-or-any>, lowercased, with any for a null sku and for the * region; a sku is lowercased and each run of characters outside a-z, 0-9, _ and - becomes a single -, trimmed of leading and trailing -.
   */
  id: string;
  /**
   * Azure service key, snake_case (for example azure_openai, cosmos_db, fabric, synapse, databricks, ai_search, event_hubs).
   */
  service: string;
  /**
   * Feature key within the service, snake_case (for example model_gpt_4o, private_endpoint, change_feed). Use base for the service itself.
   */
  feature: string;
  /**
   * Azure cloud this row describes.
   */
  cloud: "commercial" | "government";
  /**
   * Lowercase ARM region name, global for non-regional offerings, or the wildcard * only when the cited source states the row holds for every region of the cloud. Government rows use usgov* /usdod* regions, global or *; a Government * covers Government regions only and never matches a Commercial region. Commercial rows may not use usgov* /usdod* regions.
   */
  region: string;
  /**
   * SKU or tier the row applies to; null when the row is SKU-independent (no * wildcard for sku).
   */
  sku: string | null;
  /**
   * Is it offered here at all. unverified means the source does not say. Independent of ga_status and authorization_scope.
   */
  availability: "available" | "preview" | "unavailable" | "unverified";
  /**
   * Release maturity. not_applicable when maturity has no meaning (for example an unavailable row); unverified means the source does not say. Independent of availability and authorization_scope.
   */
  ga_status: "ga" | "preview" | "not_applicable" | "unverified";
  /**
   * Citation of the audit-scope document or status text the source gives for this service in this cloud (for example 'FedRAMP High audit scope per <document>, 2026-09-21' or 'FedRAMP High assessment in progress; not authorized'), or the literal none_claimed. A citation only: never a claim that NeuroSphere or the dependency is authorized for an agency. Independent of availability and ga_status.
   */
  authorization_scope: string;
  /**
   * HTTPS URL of the authoritative source for this row. Recorded, never fetched by tests.
   */
  source_url: string;
  /**
   * Date (YYYY-MM-DD, UTC) the source was observed.
   */
  observed_on: string;
  /**
   * Caveats (for example region subset, quota or preview limits); null when none.
   */
  notes: string | null;
}
