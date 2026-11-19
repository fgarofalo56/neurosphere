/*
 * GENERATED - do not edit.
 * Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
 * Regenerate: python packages/contracts/scripts/generate.py
 * Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
 */

/**
 * This interface was referenced by `ControlMapping`'s JSON-Schema
 * via the `definition` "support_status".
 */
export type SupportStatus =
  "designed" | "implemented_tested" | "inherited" | "customer" | "planned" | "not_applicable";
/**
 * This interface was referenced by `ControlMapping`'s JSON-Schema
 * via the `definition` "evidence_source_id".
 */
export type EvidenceSourceId =
  | "catalog_ownership"
  | "audit_chain"
  | "hitl_decisions"
  | "evaluation_results"
  | "cost_attribution"
  | "configuration_findings";
/**
 * @maxItems 6
 *
 * This interface was referenced by `ControlMapping`'s JSON-Schema
 * via the `definition` "evidence_sources".
 */
export type EvidenceSources = EvidenceSourceId[];

/**
 * How NeuroSphere relates to one control (PRP-56). support_status reuses the PRP-23 vocabulary (designed, implemented_tested, inherited, customer, planned, not_applicable); evidence_sources names the read-only sources whose observations are relevant to the control. designed and implemented_tested support must cite repo_paths that exist (checked by the library loader). The mapping collects and maps; it never judges.
 */
export interface ControlMapping {
  schema_version: string;
  control_id: string;
  /**
   * External framework a control belongs to. Open-ended: readers must tolerate unknown values.
   */
  framework_id:
    | "nist_ai_rmf"
    | "sr_11_7"
    | "hipaa_technical_safeguards"
    | "omb_m_25_21"
    | "soc2_tsc"
    | "iso_27001_annex_a"
    | "gdpr"
    | "nist_800_53_r5"
    | "eu_ai_act"
    | "iso_42001";
  support_status: SupportStatus;
  evidence_sources: EvidenceSources;
  /**
   * @maxItems 20
   */
  repo_paths: string[];
}
