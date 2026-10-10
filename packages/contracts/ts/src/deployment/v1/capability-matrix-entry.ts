/*
 * GENERATED - do not edit.
 * Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
 * Regenerate: python packages/contracts/scripts/generate.py
 * Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
 */

/**
 * One observed row of the capability matrix (NS-07, PRP-01 Clarification 17): whether a service feature is offered for a cloud, region and SKU, as stated by a cited source on a given date. Contract only; data and loader belong to PRP-02. availability, ga_status and authorization_scope are three independent fields with disjoint vocabularies and must never be merged into one status. authorization_scope records the external audit scope the cited source lists for the Azure service; it is not a claim that NeuroSphere holds FedRAMP authorization, an ATO or compliance parity. Unavailable combinations are disabled with a reason, never filled by routing to another cloud. Rules JSON Schema cannot express are checked by the Python validator check_capability_matrix in tests/contracts/test_capability_matrix.py (PRP-01 item 7): (service, feature, cloud, region, sku) is unique across a matrix; observed_on is not in the future.
 */
export interface CapabilityMatrixEntry {
  /**
   * Contract version of this document (semver within major 1).
   */
  schema_version: string;
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
   * Lowercase ARM region name, or global for non-regional offerings. Government rows use usgov* /usdod* regions; Commercial rows may not.
   */
  region: string;
  /**
   * SKU or tier the row applies to; null when the row is SKU-independent.
   */
  sku: string | null;
  /**
   * Is it offered here at all. Independent of ga_status and authorization_scope.
   */
  availability: "available" | "limited" | "unavailable" | "unknown";
  /**
   * Release maturity. Independent of availability and authorization_scope.
   */
  ga_status: "ga" | "public_preview" | "private_preview" | "deprecated" | "retired" | "unknown";
  /**
   * Audit scopes the cited source lists for this service in this cloud. not_in_scope and unknown must stand alone. Independent of availability and ga_status.
   *
   * @minItems 1
   */
  authorization_scope: [
    (
      | "fedramp_high"
      | "fedramp_moderate"
      | "dod_il2"
      | "dod_il4"
      | "dod_il5"
      | "dod_il6"
      | "not_in_scope"
      | "unknown"
    ),
    ...(
      | "fedramp_high"
      | "fedramp_moderate"
      | "dod_il2"
      | "dod_il4"
      | "dod_il5"
      | "dod_il6"
      | "not_in_scope"
      | "unknown"
    )[],
  ];
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
