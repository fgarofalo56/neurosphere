/*
 * GENERATED - do not edit.
 * Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
 * Regenerate: python packages/contracts/scripts/generate.py
 * Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
 */

/**
 * Semantic version of this document within major 1. Within v1 only additive, optional changes are allowed (ADR-0004).
 *
 * This interface was referenced by `IdentityScope`'s JSON-Schema
 * via the `definition` "schema_version".
 */
export type SchemaVersion = string;
/**
 * Canonical ID cloud:customer:source:type:id (PRP-01 clarification 7). Grammar owned by schemas/catalog/v1; duplicated here as a pattern so this schema has no cross-area dependency.
 *
 * This interface was referenced by `IdentityScope`'s JSON-Schema
 * via the `definition` "canonical_id".
 */
export type CanonicalId = string;
/**
 * RFC 3339 timestamp in UTC (Z suffix required).
 *
 * This interface was referenced by `IdentityScope`'s JSON-Schema
 * via the `definition` "timestamp".
 */
export type Timestamp = string;

/**
 * OUTPUT-ONLY. The server-derived authorization scope of one principal, computed from a validated identity token and the current policy store. It is never accepted from a caller or a model: no request schema may $ref this schema (asserted by tests/contracts/test_scope_isolation.py), and caller- or model-supplied domain_id/customer_id values are ignored for authorization. The same object is passed to REST, graph, analytics, search, cache keys, exports, WebSocket, copilot tools and MCP. There is deliberately no wildcard, all-domains or bypass field: privileged roles are scoped to explicit domains and time-bound. scope_hash correctness (sha256 over the canonical JSON of cloud, customer_id, principal.principal_id, roles, allowed_domains, allowed_resources and policy_version, keys sorted, no whitespace) cannot be expressed in JSON Schema and is checked by tests/contracts/validators.py::check_identity_scope_hash. expires_at > derived_at is checked by tests/contracts/validators.py::check_identity_scope_times.
 */
export interface IdentityScope {
  schema_version: SchemaVersion;
  /**
   * The single cloud this scope is valid in. A scope never spans commercial and government.
   */
  cloud: "commercial" | "government";
  /**
   * Customer segment of the canonical ID grammar, taken from the validated token's tenant mapping, never from request input.
   */
  customer_id: string;
  principal: Principal;
  /**
   * @maxItems 64
   */
  roles: RoleAssignment[];
  /**
   * Explicit canonical Domain IDs the principal may read. Empty means no domain access. No wildcard form exists.
   *
   * @maxItems 1024
   */
  allowed_domains: CanonicalId[];
  /**
   * Resource-scoped grants (custom resource-scoped permissions, NS-08) outside or narrower than domain grants.
   *
   * @maxItems 4096
   */
  allowed_resources: ResourceGrant[];
  /**
   * Version of the policy store snapshot the scope was derived from; a newer policy version invalidates cached scopes.
   */
  policy_version: string;
  derived_at: Timestamp;
  /**
   * RFC 3339 timestamp in UTC (Z suffix required).
   */
  expires_at?: string;
  /**
   * sha256 over the canonical JSON of the scope-defining fields (see schema description). Used in cache keys and audit records.
   */
  scope_hash: string;
}
/**
 * Pseudonymous principal (PRP-01 clarification 8). No name, email or other direct identifier.
 *
 * This interface was referenced by `IdentityScope`'s JSON-Schema
 * via the `definition` "principal".
 */
export interface Principal {
  principal_id: CanonicalId;
  /**
   * Stable pseudonym; re-identification is a policy-store concern, not a contract field.
   */
  principal_pseudonym: string;
  principal_kind: "user" | "service_principal" | "managed_identity" | "agent";
}
/**
 * One role bound to explicit domains (NS-08 roles). Privileged roles (admin, security_auditor) must carry expires_at: privileged access is scoped and time-bound. expires_at > derived_at is checked by tests/contracts/validators.py::check_identity_scope_times.
 *
 * This interface was referenced by `IdentityScope`'s JSON-Schema
 * via the `definition` "role_assignment".
 */
export interface RoleAssignment {
  role: "viewer" | "analyst" | "domain_steward" | "admin" | "security_auditor";
  /**
   * Domains this role applies to. At least one; there is no tenant-wide form.
   *
   * @minItems 1
   * @maxItems 1024
   */
  domain_ids: [CanonicalId, ...CanonicalId[]];
  expires_at?: Timestamp;
}
/**
 * This interface was referenced by `IdentityScope`'s JSON-Schema
 * via the `definition` "resource_grant".
 */
export interface ResourceGrant {
  resource_id: CanonicalId;
  /**
   * @minItems 1
   */
  permissions: [
    "read" | "export" | "propose_action" | "approve" | "execute",
    ...("read" | "export" | "propose_action" | "approve" | "execute")[],
  ];
  expires_at?: Timestamp;
}
