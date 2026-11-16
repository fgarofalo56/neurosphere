import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import {
  ROLE_TILES,
  TILE_ORDER,
  TILE_PERMISSION,
  tileHref,
} from "../../src/features/overview/data";
import { ACTIONS_PATH } from "../../src/features/actions/paths";
import { COST_DASHBOARD_PATH } from "../../src/features/dashboards/paths";
import { REVIEW_PATH } from "../../src/features/review/paths";

/**
 * #95: every tile's permission is a real API permission name. The API list is the `Permission`
 * enum in the core package; the test reads its string values so a rename there fails here.
 */
const PERMISSIONS_SOURCE = resolve(
  import.meta.dirname,
  "../../../packages/core/neurosphere_core/auth/scope/permissions.py",
);

function apiPermissionNames(): Set<string> {
  const text = readFileSync(PERMISSIONS_SOURCE, "utf8");
  const names = new Set<string>();
  for (const match of text.matchAll(/^\s+[A-Z_]+ = "([a-z]+\.[a-z_]+)"$/gm)) {
    if (match[1] !== undefined) names.add(match[1]);
  }
  return names;
}

describe("overview tile permissions", () => {
  it("reads a non-empty API permission list", () => {
    const names = apiPermissionNames();
    expect(names.has("data.read")).toBe(true);
    expect(names.size).toBeGreaterThan(8);
  });

  it("maps every tile a role can see to a permission the API defines", () => {
    const names = apiPermissionNames();
    const shown = new Set(Object.values(ROLE_TILES).flat());
    expect([...shown].sort()).toEqual([...TILE_ORDER].sort());
    for (const tile of TILE_ORDER) expect(names.has(TILE_PERMISSION[tile])).toBe(true);
  });
});

describe("overview links use the feature path constants", () => {
  it("builds the cost, review and awaiting links from the paths modules", () => {
    expect(tileHref("cost", "d")).toBe(`${COST_DASHBOARD_PATH}?domain_id=d`);
    expect(tileHref("review", "d")).toBe(`${REVIEW_PATH}?domain_id=d`);
    expect(tileHref("awaiting", "d")).toBe(`${ACTIONS_PATH}?domain_id=d`);
  });
});
