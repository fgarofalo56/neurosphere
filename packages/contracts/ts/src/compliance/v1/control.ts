/*
 * GENERATED - do not edit.
 * Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
 * Regenerate: python packages/contracts/scripts/generate.py
 * Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
 */

/**
 * This interface was referenced by `Control`'s JSON-Schema
 * via the `definition` "schema_version".
 */
export type SchemaVersion = string;
/**
 * External framework a control belongs to. Open-ended: readers must tolerate unknown values.
 *
 * This interface was referenced by `Control`'s JSON-Schema
 * via the `definition` "framework_id".
 */
export type FrameworkId =
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

/**
 * One control of an external framework held as library data (PRP-56). Metadata only: a short paraphrased title and a link to the official source, never copied text. A control record says what the framework names; it never says whether anyone meets it.
 */
export interface Control {
  schema_version: SchemaVersion;
  /**
   * Stable NeuroSphere control id (lowercase, dot separated). Other PRPs cite it.
   */
  control_id: string;
  framework_id: FrameworkId;
  title: string;
  source_url: string;
  /**
   * Date the control id and title were read from the official source.
   */
  source_retrieved: string;
  framework_version: string;
}
