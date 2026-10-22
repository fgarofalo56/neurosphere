/**
 * postMessage protocol between ChartFrame (parent) and the sandboxed chart document, plus the
 * defence-in-depth spec guard. The server-side validator is the security boundary; this guard
 * only re-checks the shape so a plan that skipped the server never reaches the compiler.
 */

export const PROTOCOL_VERSION = 1;

export const MSG_READY = "ns.chart.ready";
export const MSG_RENDER = "ns.chart.render";
export const MSG_RENDERED = "ns.chart.rendered";
export const MSG_ERROR = "ns.chart.error";

/** Keys that can carry expressions, network access, interactivity or global config. */
export const BANNED_KEYS: ReadonlySet<string> = new Set([
  "expr",
  "signal",
  "signals",
  "params",
  "param",
  "selection",
  "url",
  "href",
  "calculate",
  "lookup",
  "loader",
  "usermeta",
  "on",
  "events",
  "datasets",
  "$schema",
  "$ref",
  "config",
  "condition",
]);

export const ALLOWED_MARKS: ReadonlySet<string> = new Set([
  "bar",
  "line",
  "area",
  "point",
  "rect",
  "text",
]);

const MAX_DEPTH = 32;
const MAX_ROWS = 5000;

export type SandboxToParent =
  | { type: typeof MSG_READY; version: number }
  | { type: typeof MSG_RENDERED; version: number; request_id: string }
  | { type: typeof MSG_ERROR; version: number; request_id: string; code: ChartErrorCode };

export type ParentToSandbox = {
  type: typeof MSG_RENDER;
  version: number;
  request_id: string;
  spec: unknown;
};

export type ChartErrorCode = "invalid_spec" | "render_failed";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** Returns value-free violation strings; empty means the shape is acceptable. */
export function specViolations(spec: unknown): string[] {
  const out: string[] = [];
  if (!isRecord(spec)) return ["spec must be an object"];

  const scan = (node: unknown, path: string, depth: number, inValues: boolean): void => {
    if (depth > MAX_DEPTH) {
      out.push(`${path}: nesting too deep`);
      return;
    }
    if (Array.isArray(node)) {
      node.forEach((item, i) => scan(item, `${path}/${i}`, depth + 1, inValues));
    } else if (isRecord(node)) {
      for (const [key, value] of Object.entries(node)) {
        if (!inValues && BANNED_KEYS.has(key)) {
          out.push(`${path}/${key}: key not allowed`);
          continue;
        }
        scan(
          value,
          `${path}/${key}`,
          depth + 1,
          inValues || (key === "values" && path === "/data"),
        );
      }
    }
  };
  scan(spec, "", 0, false);

  const mark = spec["mark"];
  const markType = typeof mark === "string" ? mark : isRecord(mark) ? mark["type"] : undefined;
  if (typeof markType !== "string" || !ALLOWED_MARKS.has(markType)) {
    out.push("/mark: mark type not allowed");
  }
  const data = spec["data"];
  if (!isRecord(data) || !Array.isArray(data["values"])) {
    out.push("/data: inline values required");
  } else {
    if (Object.keys(data).some((k) => k !== "values")) out.push("/data: only values allowed");
    if (data["values"].length > MAX_ROWS) out.push("/data/values: too many rows");
  }
  return out;
}

export function isSafeSpec(spec: unknown): boolean {
  return specViolations(spec).length === 0;
}

export function parseSandboxMessage(data: unknown): SandboxToParent | null {
  if (!isRecord(data) || data["version"] !== PROTOCOL_VERSION) return null;
  if (data["type"] === MSG_READY) return { type: MSG_READY, version: PROTOCOL_VERSION };
  const id = data["request_id"];
  if (typeof id !== "string" || id.length === 0 || id.length > 64) return null;
  if (data["type"] === MSG_RENDERED) {
    return { type: MSG_RENDERED, version: PROTOCOL_VERSION, request_id: id };
  }
  if (data["type"] === MSG_ERROR) {
    const code = data["code"];
    if (code !== "invalid_spec" && code !== "render_failed") return null;
    return { type: MSG_ERROR, version: PROTOCOL_VERSION, request_id: id, code };
  }
  return null;
}

export function parseParentMessage(data: unknown): ParentToSandbox | null {
  if (!isRecord(data) || data["version"] !== PROTOCOL_VERSION) return null;
  if (data["type"] !== MSG_RENDER) return null;
  const id = data["request_id"];
  if (typeof id !== "string" || id.length === 0 || id.length > 64) return null;
  return { type: MSG_RENDER, version: PROTOCOL_VERSION, request_id: id, spec: data["spec"] };
}
