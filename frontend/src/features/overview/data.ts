import { createQueryHook } from "../../api/index.js";
import type { NsRole } from "../../auth/roles";
import type { Series } from "../dashboards/types";
import { MAP_PATH } from "../map/paths";
import { REPORTS_LIST_ROUTE, reportsPath } from "../reports/paths";

/**
 * Data layer of the overview tiles. Each tile has its OWN query so one failing or forbidden
 * endpoint never blanks the others. The domain is a path segment (the shared client refuses
 * `domain_id` as a parameter). No endpoint returns totals: a list is shown as "N" from one page,
 * or "N+" when the server reports a next page; an exact count is never invented.
 *
 * Imports stay light on purpose: only pure `paths`/`types` modules of other features, never a
 * feature `index.ts` (sigma/vega would reach jsdom).
 */

export type TileId = "cost" | "review" | "awaiting" | "map" | "reports";

/** Every tile, in display order. */
export const TILE_ORDER: readonly TileId[] = ["cost", "review", "awaiting", "map", "reports"];

/**
 * Which tiles each role is shown. Display only: hiding a tile is not authorization, the API
 * still answers 403 and the tile shows that. A caller with no recognised role gets the Viewer
 * set. Roles combine by union.
 */
export const ROLE_TILES: Readonly<Record<NsRole, readonly TileId[]>> = {
  Viewer: ["cost", "map", "reports"],
  // Analysts propose and confirm their own actions, but do not work the review queue.
  Analyst: ["cost", "awaiting", "map", "reports"],
  // Auditors oversee the review queue read-only; action approval is not theirs.
  Auditor: ["cost", "review", "map", "reports"],
  Steward: ["cost", "review", "awaiting", "map", "reports"],
  Admin: ["cost", "review", "awaiting", "map", "reports"],
};

export function tilesForRoles(roles: readonly NsRole[]): readonly TileId[] {
  const source: readonly NsRole[] = roles.length === 0 ? ["Viewer"] : roles;
  const wanted = new Set<TileId>();
  for (const role of source) for (const tile of ROLE_TILES[role]) wanted.add(tile);
  return TILE_ORDER.filter((tile) => wanted.has(tile));
}

/** Calls the page makes per tile (awaiting makes two). Their sum is the page's call ceiling. */
export const TILE_CALLS: Readonly<Record<TileId, number>> = {
  cost: 1,
  review: 1,
  awaiting: 2,
  map: 1,
  reports: 1,
};
export const MAX_OVERVIEW_CALLS = 7;

// ---- Links into each feature (route paths; the domain rides in `?domain_id=`).

const COST_DASHBOARD_PATH = "/dashboards/cost";
const REVIEW_PATH = "/review";
const ACTIONS_PATH = "/actions";

export function tileHref(tile: TileId, domainId: string): string {
  const base: Record<TileId, string> = {
    cost: COST_DASHBOARD_PATH,
    review: REVIEW_PATH,
    awaiting: ACTIONS_PATH,
    map: MAP_PATH,
    reports: `/${REPORTS_LIST_ROUTE}`,
  };
  return `${base[tile]}?${new URLSearchParams({ domain_id: domainId }).toString()}`;
}

// ---- Minimal response shapes (only the fields the tiles read).

export interface PagedList<T> {
  readonly items: readonly T[];
  readonly next_cursor?: string | null | undefined;
}

export interface CostResponse {
  readonly series: readonly Series[];
}

export interface MapCoverageResponse {
  readonly coverage: {
    readonly state: "complete" | "partial" | "delayed" | "unknown";
    readonly lag_seconds: number | null;
    readonly as_of: string | null;
  };
}

export interface ReportSummary {
  readonly id: string;
  readonly title: string;
}

export type AwaitingState = "awaiting_confirmation" | "awaiting_approval";
export const AWAITING_STATES: readonly AwaitingState[] = [
  "awaiting_confirmation",
  "awaiting_approval",
];

const enc = encodeURIComponent;

export const useCostTile = createQueryHook<{ domainId: string }, CostResponse>({
  key: "overview-cost",
  fetcher: (client, p, signal) =>
    client.get<CostResponse>(
      `/api/v1/dashboards/domains/${enc(p.domainId)}/cost`,
      { days: 7 },
      signal,
    ),
});

export const useReviewTile = createQueryHook<{ domainId: string }, PagedList<{ id: string }>>({
  key: "overview-review",
  fetcher: (client, p, signal) =>
    client.get<PagedList<{ id: string }>>(
      `/api/v1/review/domains/${enc(p.domainId)}/items`,
      { state: "pending" },
      signal,
    ),
});

export const useAwaitingTile = createQueryHook<
  { domainId: string; state: AwaitingState },
  PagedList<{ intent?: { id?: string } }>
>({
  key: "overview-awaiting",
  fetcher: (client, p, signal) =>
    client.get<PagedList<{ intent?: { id?: string } }>>(
      `/api/v1/actions/domains/${enc(p.domainId)}/intents`,
      { state: p.state },
      signal,
    ),
});

export const useMapTile = createQueryHook<{ domainId: string }, MapCoverageResponse>({
  key: "overview-map",
  fetcher: (client, p, signal) =>
    client.get<MapCoverageResponse>(
      `/api/v1/map/domains/${enc(p.domainId)}/viewport`,
      { node_budget: 1 },
      signal,
    ),
});

export const REPORTS_TILE_LIMIT = 5;

export const useReportsTile = createQueryHook<{ domainId: string }, PagedList<ReportSummary>>({
  key: "overview-reports",
  fetcher: (client, p, signal) =>
    client.get<PagedList<ReportSummary>>(
      reportsPath(p.domainId),
      { limit: REPORTS_TILE_LIMIT },
      signal,
    ),
});

/** "N" for a complete list, "N+" when a next page exists. Never an exact total. */
export function countText(list: PagedList<unknown>): string {
  const n = list.items.length;
  const more = list.next_cursor !== null && list.next_cursor !== undefined;
  return more ? `${n}+` : `${n}`;
}
