/*
 * GENERATED - do not edit.
 * Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
 * Regenerate: python packages/contracts/scripts/generate.py
 * Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
 */

/**
 * @maxItems 6
 */
export type EvidenceSources = (
  | "catalog_ownership"
  | "audit_chain"
  | "hitl_decisions"
  | "evaluation_results"
  | "cost_attribution"
  | "configuration_findings"
)[];

/**
 * Deterministic, stateless evidence bundle for one domain and one framework (PRP-56). Per-control summary words (evidence_present, evidence_partial, no_evidence, customer_responsibility) derive only from observations and support status. There is no pass, fail, score or percentage. digest is sha256 over the canonical JSON of the bundle without the digest member. This bundle is not an assessment; not FedRAMP authorized; the authorizing official decides.
 */
export interface EvidenceBundle {
  /**
   * This interface was referenced by `Control`'s JSON-Schema
   * via the `definition` "schema_version".
   */
  schema_version: string;
  /**
   * External framework a control belongs to. Open-ended: readers must tolerate unknown values.
   *
   * This interface was referenced by `Control`'s JSON-Schema
   * via the `definition` "framework_id".
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
  framework_version: string;
  library_version: string;
  domain_id: string;
  /**
   * This interface was referenced by `EvidenceObservation`'s JSON-Schema
   * via the `definition` "utc_timestamp".
   */
  generated_at: string;
  /**
   * This interface was referenced by `EvidenceObservation`'s JSON-Schema
   * via the `definition` "utc_timestamp".
   */
  window_start: string;
  /**
   * This interface was referenced by `EvidenceObservation`'s JSON-Schema
   * via the `definition` "utc_timestamp".
   */
  window_end: string;
  /**
   * @maxItems 200
   */
  controls: ControlSummary[];
  /**
   * @maxItems 6
   */
  observations: EvidenceObservation[];
  digest: string;
}
/**
 * This interface was referenced by `EvidenceBundle`'s JSON-Schema
 * via the `definition` "control_summary".
 */
export interface ControlSummary {
  control: Control;
  support_status:
    "designed" | "implemented_tested" | "inherited" | "customer" | "planned" | "not_applicable";
  evidence_sources: EvidenceSources;
  summary: "evidence_present" | "evidence_partial" | "no_evidence" | "customer_responsibility";
}
/**
 * One control of an external framework held as library data (PRP-56). Metadata only: a short paraphrased title and a link to the official source, never copied text. A control record says what the framework names; it never says whether anyone meets it.
 */
export interface Control {
  /**
   * This interface was referenced by `Control`'s JSON-Schema
   * via the `definition` "schema_version".
   */
  schema_version: string;
  /**
   * Stable NeuroSphere control id (lowercase, dot separated). Other PRPs cite it.
   */
  control_id: string;
  /**
   * External framework a control belongs to. Open-ended: readers must tolerate unknown values.
   *
   * This interface was referenced by `Control`'s JSON-Schema
   * via the `definition` "framework_id".
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
  title: string;
  source_url: string;
  /**
   * Date the control id and title were read from the official source.
   */
  source_retrieved: string;
  framework_version: string;
}
/**
 * What one read-only evidence source saw for a domain in a window (PRP-56). Counts, timestamps and ids only: no entity bodies, no prompts, no principal names. status: observed (the source answered), partial (answered with a cap or a gap), unavailable (store missing or down; reason_code says why), not_collected (the source cannot count this). Unknown numbers are null, never 0.
 */
export interface EvidenceObservation {
  /**
   * This interface was referenced by `Control`'s JSON-Schema
   * via the `definition` "schema_version".
   */
  schema_version: string;
  source_id:
    | "catalog_ownership"
    | "audit_chain"
    | "hitl_decisions"
    | "evaluation_results"
    | "cost_attribution"
    | "configuration_findings";
  status: "observed" | "partial" | "unavailable" | "not_collected";
  /**
   * snake_case machine reason; null when status is observed.
   */
  reason_code: string | null;
  /**
   * This interface was referenced by `EvidenceObservation`'s JSON-Schema
   * via the `definition` "utc_timestamp".
   */
  window_start: string;
  /**
   * This interface was referenced by `EvidenceObservation`'s JSON-Schema
   * via the `definition` "utc_timestamp".
   */
  window_end: string;
  /**
   * Newest timestamp the source saw; null when none or unknown.
   */
  latest_at: string | null;
  truncated: boolean;
  /**
   * @maxItems 20
   */
  measures: {
    name: string;
    value: number | null;
  }[];
}
