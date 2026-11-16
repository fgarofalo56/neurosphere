export const MAX_IMPORT_ITEMS = 100;
/** Rows of results rendered; the rest are summarised so a hostile payload cannot flood the DOM. */
export const MAX_PREVIEW_ROWS = 100;

export type ParsedPayload =
  | { readonly ok: true; readonly items: readonly Record<string, unknown>[]; readonly digest: string }
  | { readonly ok: false; readonly error: string };

/** Stable JSON: object keys sorted, so the same payload always gives the same text. */
export function canonicalJson(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(",")}]`;
  if (value !== null && typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>).sort(([a], [b]) =>
      a < b ? -1 : a > b ? 1 : 0,
    );
    return `{${entries.map(([k, v]) => `${JSON.stringify(k)}:${canonicalJson(v)}`).join(",")}}`;
  }
  return JSON.stringify(value) ?? "null";
}

/** A small non-cryptographic digest (cyrb53) of the canonical payload; equality gates the commit. */
export function digestOf(text: string): string {
  let h1 = 0xdeadbeef;
  let h2 = 0x41c6ce57;
  for (let i = 0; i < text.length; i += 1) {
    const ch = text.charCodeAt(i);
    h1 = Math.imul(h1 ^ ch, 2654435761);
    h2 = Math.imul(h2 ^ ch, 1597334677);
  }
  h1 = Math.imul(h1 ^ (h1 >>> 16), 2246822507) ^ Math.imul(h2 ^ (h2 >>> 13), 3266489909);
  h2 = Math.imul(h2 ^ (h2 >>> 16), 2246822507) ^ Math.imul(h1 ^ (h1 >>> 13), 3266489909);
  const n = 4294967296 * (2097151 & h2) + (h1 >>> 0);
  return `${n.toString(16)}:${text.length}`;
}

/** Accepts a JSON array of entity documents or `{ "items": [...] }`. */
export function parsePayload(text: string): ParsedPayload {
  if (text.trim() === "") return { ok: false, error: "Paste or upload JSON first." };
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch {
    return { ok: false, error: "This is not valid JSON." };
  }
  const list =
    Array.isArray(parsed) ||
    parsed === null ||
    typeof parsed !== "object" ||
    !Array.isArray((parsed as { items?: unknown }).items)
      ? parsed
      : (parsed as { items: unknown[] }).items;
  if (!Array.isArray(list)) {
    return { ok: false, error: "Expected a JSON array of entity documents or { items: [...] }." };
  }
  if (list.length === 0) return { ok: false, error: "The payload has no items." };
  if (list.length > MAX_IMPORT_ITEMS) {
    return {
      ok: false,
      error: `The payload has ${list.length} items. The limit is ${MAX_IMPORT_ITEMS} per import.`,
    };
  }
  if (!list.every((i) => i !== null && typeof i === "object" && !Array.isArray(i))) {
    return { ok: false, error: "Every item must be a JSON object." };
  }
  return {
    ok: true,
    items: list as Record<string, unknown>[],
    digest: digestOf(canonicalJson(list)),
  };
}
