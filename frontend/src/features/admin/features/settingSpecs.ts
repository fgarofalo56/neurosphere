import {
  EMPTY_CREDENTIAL,
  credentialProblem,
  fromReference,
  toReference,
  type CredentialDraft,
} from "../sources/credentialReference";
import type { CredentialReference } from "../sources/types";

export type SettingKey = "copilot" | "judge" | "search" | "scan" | "mcp_server" | "write_targets";

export const SETTING_KEYS: readonly SettingKey[] = [
  "copilot",
  "judge",
  "search",
  "scan",
  "mcp_server",
  "write_targets",
];

export interface FieldSpec {
  readonly name: string;
  readonly label: string;
  readonly kind: "text" | "number" | "lines";
  readonly required: boolean;
  readonly hint?: string;
}

export interface SettingSpec {
  readonly key: SettingKey;
  readonly title: string;
  readonly description: string;
  /** The member of the stored body that holds these fields. */
  readonly member: string;
  readonly fields: readonly FieldSpec[];
  /** managed_identity: the runtime calls the model with an identity; optional: none allowed. */
  readonly credential: "managed_identity" | "any" | "optional";
}

const RESOURCE: FieldSpec = {
  name: "resource_id",
  label: "Azure resource id (optional)",
  kind: "text",
  required: false,
};

export const SETTING_SPECS: Readonly<Record<Exclude<SettingKey, "write_targets">, SettingSpec>> = {
  copilot: {
    key: "copilot",
    title: "Copilot model",
    description: "The model deployment that answers governed copilot requests.",
    member: "copilot",
    credential: "managed_identity",
    fields: [
      { name: "endpoint", label: "Endpoint (https)", kind: "text", required: true },
      { name: "deployment", label: "Deployment name", kind: "text", required: true },
      {
        name: "api_version",
        label: "API version",
        kind: "text",
        required: true,
        hint: "2025-01-01-preview",
      },
      RESOURCE,
    ],
  },
  judge: {
    key: "judge",
    title: "Evaluation judge model",
    description: "The model deployment used as the evaluation judge.",
    member: "judge",
    credential: "managed_identity",
    fields: [
      { name: "endpoint", label: "Endpoint (https)", kind: "text", required: true },
      { name: "deployment", label: "Deployment name", kind: "text", required: true },
      {
        name: "api_version",
        label: "API version",
        kind: "text",
        required: true,
        hint: "2025-01-01-preview",
      },
      RESOURCE,
    ],
  },
  search: {
    key: "search",
    title: "Search",
    description: "Azure AI Search service and index for catalog and evidence search.",
    member: "search",
    credential: "any",
    fields: [
      { name: "endpoint", label: "Endpoint (https)", kind: "text", required: true },
      { name: "index_name", label: "Index name", kind: "text", required: true },
      RESOURCE,
    ],
  },
  scan: {
    key: "scan",
    title: "Discovery scan",
    description: "Scheduled discovery scan over subscriptions or resource groups.",
    member: "scan",
    credential: "any",
    fields: [
      {
        name: "interval_seconds",
        label: "Interval in seconds (300 to 604800)",
        kind: "number",
        required: true,
      },
      { name: "scopes", label: "Scopes (one per line)", kind: "lines", required: true },
    ],
  },
  mcp_server: {
    key: "mcp_server",
    title: "MCP server",
    description: "The NeuroSphere MCP server endpoint published to clients.",
    member: "mcp_server",
    credential: "optional",
    fields: [
      { name: "endpoint", label: "Endpoint (https)", kind: "text", required: true },
      RESOURCE,
    ],
  },
};

export interface SettingDraft {
  readonly enabled: boolean;
  readonly values: Readonly<Record<string, string>>;
  readonly credential: CredentialDraft;
}

export const EMPTY_DRAFT: SettingDraft = {
  enabled: false,
  values: {},
  credential: EMPTY_CREDENTIAL,
};

type Json = Record<string, unknown>;

/** Reads a stored SystemSetting body into form state. Unknown shapes become an empty draft. */
export function draftFromStored(spec: SettingSpec, stored: unknown): SettingDraft {
  if (stored === null || typeof stored !== "object") return EMPTY_DRAFT;
  const body = stored as Json;
  const member = (body[spec.member] ?? {}) as Json;
  const values: Record<string, string> = {};
  for (const f of spec.fields) {
    const raw = member[f.name];
    if (Array.isArray(raw)) values[f.name] = raw.map(String).join("\n");
    else if (raw !== undefined && raw !== null) values[f.name] = String(raw);
  }
  return {
    enabled: body["enabled"] === true,
    values,
    credential: fromReference((member["credential"] ?? null) as CredentialReference | null),
  };
}

/** Why the draft cannot be saved, or undefined when it can. */
export function draftProblem(spec: SettingSpec, draft: SettingDraft): string | undefined {
  for (const f of spec.fields) {
    if (f.required && (draft.values[f.name] ?? "").trim() === "") return `${f.label} is required.`;
  }
  if (spec.credential !== "optional" && draft.credential.kind === "none") {
    return "A credential reference is required.";
  }
  if (spec.credential === "managed_identity" && draft.credential.kind !== "managed_identity") {
    return "This model is called with a managed identity.";
  }
  if (draft.credential.kind !== "none") return credentialProblem(draft.credential);
  return undefined;
}

/** The SystemSetting body for a PUT. Only references; no field is ever a credential value. */
export function bodyFromDraft(spec: SettingSpec, draft: SettingDraft): Json {
  const member: Json = {};
  for (const f of spec.fields) {
    const text = (draft.values[f.name] ?? "").trim();
    if (f.kind === "number") {
      if (text !== "") member[f.name] = Number(text);
    } else if (f.kind === "lines") {
      member[f.name] = text
        .split("\n")
        .map((l) => l.trim())
        .filter((l) => l !== "");
    } else if (text !== "") {
      member[f.name] = text;
    } else if (f.name === "resource_id") {
      member[f.name] = null;
    }
  }
  member["credential"] = toReference(draft.credential);
  return {
    schema_version: "1.0.0",
    setting_key: spec.key,
    enabled: draft.enabled,
    [spec.member]: member,
  };
}

/** Before and after text for each changed field, for the confirm dialog. */
export function draftDiff(
  spec: SettingSpec,
  before: SettingDraft,
  after: SettingDraft,
): { readonly field: string; readonly before: string; readonly after: string }[] {
  const rows: { field: string; before: string; after: string }[] = [];
  if (before.enabled !== after.enabled) {
    rows.push({ field: "enabled", before: String(before.enabled), after: String(after.enabled) });
  }
  for (const f of spec.fields) {
    const b = (before.values[f.name] ?? "").trim();
    const a = (after.values[f.name] ?? "").trim();
    if (a !== b)
      rows.push({ field: f.name, before: b === "" ? "unset" : b, after: a === "" ? "unset" : a });
  }
  const bc = `${before.credential.kind}:${before.credential.value.trim()}`;
  const ac = `${after.credential.kind}:${after.credential.value.trim()}`;
  if (bc !== ac) rows.push({ field: "credential", before: bc, after: ac });
  return rows;
}
