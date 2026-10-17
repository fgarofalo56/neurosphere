// Manifest builder and validator over the PRP-01 ConnectorManifest contract.
//
// The type comes from @neurosphere/contracts and is never redefined. Validation runs the
// contract's JSON Schema (including its if/then rules) through Ajv, then the cross-field rules
// the schema description names, mirroring neurosphere_connector.manifest.manifest_issues.
// Issues carry a JSON pointer and a value-free message.

import type { ConnectorManifest } from "@neurosphere/contracts";
import { Ajv2020 } from "ajv/dist/2020.js";
import schema from "../../../packages/contracts/schemas/connectors/v1/connector-manifest.schema.json";

import { InvalidManifestError, type ManifestIssue } from "./errors.js";

type CredentialRef = ConnectorManifest["credential_refs"][number];
type RateLimit = NonNullable<ConnectorManifest["rate_limits"]>[number];
export type Capability = ConnectorManifest["capabilities"][number];
export type Cloud = ConnectorManifest["supported_clouds"][number];
export type Granularity = ConnectorManifest["granularity"];
export type Freshness = ConnectorManifest["freshness"];

const VAULT_HOST_CLOUD: Readonly<Record<string, Cloud>> = {
  "vault.azure.net": "commercial",
  "vault.usgovcloudapi.net": "government",
};

const ajv = new Ajv2020({ allErrors: true, strict: true, strictTypes: false });
const validateSchema = ajv.compile(schema);

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function crossFieldIssues(m: ConnectorManifest): ManifestIssue[] {
  const issues: ManifestIssue[] = [];
  const refs = m.credential_refs;
  if (m.auth_mode === "vault_reference" && refs.length === 0) {
    issues.push({ pointer: "/credential_refs", detail: "vault_reference requires a ref" });
  }
  if (m.auth_mode !== "vault_reference" && refs.length > 0) {
    issues.push({ pointer: "/credential_refs", detail: "only vault_reference carries refs" });
  }
  refs.forEach((ref, i) => {
    if (refs.findIndex((r) => r.name === ref.name) !== i) {
      issues.push({ pointer: `/credential_refs/${i}/name`, detail: "duplicate name" });
    }
  });
  const clouds = new Set<string>(m.supported_clouds);
  refs.forEach((ref, i) => {
    const host = ref.vault_ref.replace(/^https:\/\//, "").split("/", 1)[0] ?? "";
    const cloud = Object.entries(VAULT_HOST_CLOUD).find(([suffix]) =>
      host.endsWith(`.${suffix}`),
    )?.[1];
    if (cloud === undefined || !clouds.has(cloud)) {
      issues.push({
        pointer: `/credential_refs/${i}/vault_ref`,
        detail: "vault host not in a listed cloud",
      });
    }
  });
  const ws = m.write_support;
  if (ws.supported && ws.actions.length === 0) {
    issues.push({ pointer: "/write_support/actions", detail: "supported requires an action" });
  }
  if (!ws.supported && ws.actions.length > 0) {
    issues.push({ pointer: "/write_support/actions", detail: "must be empty when unsupported" });
  }
  if (new Set(ws.actions).size !== ws.actions.length) {
    issues.push({ pointer: "/write_support/actions", detail: "actions must be unique" });
  }
  if (m.advisory === ws.supported) {
    issues.push({ pointer: "/advisory", detail: "advisory must be true iff write is unsupported" });
  }
  if (m.capabilities.includes("action_execution") !== ws.supported) {
    issues.push({
      pointer: "/capabilities",
      detail: "action_execution iff write_support.supported",
    });
  }
  return issues;
}

/** Every contract violation for a manifest object or JSON text (empty array means valid). */
export function manifestIssues(data: unknown): ManifestIssue[] {
  let parsed: unknown = data;
  if (typeof data === "string") {
    try {
      parsed = JSON.parse(data);
    } catch {
      return [{ pointer: "", detail: "document is not valid JSON" }];
    }
  }
  if (!isRecord(parsed)) {
    return [{ pointer: "", detail: "document must be a JSON object" }];
  }
  if (!validateSchema(parsed)) {
    // Ajv messages are keyword-based ("must be equal to one of the allowed values"); the
    // offending data lives in params/data, which are deliberately not copied.
    return (validateSchema.errors ?? []).map((e) => ({
      pointer: e.instancePath,
      detail: e.message ?? e.keyword,
    }));
  }
  return crossFieldIssues(parsed as unknown as ConnectorManifest);
}

/** Return the validated manifest or throw InvalidManifestError listing the issues. */
export function validateManifest(data: unknown): ConnectorManifest {
  const issues = manifestIssues(data);
  if (issues.length > 0) {
    throw new InvalidManifestError(issues);
  }
  return (typeof data === "string" ? JSON.parse(data) : data) as ConnectorManifest;
}

export interface BuildManifestOptions {
  name: string;
  version: string;
  capabilities: readonly Exclude<Capability, "action_execution">[];
  supportedClouds: readonly Cloud[];
  granularity: Granularity;
  freshness?: Freshness;
  scopes?: readonly string[];
  /** Omit for unknown (null); pass [] when the source publishes no limits. */
  rateLimits?: readonly RateLimit[];
  credentialRefs?: readonly CredentialRef[];
  documentationUrl?: string;
  authMode?: ConnectorManifest["auth_mode"];
  schemaVersion?: string;
}

/**
 * Assemble and validate a read-only manifest. Derives auth mode and the advisory/write_support
 * block (always advisory: this SDK has no write surface). Unknown freshness is null/null and
 * unknown rate limits stay null, never 0.
 */
export function buildManifest(options: BuildManifestOptions): ConnectorManifest {
  const refs = [...(options.credentialRefs ?? [])];
  const doc = {
    schema_version: options.schemaVersion ?? "1.0.0",
    name: options.name,
    version: options.version,
    supported_clouds: [...options.supportedClouds],
    capabilities: [...options.capabilities],
    scopes: [...(options.scopes ?? [])],
    granularity: { ...options.granularity },
    freshness: options.freshness
      ? { ...options.freshness }
      : { typical_delay_ms: null, max_delay_ms: null },
    rate_limits: options.rateLimits ? options.rateLimits.map((r) => ({ ...r })) : null,
    auth_mode: options.authMode ?? (refs.length > 0 ? "vault_reference" : "managed_identity"),
    credential_refs: refs.map((r) => ({ ...r })),
    advisory: true,
    write_support: { supported: false, actions: [] },
    ...(options.documentationUrl === undefined
      ? {}
      : { documentation_url: options.documentationUrl }),
  };
  return validateManifest(doc);
}
