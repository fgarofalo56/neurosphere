import { createQueryHook } from "../../api/index.js";
import { federationSummaryPath } from "./paths";

/** Response shapes of `GET /api/v1/federation/summary` (federation/models.py). */
export type CellState = "ok" | "denied" | "unavailable";

export interface CellOutcome {
  readonly cell_id: string;
  readonly state: CellState;
}

export interface CostTotal {
  readonly kind: "estimated" | "invoiced";
  readonly currency: string;
  /** Decimal string, or null when nothing was known (never 0). */
  readonly amount: string | null;
  readonly complete: boolean;
}

export interface DomainSummary {
  readonly domain_id: string;
  readonly request_count?: number | null;
  readonly error_count?: number | null;
  readonly unknown_outcome_count?: number | null;
  readonly costs: readonly CostTotal[];
  readonly complete: boolean;
}

export interface MergedSummary {
  readonly cloud: string;
  readonly boundary_id: string;
  readonly window_start: string;
  readonly window_end: string;
  readonly cells: readonly CellOutcome[];
  readonly domains: readonly DomainSummary[];
  readonly totals: readonly CostTotal[];
  readonly complete: boolean;
  readonly truncated: boolean;
}

export interface FederationParams {
  readonly days: number;
  /** One cell id, or "" for all cells (the client cannot repeat a query key). */
  readonly cell: string;
}

export const useFederation = createQueryHook<FederationParams, MergedSummary>({
  key: "federation-summary",
  fetcher: (client, p, signal) =>
    client.get<MergedSummary>(
      federationSummaryPath(),
      { days: p.days, cells: p.cell === "" ? undefined : p.cell },
      signal,
    ),
});

/** Groups totals by currency, preserving first-seen order. Amounts are never combined. */
export function groupByCurrency(totals: readonly CostTotal[]): [string, CostTotal[]][] {
  const groups = new Map<string, CostTotal[]>();
  for (const t of totals) {
    const list = groups.get(t.currency);
    if (list === undefined) groups.set(t.currency, [t]);
    else list.push(t);
  }
  return [...groups.entries()];
}
