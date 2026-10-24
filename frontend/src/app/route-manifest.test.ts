import { describe, expect, it, vi } from "vitest";
import type { RouteObject } from "react-router";

// The real route objects import the map feature, whose WebGL renderer crashes jsdom on import.
vi.mock("../features/map/renderer", () => ({ createMapRenderer: vi.fn() }));

import { appRoutes } from "./appRoutes";
import manifest from "./route-manifest.json";
import { createAppRoutes } from "./routes";

/** Every concrete route pattern in a route tree, `*` excluded, index routes as their parent. */
function collectRoutePatterns(routes: readonly RouteObject[], parent = ""): string[] {
  const out: string[] = [];
  for (const route of routes) {
    if (route.path === "*") continue;
    const own = route.path ?? "";
    const joined = own.startsWith("/") ? own : `${parent.replace(/\/$/, "")}/${own}`;
    const pattern = joined === "" ? "/" : joined.replace(/(.)\/$/, "$1");
    if (route.index === true || route.path !== undefined) out.push(pattern);
    if (route.children !== undefined) out.push(...collectRoutePatterns(route.children, pattern));
  }
  return out;
}

describe("route manifest", () => {
  it("lists every route the app registers (update route-manifest.json when this fails)", () => {
    const actual = [...new Set(collectRoutePatterns(createAppRoutes({ extraRoutes: appRoutes })))]
      .filter((p) => !p.includes("*"))
      .sort();
    expect(
      manifest.routes,
      "route-manifest.json is out of date: update it to the sorted list of routes in " +
        "src/app/appRoutes.ts (the accessibility suite reads it and needs a sample URL for each)",
    ).toEqual(actual);
  });

  it("is sorted and free of duplicates", () => {
    expect(manifest.routes).toEqual([...new Set(manifest.routes)].sort());
  });

  it("includes the sandbox page and the home route", () => {
    expect(manifest.routes).toContain("/");
    expect(manifest.routes).toContain("/sandbox");
  });
});
