import type { FilterValue, MessageContext, TimeRangeValue } from "./types";

/**
 * Filter keys the API accepts by default (`DEFAULT_FILTER_KEYS` in the copilot settings). The
 * server stays the authority and refuses any other key with a 422, so only these are forwarded
 * from the page's query string.
 */
export const CONTEXT_FILTER_KEYS: readonly string[] = [
  "environment",
  "kind",
  "lifecycle_status",
  "model_name",
  "outcome",
  "provider",
  "status",
];

const MAX_VALUE = 128;
const MAX_LIST = 10;
const MAX_DAYS = 366;
const ISO_WITH_ZONE = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:\d{2})$/;

function isoOrNull(value: string | null): string | null {
  if (value === null || !ISO_WITH_ZONE.test(value)) return null;
  return Number.isNaN(Date.parse(value)) ? null : value;
}

/**
 * The page's time range: explicit `from` and `to` timestamps win, else a `days` window ending now.
 * Anything malformed or reversed yields `null`; the chip shows what the server really received.
 */
export function timeRangeFromParams(params: URLSearchParams, now: Date): TimeRangeValue | null {
  const from = isoOrNull(params.get("from"));
  const to = isoOrNull(params.get("to"));
  if (from !== null && to !== null) {
    return Date.parse(from) <= Date.parse(to) ? { from, to } : null;
  }
  const rawDays = params.get("days");
  if (rawDays === null || !/^\d{1,3}$/.test(rawDays)) return null;
  const days = Number(rawDays);
  if (days < 1 || days > MAX_DAYS) return null;
  return {
    from: new Date(now.getTime() - days * 86_400_000).toISOString(),
    to: now.toISOString(),
  };
}

export function filtersFromParams(params: URLSearchParams): Record<string, FilterValue> {
  const filters: Record<string, FilterValue> = {};
  for (const key of CONTEXT_FILTER_KEYS) {
    const values = params
      .getAll(key)
      .map((v) => v.trim())
      .filter((v) => v !== "" && v.length <= MAX_VALUE)
      .slice(0, MAX_LIST);
    if (values.length === 1) filters[key] = values[0] ?? "";
    else if (values.length > 1) filters[key] = values;
  }
  return filters;
}

/** First path segment, used as the human-readable page name ("home" for the root). */
export function pageFromPath(pathname: string): string {
  const first = pathname.split("/").find((s) => s !== "");
  return (first ?? "home").slice(0, MAX_VALUE);
}

export interface BuildContextInput {
  readonly pathname: string;
  readonly search: string;
  readonly selection: readonly string[];
  readonly now?: Date;
}

/**
 * The context hint sent with a question, built from the current router location and the
 * selection features published. It is only a hint: the server narrows it against the caller's
 * own scope and echoes back what it used, and THAT echo is what the chip displays.
 */
export function buildMessageContext(input: BuildContextInput): MessageContext {
  const params = new URLSearchParams(input.search);
  const domain = params.get("domain_id")?.trim() ?? "";
  return {
    page: pageFromPath(input.pathname),
    route: input.pathname.slice(0, 256),
    filters: filtersFromParams(params),
    time_range: timeRangeFromParams(params, input.now ?? new Date()),
    selection: input.selection.slice(0, 100),
    domain_id: domain === "" || domain.length > 512 ? null : domain,
  };
}
