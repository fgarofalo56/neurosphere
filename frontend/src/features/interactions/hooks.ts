import {
  useInfiniteQuery,
  type InfiniteData,
  type UseInfiniteQueryResult,
} from "@tanstack/react-query";
import { createQueryHook, useApiClient, type ApiClient, type ApiError } from "../../api/index.js";
import type {
  InteractionAccessPurpose,
  InteractionExportManifest,
  InteractionExportRequest,
  InteractionFilters,
  InteractionPage,
  InteractionRecord,
  RedactedContent,
} from "./types";

/**
 * The domain is the addressed resource (a path segment), never a scope parameter; the server
 * authorizes it against the derived IdentityScope. Only metadata (list and detail) goes through
 * the TanStack cache. Revealed content and export bundles are fetched with the plain client
 * (`readInteractionContent`, `downloadExportBundle`) and never enter any query cache.
 */
const BASE = "/api/v1/domains";
export const PAGE_SIZE = 25;

export function interactionsPath(domainId: string): string {
  return `${BASE}/${encodeURIComponent(domainId)}/interactions`;
}

export function interactionPath(domainId: string, interactionId: string): string {
  return `${interactionsPath(domainId)}/${encodeURIComponent(interactionId)}`;
}

export function contentReadsPath(domainId: string, interactionId: string): string {
  return `${interactionPath(domainId, interactionId)}/content-reads`;
}

export function exportsPath(domainId: string): string {
  return `${BASE}/${encodeURIComponent(domainId)}/interaction-exports`;
}

export function exportPath(domainId: string, exportId: string): string {
  return `${exportsPath(domainId)}/${encodeURIComponent(exportId)}`;
}

const UTC_DATE = /^\d{4}-\d{2}-\d{2}$/;
const UTC_DATE_TIME = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/;

/**
 * A typed UTC time (`YYYY-MM-DD` or `YYYY-MM-DDTHH:MM`) -> RFC 3339 with a Z suffix (the
 * contract timestamp), or null when empty or not a real date. Plain text, not `datetime-local`:
 * Chromium tabs through that input's segments, which reads as a keyboard trap.
 */
export function toUtc(value: string): string | null {
  const trimmed = value.trim();
  let iso: string;
  if (UTC_DATE.test(trimmed)) iso = `${trimmed}T00:00:00Z`;
  else if (UTC_DATE_TIME.test(trimmed)) iso = `${trimmed}:00Z`;
  else return null;
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return null;
  // Rejects rolled-over dates such as 2026-02-31.
  return at.toISOString().slice(0, 16) === `${iso.slice(0, 16)}` ? iso : null;
}

/** True when a time field is empty or holds a valid UTC time. */
export function timeOk(value: string): boolean {
  return value.trim() === "" || toUtc(value) !== null;
}

/** Query parameters of the search; empty filters are left out. */
export function searchQuery(
  filters: InteractionFilters,
  continuation?: string,
): Record<string, string | number> {
  const query: Record<string, string | number> = { page_size: PAGE_SIZE };
  const set = (key: string, value: string | null): void => {
    if (value !== null && value.trim() !== "") query[key] = value.trim();
  };
  set("agent_id", filters.agentId);
  set("principal_id", filters.principalId);
  set("tool_id", filters.toolId);
  set("data_asset_id", filters.dataAssetId);
  set("detected_category", filters.detectedCategory);
  set("from", toUtc(filters.from));
  set("to", toUtc(filters.to));
  if (continuation !== undefined) query["continuation"] = continuation;
  return query;
}

export function useInteractionList(
  domainId: string,
  filters: InteractionFilters,
): UseInfiniteQueryResult<InfiniteData<InteractionPage, string | undefined>, ApiError> {
  const client = useApiClient();
  return useInfiniteQuery<
    InteractionPage,
    ApiError,
    InfiniteData<InteractionPage, string | undefined>,
    unknown[],
    string | undefined
  >({
    queryKey: ["interactions", domainId, filters],
    initialPageParam: undefined,
    queryFn: ({ pageParam, signal }) =>
      client.get<InteractionPage>(
        interactionsPath(domainId),
        searchQuery(filters, pageParam),
        signal,
      ),
    getNextPageParam: (last) => last.continuation ?? undefined,
  });
}

export interface InteractionParams {
  readonly domainId: string;
  readonly interactionId: string;
}

export const useInteraction = createQueryHook<InteractionParams, InteractionRecord>({
  key: "interaction",
  fetcher: (client, p, signal) =>
    client.get<InteractionRecord>(interactionPath(p.domainId, p.interactionId), undefined, signal),
});

/** One audited content read. Not a query: the caller keeps the result in component state only. */
export function readInteractionContent(
  client: ApiClient,
  domainId: string,
  interactionId: string,
  purpose: InteractionAccessPurpose,
): Promise<RedactedContent> {
  return client.post<RedactedContent>(contentReadsPath(domainId, interactionId), purpose);
}

export function createInteractionExport(
  client: ApiClient,
  domainId: string,
  body: InteractionExportRequest,
): Promise<InteractionExportManifest> {
  return client.post<InteractionExportManifest>(exportsPath(domainId), body);
}

/** The decrypted bundle JSON (audited download); handed straight to a file, never cached. */
export function downloadExportBundle(
  client: ApiClient,
  domainId: string,
  exportId: string,
): Promise<unknown> {
  return client.get<unknown>(`${exportPath(domainId, exportId)}/bundle`);
}
