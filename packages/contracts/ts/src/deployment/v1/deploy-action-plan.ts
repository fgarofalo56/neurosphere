/*
 * GENERATED - do not edit.
 * Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
 * Regenerate: python packages/contracts/scripts/generate.py
 * Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
 */

/**
 * Executable snapshot of an approved deployment plan, carried by the `deploy_plan_apply` action kind (PRP-08 item 12). The API derives it from the approved plan; its resource list is written into the ActionIntent proposed_diff (`add /resources/<service>` operations next to `test /plan_hash` and `test /resources_digest`), so the maker confirms and the approver decides on the exact set of resources. plan_hash is the SHA-256 of the canonical plan the approver approved; the executor refuses an apply whose plan is not approved or whose hash differs. Uninstall (`deploy_uninstall`) is dry-run only and carries no resource list. Contains no credential, secret or principal e-mail.
 */
export interface DeployActionPlan {
  /**
   * Contract version of this document (semver within major 1).
   */
  schema_version: string;
  /**
   * Identifier of the approved plan.
   */
  plan_id: string;
  /**
   * Lowercase hex SHA-256 digest with algorithm prefix of the approved plan.
   */
  plan_hash: string;
  /**
   * Deployment the plan belongs to (ownership register key).
   */
  deployment_id: string;
  /**
   * Azure cloud of the deployment. Never routed to the other cloud.
   */
  cloud: "commercial" | "government";
  /**
   * Resources to create or reuse, in apply order.
   *
   * @maxItems 64
   */
  resources: ResourceSpec[];
}
/**
 * One resource the apply creates or reuses. Reused resources are only recorded in the ownership register, never modified.
 *
 * This interface was referenced by `DeployActionPlan`'s JSON-Schema
 * via the `definition` "resource_spec".
 */
export interface ResourceSpec {
  /**
   * Manifest service key, lowercase snake_case (for example `analytics_workspace`).
   */
  service: string;
  /**
   * Provisioning path: Fabric capacity (ARM), Fabric workspace (Fabric REST) or another ARM resource.
   */
  kind: "fabric_capacity" | "fabric_workspace" | "arm_resource";
  disposition: "create" | "reuse";
  /**
   * Resource or display name.
   */
  name: string;
  /**
   * Lowercase ARM region name.
   */
  region: string;
  sku: string | null;
  /**
   * ARM resource id of the resource being reused; null when it is created.
   */
  resource_id: string | null;
  subscription_id: string | null;
  resource_group: string | null;
  /**
   * Owner consent reference; required for a reused resource, null otherwise.
   */
  consent_reference: string | null;
}
