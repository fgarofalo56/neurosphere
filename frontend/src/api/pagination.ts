import type { Budget, Page } from "@neurosphere/contracts";

/** List response envelope: items plus the contract Page block. */
export interface PagedResponse<T> {
  items: T[];
  page: Page;
}

export type QueryParams = Record<string, string | number | boolean | undefined>;

/** Conservative client defaults; the server may clamp lower and reports the effective values. */
export const DEFAULT_BUDGET: Budget = { timeout_ms: 10_000, limit: 50, max_depth: 0 };

export function assertValidBudget(budget: Budget): void {
  for (const key of ["timeout_ms", "limit"] as const) {
    if (!Number.isInteger(budget[key]) || budget[key] < 1) {
      throw new RangeError(`budget.${key} must be a positive integer`);
    }
  }
  const optional: [string, number | undefined][] = [
    ["max_depth", budget.max_depth],
    ["max_nodes", budget.max_nodes],
    ["max_edges", budget.max_edges],
  ];
  for (const [name, value] of optional) {
    if (value !== undefined && (!Number.isInteger(value) || value < 0)) {
      throw new RangeError(`budget.${name} must be a non-negative integer`);
    }
  }
}

/** Budget + cursor as query parameters. Never includes scope identifiers. */
export function budgetParams(budget: Budget = DEFAULT_BUDGET, cursor?: string | null): QueryParams {
  assertValidBudget(budget);
  const params: QueryParams = {
    timeout_ms: budget.timeout_ms,
    limit: budget.limit,
    max_depth: budget.max_depth,
    max_nodes: budget.max_nodes,
    max_edges: budget.max_edges,
  };
  if (cursor !== undefined && cursor !== null) params["cursor"] = cursor;
  return params;
}

/** Next cursor for TanStack's getNextPageParam; undefined stops paging. */
export function nextCursor(page: Page): string | undefined {
  return page.has_more && page.next_cursor !== null ? page.next_cursor : undefined;
}

export function flattenPages<T>(pages: readonly PagedResponse<T>[]): T[] {
  return pages.flatMap((p) => p.items);
}

/** A truncated result is partial and must be labelled in the UI. Returns the label or undefined. */
export function truncationNotice(page: Page): string | undefined {
  if (!page.truncated) return undefined;
  return page.truncation_reason === undefined
    ? "Partial result: a budget stopped this result early."
    : `Partial result: stopped by ${page.truncation_reason}.`;
}
