/*
 * GENERATED - do not edit.
 * Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
 * Regenerate: python packages/contracts/scripts/generate.py
 * Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
 */

/**
 * How a policy or enforcement point acts: off (not evaluated), audit (evaluated and recorded, never blocks; the default, GD-7) or enforce (blocks). Enforce is set only by an approved action.
 */
export type EnforcementMode = "off" | "audit" | "enforce";
/**
 * How serious a violation of the policy or rule is.
 *
 * This interface was referenced by `PolicyDefinition`'s JSON-Schema
 * via the `definition` "severity".
 */
export type PolicySeverity = "low" | "medium" | "high" | "critical";
/**
 * Closed typed rule kind that selects the parameter object; open-ended: readers must tolerate unknown values (PRP-110 adds identity_entitlement).
 *
 * This interface was referenced by `PolicyDefinition`'s JSON-Schema
 * via the `definition` "rule_kind".
 */
export type PolicyRuleKind =
  | "model_allow_list"
  | "data_sensitivity_access"
  | "residency"
  | "budget"
  | "required_owner"
  | "required_attestation"
  | "required_approval"
  | "content_rule"
  | "registration_required";
/**
 * Canonical ID grammar cloud:customer:source:type:id. cloud is commercial or government; customer, source and type are lowercase [a-z0-9._-]; id is lowercase [a-z0-9._-] plus '/' and '='; no segment may contain ':'. Corpus: id-corpus.json. Python validator validate_canonical_id_fullmatch re-checks with re.fullmatch because Python re.search lets '$' match before a trailing newline.
 */
export type CanonicalId = string;
/**
 * Kind of sensitive content a detector found; open-ended: readers must tolerate unknown values. The first eight are credential categories (CredentialCategory).
 */
export type DetectedCategory =
  | "private_key"
  | "jwt"
  | "bearer_token"
  | "cloud_access_key"
  | "vendor_api_key"
  | "connection_string"
  | "url_with_credentials"
  | "password_assignment"
  | "payment_card"
  | "iban"
  | "us_ssn"
  | "email_address"
  | "phone_number"
  | "ip_address"
  | "mac_address"
  | "guid"
  | "customer_dictionary_term"
  | "customer_identifier_pattern"
  | "other";
/**
 * Which part of an interaction a piece of content is.
 */
export type ContentPartKind =
  "prompt" | "response" | "tool_input" | "tool_output" | "system_instructions";
/**
 * How a policy or enforcement point acts: off (not evaluated), audit (evaluated and recorded, never blocks; the default, GD-7) or enforce (blocks). Enforce is set only by an approved action.
 *
 * This interface was referenced by `PolicyDefinition`'s JSON-Schema
 * via the `definition` "enforcement_mode".
 */
export type EnforcementMode1 = "off" | "audit" | "enforce";

/**
 * A governance policy as typed rules (PRP-99; container policy_definitions, declared by PRP-102). Rules are closed typed kinds with parameter objects: no expression, code, query or free-text condition exists, by decision (PRP-99 clarification 4). Mode defaults to audit (GD-7). The kind-to-params pin and the published-requires-publish-evidence rule are JSON Schema if/then that Pydantic ignores (ADR-0004), so consumers validate against the JSON Schema.
 */
export interface PolicyDefinition {
  /**
   * Contract version of the document; major 1 for every catalog v1 schema.
   */
  schema_version: string;
  /**
   * Policy id (slug).
   */
  policy_id: string;
  /**
   * Increments on every change.
   */
  policy_version: number;
  /**
   * Version this one replaces. Null for the first.
   */
  previous_version?: number | null;
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
   * Human-readable label shown in the console. Not an identity attribute: never a person's name, UPN or email.
   */
  display_name: string;
  /**
   * Link to the source policy document. Null when none.
   */
  document_url?: string | null;
  status: "draft" | "published" | "retired";
  mode?: EnforcementMode;
  severity: PolicySeverity;
  /**
   * One to 32 typed rules.
   *
   * @minItems 1
   * @maxItems 32
   */
  rules: [PolicyRule, ...PolicyRule[]];
  /**
   * Digest of the canonical rules, so a published version cannot change silently.
   */
  content_sha256: string;
  /**
   * Canonical pseudonymous principal id minted by the PRP-06 pseudonymizer: cloud:customer:entra:(person|principal):p-<64 hex>. Never a UPN, email address or raw directory object id.
   */
  created_by: string;
  /**
   * RFC 3339 timestamp in UTC (Z suffix required; no offsets).
   */
  created_at: string;
  /**
   * When published. Required when status is published.
   */
  published_at?: string | null;
  /**
   * Approved publish intent.
   */
  published_intent_id?: string | null;
  /**
   * Audit record of the publish.
   */
  published_audit_id?: string | null;
}
/**
 * One typed rule. params is pinned by kind (anyOf plus allOf if/then, the AdminConfigDocument pattern); core validates it again because the generated Pydantic model cannot express the per-kind rule (ADR-0004). There is no expression, code, query or free-text condition field.
 *
 * This interface was referenced by `PolicyDefinition`'s JSON-Schema
 * via the `definition` "rule".
 */
export interface PolicyRule {
  /**
   * Lowercase operator-chosen identifier.
   */
  rule_id: string;
  kind: PolicyRuleKind;
  /**
   * Overrides the policy severity. Null uses the policy's.
   */
  severity?: PolicySeverity | null;
  applies_to?: PolicyAppliesTo;
  /**
   * The kind's parameter object; allOf below pins which one.
   */
  params:
    | ModelAllowListParams
    | DataSensitivityAccessParams
    | ResidencyParams
    | BudgetRuleParams
    | RequiredOwnerParams
    | RequiredAttestationParams
    | RequiredApprovalParams
    | ContentRuleParams
    | RegistrationRequiredParams;
}
/**
 * Which entities a rule covers inside the domain. Every list defaults to empty, and all-empty means every entity in the domain.
 */
export interface PolicyAppliesTo {
  /**
   * Catalog entity types.
   *
   * @maxItems 8
   */
  entity_types?: string[];
  /**
   * Catalog tags.
   *
   * @maxItems 16
   *
   * Items: Lowercase label token used for grouping and filtering catalog entities.
   */
  tags?: string[];
  /**
   * Deployment environments.
   *
   * @maxItems 6
   *
   * Items: Deployment environment; the same vocabulary as TelemetryEvent.environment.
   */
  environments?: ("production" | "staging" | "development" | "test" | "sandbox" | "unknown")[];
  /**
   * Specific entities by canonical id.
   *
   * @maxItems 64
   */
  entity_ids?: CanonicalId[];
}
/**
 * Only the listed models or deployments may be used.
 *
 * This interface was referenced by `PolicyDefinition`'s JSON-Schema
 * via the `definition` "model_allow_list_params".
 */
export interface ModelAllowListParams {
  /**
   * Allowed model names and versions.
   *
   * @maxItems 64
   */
  allowed_models?: {
    model_name: string;
    /**
     * Null means any version.
     */
    model_version?: string | null;
  }[];
  /**
   * Allowed model deployments by canonical id.
   *
   * @maxItems 64
   */
  allowed_deployment_ids?: CanonicalId[];
}
/**
 * Access to data of the listed sensitivity categories needs an approved agent version or an exception.
 *
 * This interface was referenced by `PolicyDefinition`'s JSON-Schema
 * via the `definition` "data_sensitivity_access_params".
 */
export interface DataSensitivityAccessParams {
  /**
   * @minItems 1
   * @maxItems 10
   *
   * Items: Kind of sensitive data a data asset holds; sits beside classification, not instead of it. Open-ended: readers must tolerate unknown values.
   */
  sensitivity_categories: [
    (
      | "pii"
      | "phi"
      | "cui"
      | "pci"
      | "financial"
      | "biometric"
      | "credentials"
      | "export_controlled"
      | "legal_privileged"
      | "other"
    ),
    ...(
      | "pii"
      | "phi"
      | "cui"
      | "pci"
      | "financial"
      | "biometric"
      | "credentials"
      | "export_controlled"
      | "legal_privileged"
      | "other"
    )[],
  ];
  access: "read" | "write" | "read_or_write";
  allowed_when: "agent_version_approved" | "exception_only";
}
/**
 * Data and calls stay inside the listed geographies and regions.
 *
 * This interface was referenced by `PolicyDefinition`'s JSON-Schema
 * via the `definition` "residency_params".
 */
export interface ResidencyParams {
  /**
   * Coarse geographies.
   *
   * @maxItems 16
   *
   * Items: Coarse geography of the data's authoritative copy; complements residency_region. Open-ended: readers must tolerate unknown values.
   */
  allowed_geographies?: (
    | "eu_eea"
    | "uk"
    | "switzerland"
    | "united_states"
    | "canada"
    | "asia_pacific"
    | "latin_america"
    | "middle_east_africa"
    | "other"
  )[];
  /**
   * Provider region tokens.
   *
   * @maxItems 64
   *
   * Items: Lowercase identifier token (source IDs, platforms, providers, kinds).
   */
  allowed_regions?: string[];
}
/**
 * A budget record crossing a percentage of its limit.
 *
 * This interface was referenced by `PolicyDefinition`'s JSON-Schema
 * via the `definition` "budget_rule_params".
 */
export interface BudgetRuleParams {
  /**
   * Identifier of a record inside a policy or configuration document (assignment, grant, budget, item).
   */
  budget_record_id: string;
  threshold_percent: number;
  on_breach: "alert" | "propose_cap_change";
}
/**
 * The entity needs owners.
 *
 * This interface was referenced by `PolicyDefinition`'s JSON-Schema
 * via the `definition` "required_owner_params".
 */
export interface RequiredOwnerParams {
  min_owners?: number;
  require_active_owner?: boolean;
}
/**
 * A recent attestation of the given kind is required.
 *
 * This interface was referenced by `PolicyDefinition`'s JSON-Schema
 * via the `definition` "required_attestation_params".
 */
export interface RequiredAttestationParams {
  attestation_kind: "owner_recertification" | "agent_attestation";
  max_age_days: number;
}
/**
 * The entity version needs an approval before it is active.
 *
 * This interface was referenced by `PolicyDefinition`'s JSON-Schema
 * via the `definition` "required_approval_params".
 */
export interface RequiredApprovalParams {
  /**
   * Entity types that need approval: `agent_version` today. Open-ended: readers must tolerate unknown values.
   *
   * @minItems 1
   * @maxItems 8
   */
  entity_types?: [string, ...string[]];
  block_activation?: boolean;
}
/**
 * Captured interactions whose findings include the listed categories, counted from interaction metadata (never content).
 *
 * This interface was referenced by `PolicyDefinition`'s JSON-Schema
 * via the `definition` "content_rule_params".
 */
export interface ContentRuleParams {
  /**
   * @minItems 1
   * @maxItems 16
   */
  detected_categories: [DetectedCategory, ...DetectedCategory[]];
  min_count?: number;
  /**
   * Content parts to count; empty means all.
   *
   * @maxItems 5
   */
  parts?: ContentPartKind[];
  window_minutes?: number;
}
/**
 * Entities seen in telemetry must be registered in the catalog within the grace period.
 *
 * This interface was referenced by `PolicyDefinition`'s JSON-Schema
 * via the `definition` "registration_required_params".
 */
export interface RegistrationRequiredParams {
  /**
   * @minItems 1
   * @maxItems 5
   */
  entity_types: [
    "agent" | "tool" | "model_deployment" | "mcp_server" | "service",
    ...("agent" | "tool" | "model_deployment" | "mcp_server" | "service")[],
  ];
  grace_period_hours?: number;
}
/**
 * Which entities a rule covers inside the domain. Every list defaults to empty, and all-empty means every entity in the domain.
 *
 * This interface was referenced by `PolicyDefinition`'s JSON-Schema
 * via the `definition` "applies_to".
 */
export interface PolicyAppliesTo1 {
  /**
   * Catalog entity types.
   *
   * @maxItems 8
   */
  entity_types?: string[];
  /**
   * Catalog tags.
   *
   * @maxItems 16
   *
   * Items: Lowercase label token used for grouping and filtering catalog entities.
   */
  tags?: string[];
  /**
   * Deployment environments.
   *
   * @maxItems 6
   *
   * Items: Deployment environment; the same vocabulary as TelemetryEvent.environment.
   */
  environments?: ("production" | "staging" | "development" | "test" | "sandbox" | "unknown")[];
  /**
   * Specific entities by canonical id.
   *
   * @maxItems 64
   */
  entity_ids?: CanonicalId[];
}
