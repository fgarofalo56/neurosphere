import { createQueryHook } from "../../../api/index.js";
import { auditPaths } from "../shared/adminPaths";

/** The slice of an audit record the console shows (PRP-40 `AuditRecord`). */
export interface AuditRecordView {
  readonly audit_id: string;
  readonly chain_id: string;
  readonly sequence: number;
  readonly kind: "before" | "after" | "denied";
  readonly recorded_at: string;
  readonly actor: { readonly principal_pseudonym: string; readonly principal_kind: string };
  readonly correlation_id: string;
  readonly operation: string;
  readonly outcome: { readonly result: string; readonly verified: boolean } | null;
  readonly denial: { readonly code: string; readonly reason: string } | null;
}

export interface AuditHitView {
  readonly domain_id: string;
  readonly record: AuditRecordView;
}

export interface AuditSearchPageView {
  readonly items: readonly AuditHitView[];
  readonly next_cursor?: string | null;
}

export interface DenialsPageView {
  readonly items: readonly AuditRecordView[];
  readonly next_cursor?: string | null;
}

export interface SiemStatusView {
  readonly sink: string;
  readonly state: "ok" | "disabled" | "failed" | "not_built";
  readonly reason?: string | null;
  readonly consecutive_failures?: number;
  readonly last_success_at?: string | null;
  readonly last_failure_at?: string | null;
  readonly last_failure_reason?: string | null;
}

/** Filters as sent to the API. `since` and `until` are required RFC 3339 timestamps. */
export interface AuditFilters {
  readonly since: string;
  readonly until: string;
  readonly domain: string;
  readonly operation: string;
  readonly kind: string;
  readonly outcome: string;
  readonly actor: string;
  readonly correlationId: string;
}

export const AUDIT_PAGE_SIZE = 25;

/** Maps the filters to the query names of the shipped PRP-40 routes; empty fields are omitted. */
export function filterQuery(f: AuditFilters): Record<string, string> {
  const query: Record<string, string> = { since: f.since, until: f.until };
  const optional: Record<string, string> = {
    domain: f.domain,
    operation: f.operation,
    kind: f.kind,
    outcome: f.outcome,
    actor: f.actor,
    correlation_id: f.correlationId,
  };
  for (const [name, value] of Object.entries(optional)) {
    if (value.trim() !== "") query[name] = value.trim();
  }
  return query;
}

export interface SearchParams {
  readonly filters: AuditFilters;
  readonly cursor: string;
}

export const useAuditSearch = createQueryHook<SearchParams, AuditSearchPageView>({
  key: "admin-audit-search",
  fetcher: (client, p, signal) =>
    client.get<AuditSearchPageView>(
      auditPaths.search(),
      {
        ...filterQuery(p.filters),
        page_size: AUDIT_PAGE_SIZE,
        ...(p.cursor === "" ? {} : { cursor: p.cursor }),
      },
      signal,
    ),
});

export const useAuditDenials = createQueryHook<{ cursor: string }, DenialsPageView>({
  key: "admin-audit-denials",
  fetcher: (client, p, signal) =>
    client.get<DenialsPageView>(
      auditPaths.denials(),
      { page_size: AUDIT_PAGE_SIZE, ...(p.cursor === "" ? {} : { cursor: p.cursor }) },
      signal,
    ),
});

export const useSiemStatus = createQueryHook<Record<string, never>, SiemStatusView>({
  key: "admin-audit-siem",
  fetcher: (client, _p, signal) => client.get<SiemStatusView>(auditPaths.siem(), undefined, signal),
});

/** The API caps a search or export window at 31 days. */
export const MAX_RANGE_DAYS = 31;
/** Export row cap (docs/runbooks/audit-siem.md). */
export const EXPORT_ROW_CAP = 10_000;

/** A usability check only; the API validates the range and answers 422 with its own text. */
export function rangeProblem(sinceLocal: string, untilLocal: string): string | undefined {
  const since = Date.parse(sinceLocal);
  const until = Date.parse(untilLocal);
  if (Number.isNaN(since) || Number.isNaN(until)) return "Choose a start and an end time.";
  if (until <= since) return "The end time must be after the start time.";
  if (until - since > MAX_RANGE_DAYS * 86_400_000) {
    return `The time range is capped at ${MAX_RANGE_DAYS} days.`;
  }
  return undefined;
}
