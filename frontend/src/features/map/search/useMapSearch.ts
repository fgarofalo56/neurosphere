import { useEffect, useRef, useState } from "react";
import { useApiClient, type ApiError } from "../../../api/index.js";
import { searchPath } from "../filters/hooks";
import type { MapFilterQuery } from "../filters/useMapFilters";
import type { SearchMatch, SearchResponse, TruncationReason } from "../types";

/** The server needs a needle; a shorter query is never sent. */
export const MIN_QUERY_LENGTH = 2;
export const SEARCH_DEBOUNCE_MS = 250;
/** Results shown in the list. */
export const SEARCH_LIMIT = 20;

export interface MapSearchState {
  readonly matches: readonly SearchMatch[];
  readonly truncated: boolean;
  readonly truncationReason: TruncationReason | null;
  /** True while the query is long enough and the response for it is not in yet. */
  readonly loading: boolean;
  readonly error: ApiError | null;
  /** The query is long enough to search. */
  readonly active: boolean;
}

const IDLE: MapSearchState = {
  matches: [],
  truncated: false,
  truncationReason: null,
  loading: false,
  error: null,
  active: false,
};

/**
 * Domain search for the map and the table. Nothing is sent below MIN_QUERY_LENGTH characters; a
 * typing pause collapses keystrokes into one request; and the request in flight is aborted on the
 * very next keystroke (not when the debounce fires), so a stale response never replaces a newer
 * one. The given filters (the active map filters) narrow the search.
 */
export function useMapSearch(
  domainId: string,
  query: string,
  filters: MapFilterQuery = {},
  debounceMs: number = SEARCH_DEBOUNCE_MS,
): MapSearchState {
  const client = useApiClient();
  const trimmed = query.trim();
  const active = trimmed.length >= MIN_QUERY_LENGTH;
  const filterJson = JSON.stringify(filters);
  const controllerRef = useRef<AbortController | null>(null);
  // `seq` re-runs the request for unchanged text whose request was aborted by a keystroke.
  const [settled, setSettled] = useState<{ q: string; seq: number }>({ q: "", seq: 0 });
  const [result, setResult] = useState<{ id: string; state: MapSearchState } | null>(null);

  // Every keystroke: abort what is in flight, then settle after the typing pause.
  useEffect(() => {
    controllerRef.current?.abort();
    controllerRef.current = null;
    if (!active) {
      setSettled((prev) => ({ q: "", seq: prev.seq + 1 }));
      return;
    }
    const timer = setTimeout(
      () => setSettled((prev) => ({ q: trimmed, seq: prev.seq + 1 })),
      debounceMs,
    );
    return () => clearTimeout(timer);
  }, [trimmed, active, debounceMs]);

  const requestId = `${domainId}|${settled.q}|${filterJson}`;
  useEffect(() => {
    if (settled.q.length < MIN_QUERY_LENGTH) return;
    const controller = new AbortController();
    controllerRef.current = controller;
    const parsed = JSON.parse(filterJson) as MapFilterQuery;
    client
      .get<SearchResponse>(
        searchPath(domainId),
        { ...parsed, q: settled.q, limit: SEARCH_LIMIT },
        controller.signal,
      )
      .then((response) => {
        if (controller.signal.aborted) return;
        setResult({
          id: requestId,
          state: {
            matches: response.matches ?? [],
            truncated: response.truncated === true,
            truncationReason: response.truncation_reason ?? null,
            loading: false,
            error: null,
            active: true,
          },
        });
      })
      .catch((caught: unknown) => {
        if (controller.signal.aborted) return;
        setResult({ id: requestId, state: { ...IDLE, active: true, error: caught as ApiError } });
      });
    return () => controller.abort();
  }, [client, domainId, settled.q, settled.seq, filterJson]);

  if (!active) return IDLE;
  if (result !== null && result.id === requestId && settled.q === trimmed) return result.state;
  // The text moved on or the request is in flight: keep the previous matches, flag loading.
  const previous = result !== null && result.id.startsWith(`${domainId}|`) ? result.state : IDLE;
  return { ...previous, loading: true, error: null, active: true };
}
