import { useInfiniteQuery, type UseInfiniteQueryResult } from "@tanstack/react-query";
import {
  ForbiddenError,
  StaleVersionError,
  createMutationHook,
  createQueryHook,
  isApiError,
  useApiClient,
  type ApiError,
} from "../../api/index.js";
import type { ChangeDiffRow } from "../governed-change";
import {
  domainEdgePath,
  edgeDecisionsPath,
  edgeObservationsPath,
  edgeOverridesPath,
} from "./paths";
import { STRINGS } from "./strings";
import type {
  Decision,
  DecisionBody,
  DecisionResult,
  EdgeRead,
  ObservationPage,
  OverrideHistory,
  PresentedEdge,
} from "./types";

/** Observations are cursor paged; no total is ever shown. */
export const OBSERVATION_PAGE_SIZE = 25;

/** Reads through the selected domain's path so the response carries edge_version / edge_etag. */
export const useEdge = createQueryHook<{ domain: string; edgeId: string }, EdgeRead>({
  key: "curation-edge",
  fetcher: (client, p, signal) =>
    client.get<EdgeRead>(domainEdgePath(p.domain, p.edgeId), undefined, signal),
});

export const useOverrides = createQueryHook<{ edgeId: string }, OverrideHistory>({
  key: "curation-overrides",
  fetcher: (client, p, signal) =>
    client.get<OverrideHistory>(edgeOverridesPath(p.edgeId), undefined, signal),
});

/** Observations need `evidence.read`; the query only runs once the section is opened. */
export function useObservations(
  edgeId: string,
  enabled: boolean,
): UseInfiniteQueryResult<{ pages: ObservationPage[] }, ApiError> {
  const client = useApiClient();
  return useInfiniteQuery<
    ObservationPage,
    ApiError,
    { pages: ObservationPage[] },
    unknown[],
    string | undefined
  >({
    queryKey: ["curation-observations", edgeId],
    initialPageParam: undefined,
    enabled,
    queryFn: ({ pageParam, signal }) =>
      client.get<ObservationPage>(
        edgeObservationsPath(edgeId),
        {
          page_size: OBSERVATION_PAGE_SIZE,
          ...(pageParam === undefined ? {} : { cursor: pageParam }),
        },
        signal,
      ),
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  }) as UseInfiniteQueryResult<{ pages: ObservationPage[] }, ApiError>;
}

export interface DecideVars {
  readonly domain: string;
  readonly edgeId: string;
  readonly body: DecisionBody;
}

/** The selected domain rides in the PATH; the body holds the decision and its preconditions only. */
export const useDecide = createMutationHook<DecideVars, DecisionResult>({
  mutate: (client, v) => client.post<DecisionResult>(edgeDecisionsPath(v.domain, v.edgeId), v.body),
});

export const PINNING: readonly Decision[] = ["lock", "override"];

export function needsExpiry(decision: Decision): boolean {
  return PINNING.includes(decision);
}

/** Converts the dialog's local date-time to an RFC 3339 UTC timestamp, or null when invalid. */
export function expiryToTimestamp(local: string): string | null {
  const at = new Date(local);
  if (Number.isNaN(at.getTime())) return null;
  return at.toISOString().replace(/\.\d{3}Z$/, "Z");
}

/** True when the timestamp lies after `now`. */
export function isFuture(timestamp: string, now: number = Date.now()): boolean {
  return new Date(timestamp).getTime() > now;
}

function lockText(edge: PresentedEdge): string {
  if (!edge.lock.locked) return STRINGS.summary.unlocked;
  const expiry = edge.lock.expiry ?? "";
  return expiry === ""
    ? STRINGS.summary.locked
    : `${STRINGS.summary.locked}, ${STRINGS.summary.lockExpiry} ${expiry}`;
}

/**
 * What the dialog shows as before/after. It describes what the decision asks for; the server
 * decides and the page reloads the real edge afterwards.
 */
export function decisionDiff(
  edge: PresentedEdge,
  decision: Decision,
  pinnedConfidence: number | null,
  expiryLabel: string,
): ChangeDiffRow[] {
  const afterLock =
    decision === "lock" || decision === "override"
      ? `${STRINGS.summary.locked}, ${STRINGS.summary.lockExpiry} ${expiryLabel}`
      : decision === "unlock"
        ? STRINGS.summary.unlocked
        : lockText(edge);
  const afterConfidence =
    (decision === "lock" || decision === "override") && pinnedConfidence !== null
      ? String(pinnedConfidence)
      : String(edge.confidence);
  return [
    { field: STRINGS.summary.status, before: edge.status, after: "curated" },
    { field: STRINGS.summary.lock, before: lockText(edge), after: afterLock },
    { field: STRINGS.summary.confidence, before: String(edge.confidence), after: afterConfidence },
  ];
}

/** Readable message for a failed decision. A stale edge is never retried by the page. */
export function decisionErrorMessage(error: unknown): string {
  if (!isApiError(error)) return STRINGS.decide.generic;
  const reason = error.problem?.reason;
  if (error instanceof StaleVersionError)
    return STRINGS.reasons["stale_edge"] ?? STRINGS.decide.stale;
  if (typeof reason === "string") {
    const known = STRINGS.reasons[reason];
    if (known !== undefined) return known;
  }
  if (error instanceof ForbiddenError) return STRINGS.decide.forbidden;
  if (error.status === 404) return STRINGS.decide.notFound;
  return STRINGS.decide.generic;
}

export function isStale(error: unknown): boolean {
  return error instanceof StaleVersionError;
}
