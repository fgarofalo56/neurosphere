/*
 * GENERATED - do not edit.
 * Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
 * Regenerate: python packages/contracts/scripts/generate.py
 * Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
 */

/**
 * A versioned framework and the controls the library names for it (PRP-56). Held as data under neurosphere_core/compliance/library. Naming a framework here is not a claim that anything is supported or covered; use 'mapped controls' and 'evidence observed'.
 */
export interface ControlFramework {
  /**
   * This interface was referenced by `Control`'s JSON-Schema
   * via the `definition` "schema_version".
   */
  schema_version: string;
  /**
   * This interface was referenced by `Control`'s JSON-Schema
   * via the `definition` "framework_id".
   */
  framework_id: "nist_ai_rmf" | "sr_11_7" | "hipaa_technical_safeguards" | "omb_m_25_21";
  title: string;
  framework_version: string;
  source_url: string;
  source_retrieved: string;
  /**
   * @minItems 1
   * @maxItems 200
   */
  controls: [Control, ...Control[]];
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
   * This interface was referenced by `Control`'s JSON-Schema
   * via the `definition` "framework_id".
   */
  framework_id: "nist_ai_rmf" | "sr_11_7" | "hipaa_technical_safeguards" | "omb_m_25_21";
  title: string;
  source_url: string;
  /**
   * Date the control id and title were read from the official source.
   */
  source_retrieved: string;
  framework_version: string;
}
