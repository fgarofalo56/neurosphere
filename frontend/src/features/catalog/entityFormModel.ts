/**
 * Create and edit model for catalog entities (PRP-31 round 2 item 10; wire contract is item 13).
 * Field sets follow packages/contracts catalog/v1/{agent,tool,model_deployment,mcp_server}. The
 * request body NEVER carries a server-owned key: the server mints the id and derives scope.
 */
import type { CatalogEntityView } from "./explorerTypes";

export const FORM_TYPES = ["agent", "tool", "model_deployment", "mcp_server"] as const;
export type FormType = (typeof FORM_TYPES)[number];

export function isFormType(value: string): value is FormType {
  return (FORM_TYPES as readonly string[]).includes(value);
}

/** Keys the server owns: sending any of them is a 422. PUT also refuses `lifecycle_status`. */
export const SERVER_OWNED_KEYS: readonly string[] = [
  "id",
  "cloud",
  "customer_id",
  "domain_id",
  "version",
  "etag",
  "created_at",
  "updated_at",
  "schema_version",
  "recertified_at",
  "recertify_by",
];
const EDIT_REFUSED_KEYS: readonly string[] = [...SERVER_OWNED_KEYS, "lifecycle_status"];

export const TOKEN_PATTERN = /^[a-z0-9][a-z0-9._-]*$/;
export const MCP_URL_PATTERN =
  /^https:\/\/[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)*(:[0-9]{1,5})?(\/[A-Za-z0-9._~%!$&'()*+,;=:@-]+)*\/mcp$/;

export type FieldKind = "text" | "textarea" | "select" | "switch";
export type FieldCheck = "token" | "url" | "none";

export interface FieldDef {
  readonly key: string;
  readonly kind: FieldKind;
  readonly required: boolean;
  readonly maxLength?: number;
  readonly options?: readonly string[];
  readonly check?: FieldCheck;
  readonly initial: string;
}

const CLASSIFICATIONS = ["unknown", "public", "internal", "confidential", "restricted"] as const;

const classification: FieldDef = {
  key: "classification",
  kind: "select",
  required: false,
  options: CLASSIFICATIONS,
  initial: "unknown",
};
const text = (
  key: string,
  required: boolean,
  check: FieldCheck = "none",
  maxLength = 256,
): FieldDef => ({ key, kind: "text", required, check, maxLength, initial: "" });
const select = (key: string, options: readonly string[], initial: string): FieldDef => ({
  key,
  kind: "select",
  required: true,
  options,
  initial,
});

export const FIELD_DEFS: Readonly<Record<FormType, readonly FieldDef[]>> = {
  agent: [
    text("display_name", true),
    { key: "description", kind: "textarea", required: false, maxLength: 2000, initial: "" },
    text("platform", true, "token", 128),
    text("source_id", true, "token", 128),
    select(
      "agent_kind",
      ["unknown", "assistant", "workflow", "sub_agent", "autonomous"],
      "unknown",
    ),
    classification,
  ],
  tool: [
    text("display_name", true),
    text("source_id", true, "token", 128),
    select(
      "tool_kind",
      ["unknown", "function", "api", "mcp_tool", "search", "code_interpreter", "other"],
      "unknown",
    ),
    select("side_effects", ["unknown", "read_only", "writes"], "unknown"),
    classification,
  ],
  model_deployment: [
    text("provider", true, "token", 128),
    text("model_name", true),
    text("deployment_name", true),
    text("model_version", false, "none", 128),
    classification,
  ],
  mcp_server: [
    text("display_name", true),
    text("url", true, "url", 2048),
    select("transport", ["streamable_http", "sse"], "streamable_http"),
    select("auth_kind", ["entra", "managed_identity", "none", "api_key"], "entra"),
    text("auth_audience", false, "none", 512),
    { key: "publishable", kind: "switch", required: true, initial: "false" },
    classification,
  ],
};

export type FormValues = Readonly<Record<string, string>>;

export function entityRecord(entity: CatalogEntityView): Record<string, unknown> {
  return entity as unknown as Record<string, unknown>;
}

function asText(value: unknown): string {
  if (typeof value === "string") return value;
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "number") return String(value);
  return "";
}

/** Form values for a type: defaults on create, the entity's current values on edit. */
export function initialValues(type: FormType, entity?: CatalogEntityView): FormValues {
  const doc = entity === undefined ? {} : entityRecord(entity);
  const auth = doc["auth"] as { kind?: unknown; audience?: unknown } | undefined;
  const out: Record<string, string> = {};
  for (const def of FIELD_DEFS[type]) {
    let current: string;
    if (def.key === "auth_kind") current = asText(auth?.kind);
    else if (def.key === "auth_audience") current = asText(auth?.audience);
    else current = asText(doc[def.key]);
    out[def.key] = current === "" ? def.initial : current;
  }
  return out;
}

/** Field-level problems as message keys of STRINGS.form; empty when the values are valid. */
export function validate(type: FormType, values: FormValues): Readonly<Record<string, string>> {
  const problems: Record<string, string> = {};
  for (const def of FIELD_DEFS[type]) {
    const value = (values[def.key] ?? "").trim();
    if (def.required && def.kind !== "switch" && value === "") problems[def.key] = "required";
    else if (value !== "" && def.check === "token" && !TOKEN_PATTERN.test(value)) {
      problems[def.key] = "token";
    } else if (value !== "" && def.check === "url" && !MCP_URL_PATTERN.test(value)) {
      problems[def.key] = "url";
    }
  }
  return problems;
}

/** SSE transport or an API-key upstream can never be published. */
export function publishBlocked(values: FormValues): boolean {
  return values["transport"] === "sse" || values["auth_kind"] === "api_key";
}

/**
 * Request body. Edit starts from the stored document so fields this form does not manage survive
 * the PUT, minus every server-owned key and `lifecycle_status`; create sends only the form fields.
 * `now` stamps the MCP provenance the contract requires.
 */
export function buildBody(
  type: FormType,
  values: FormValues,
  options: { readonly entity?: CatalogEntityView; readonly now: string },
): Record<string, unknown> {
  const body: Record<string, unknown> = {};
  const editing = options.entity !== undefined;
  if (options.entity !== undefined) {
    for (const [key, value] of Object.entries(entityRecord(options.entity))) {
      if (!EDIT_REFUSED_KEYS.includes(key)) body[key] = value;
    }
  }
  body["entity_type"] = type;
  for (const def of FIELD_DEFS[type]) {
    if (def.key === "auth_kind" || def.key === "auth_audience") continue;
    const raw = (values[def.key] ?? "").trim();
    if (def.kind === "switch")
      body[def.key] = values[def.key] === "true" && !publishBlocked(values);
    else if (raw !== "") body[def.key] = raw;
    else if (editing && def.key in body) body[def.key] = null;
  }
  if (type === "mcp_server") {
    const audience = (values["auth_audience"] ?? "").trim();
    body["auth"] = {
      kind: values["auth_kind"] ?? "entra",
      ...(audience !== "" && { audience }),
    };
    body["provenance"] ??= {
      method: "declared",
      source_id: "catalog-ui",
      recorded_at: options.now,
    };
  }
  return body;
}

export interface DiffRow {
  readonly field: string;
  readonly before: string;
  readonly after: string;
}

function show(value: unknown, none: string): string {
  if (value === null || value === undefined || value === "") return none;
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

/** Changed fields only on edit; every set field on create (before is `none`). */
export function diffRows(
  body: Readonly<Record<string, unknown>>,
  entity: CatalogEntityView | undefined,
  none: string,
): readonly DiffRow[] {
  const before = entity === undefined ? {} : entityRecord(entity);
  const rows: DiffRow[] = [];
  for (const [key, value] of Object.entries(body)) {
    if (key === "provenance" && entity !== undefined) continue;
    const a = show(before[key], none);
    const b = show(value, none);
    if (entity === undefined ? b !== none : a !== b) rows.push({ field: key, before: a, after: b });
  }
  return rows;
}
