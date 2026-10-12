import type { Page } from "@neurosphere/contracts";
import { describe, expect, it } from "vitest";
import {
  DEFAULT_BUDGET,
  assertValidBudget,
  budgetParams,
  flattenPages,
  nextCursor,
  truncationNotice,
} from "./pagination.js";

const page = (over: Partial<Page>): Page => ({
  limit: 10,
  returned: 10,
  has_more: false,
  next_cursor: null,
  truncated: false,
  ...over,
});

describe("budgetParams", () => {
  it("emits mandatory budget fields and omits unset optionals", () => {
    expect(budgetParams({ timeout_ms: 5000, limit: 25, max_depth: 2 }, "abc")).toEqual({
      timeout_ms: 5000,
      limit: 25,
      max_depth: 2,
      max_nodes: undefined,
      max_edges: undefined,
      cursor: "abc",
    });
  });

  it("never includes scope identifiers", () => {
    const keys = Object.keys(
      budgetParams({ ...DEFAULT_BUDGET, max_nodes: 100, max_edges: 200 }, null),
    );
    expect(keys).not.toContain("domain_id");
    expect(keys).not.toContain("customer_id");
    expect(keys).not.toContain("cursor");
  });

  it.each([
    { timeout_ms: 0, limit: 1, max_depth: 0 },
    { timeout_ms: 1, limit: 1.5, max_depth: 0 },
    { timeout_ms: 1, limit: 1, max_depth: -1 },
    { timeout_ms: 1, limit: 1, max_depth: 0, max_nodes: -5 },
  ])("rejects invalid budget %j", (budget) => {
    expect(() => assertValidBudget(budget)).toThrow(RangeError);
  });
});

describe("page helpers", () => {
  it("nextCursor stops when there are no more pages", () => {
    expect(nextCursor(page({ has_more: true, next_cursor: "c2" }))).toBe("c2");
    expect(nextCursor(page({ has_more: false }))).toBeUndefined();
  });

  it("flattenPages concatenates items in order", () => {
    expect(
      flattenPages([
        { items: [1, 2], page: page({}) },
        { items: [3], page: page({}) },
      ]),
    ).toEqual([1, 2, 3]);
  });

  it("labels truncated results and only those", () => {
    expect(truncationNotice(page({}))).toBeUndefined();
    expect(truncationNotice(page({ truncated: true, truncation_reason: "timeout_ms" }))).toContain(
      "timeout_ms",
    );
    expect(truncationNotice(page({ truncated: true }))).toContain("Partial result");
  });
});
