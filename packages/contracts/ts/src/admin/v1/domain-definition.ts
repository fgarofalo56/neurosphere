/*
 * GENERATED - do not edit.
 * Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
 * Regenerate: python packages/contracts/scripts/generate.py
 * Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
 */

/**
 * Operator definition of one domain (PRP-44): the authorization scope anchor every role, grant, connector and budget names. residency_region is the ARM region the domain's data is held in (Government domains use usgov* /usdod* regions; data is never bridged across clouds). The control domain is the reserved per-customer domain that holds platform configuration actions; at most one exists per customer (checked by the PRP-44 handler). A retired domain keeps its id for audit and accepts no new data.
 */
export interface DomainDefinition {
  /**
   * Contract version of the document, major 1 with additive minor revisions (ADR-0004).
   */
  schema_version: string;
  /**
   * Canonical Domain id (type segment 'domain'). No wildcard or all-domains form exists.
   */
  domain_id: string;
  /**
   * Human-readable label shown in the console. Not an identity attribute: never a person's name, UPN or email.
   */
  display_name: string;
  /**
   * Data classification label (catalog/v1 classification vocabulary).
   */
  classification: "public" | "internal" | "confidential" | "restricted" | "unknown";
  /**
   * Lowercase ARM region name (eastus2, usgovvirginia).
   */
  residency_region: string;
  status: "active" | "retired";
  is_control_domain: boolean;
}
