/*
 * GENERATED - do not edit.
 * Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
 * Regenerate: python packages/contracts/scripts/generate.py
 * Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
 */

/**
 * Where a decision is enforced; open-ended: readers must tolerate unknown values.
 *
 * This interface was referenced by `EnforcementBinding`'s JSON-Schema
 * via the `definition` "enforcement_point".
 */
export type EnforcementPoint =
  "gateway" | "tool_call" | "mcp_server" | "mcp_client" | "sdk" | "budget" | "registration";
/**
 * How a policy or enforcement point acts: off (not evaluated), audit (evaluated and recorded, never blocks; the default, GD-7) or enforce (blocks). Enforce is set only by an approved action.
 */
export type EnforcementMode = "off" | "audit" | "enforce";

/**
 * Binds a policy to an enforcement point and a mode (PRP-99; body of admin_kind enforcement_binding). mode defaults to audit (GD-7); enforce is set only by an approved enforcement_mode_change action. A null target means every target of that point in the domain.
 */
export interface EnforcementBinding {
  /**
   * Contract version of the document; major 1 for every catalog v1 schema.
   */
  schema_version: string;
  /**
   * Binding id (slug).
   */
  binding_id: string;
  /**
   * Sovereign cloud boundary. Government data is never bridged to Commercial.
   */
  cloud: "commercial" | "government";
  /**
   * Customer segment of the canonical ID grammar.
   */
  customer_id: string;
  /**
   * Owning domain; authorization scope anchor. Canonical ID (canonical_id.schema.json) whose type segment is 'domain'.
   */
  domain_id: string;
  /**
   * Lowercase operator-chosen identifier.
   */
  policy_id: string;
  point: EnforcementPoint;
  /**
   * Specific target; null = every target of the point in the domain.
   */
  target?: TargetRef | null;
  mode?: EnforcementMode;
  /**
   * pending: not yet applied. applied: verified. failed: apply failed. drifted: verified state changed. not_supported: the point cannot enforce here.
   */
  state: "pending" | "applied" | "failed" | "drifted" | "not_supported";
  /**
   * Last action intent that changed this binding.
   */
  last_intent_id?: string | null;
  /**
   * Audit record of that change.
   */
  last_audit_id?: string | null;
  /**
   * When the applied state was last read back.
   */
  last_verified_at?: string | null;
}
/**
 * Reference to the resource an action changes or an audit record concerns. `canonical_id` uses the catalog grammar `cloud:customer:source:type:id` (Clarification 7); the pattern here mirrors it and the catalog/v1 grammar is authoritative. Python validator `validate_target_ref_matches_catalog_grammar` in tests/contracts/test_canonical_ids.py checks this pattern against the catalog ID corpus so the two cannot drift. The version being acted on is carried beside this object (ActionIntent.target_version), not inside it, so it is hashed as its own field.
 */
export interface TargetRef {
  /**
   * Cloud/customer/source qualified canonical ID of the target.
   */
  canonical_id: string;
  /**
   * Catalog entity type of the target, lowercase snake_case (for example `model_deployment`, `agent_version`).
   */
  entity_type: string;
}
