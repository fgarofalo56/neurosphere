import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import type { Page } from "@playwright/test";
import { expect, test, type ApiAnswer } from "./fixtures.ts";

/**
 * PRP-29 item 11, MANUAL gate (see playwright.real-stack.config.ts): every route in
 * `src/app/route-manifest.json` is opened against the compose stack after a real Entra sign-in.
 * Each page must render, show no demo banner and cause no 4xx/5xx except the explicitly expected
 * answers below. Pages that show data in the seeded stack must show it.
 *
 * Gaps that the seeded stack has today (the same ones tests/integration/real_stack/
 * test_manifest_routes.py lists as KNOWN_EMPTY) are named in `NO_DATA` with the reason; they are
 * reported OPEN, not hidden. The run needs a human operator who holds a role in the policy store
 * (`make grant-operator`, docs/dev/local-setup.md) and was seeded with `make stack-up`.
 */

interface Expected {
  /** An answer the page is allowed to cause: `status` on a path that starts with `pathPrefix`. */
  readonly status: number;
  readonly pathPrefix: string;
  readonly why: string;
}

interface Entry {
  readonly route: string;
  /** Open this route by following a link from a list route (detail pages need an id). */
  readonly via?: { readonly list: string; readonly link: string };
  /** `data-testid` of a row that must be visible when the page has data. */
  readonly rows?: string;
  readonly expected?: readonly Expected[];
}

const workspace = (persona: string): Entry => ({
  route: `/workspaces/${persona}`,
  expected: [
    {
      status: 403,
      pathPrefix: `/api/v1/workspaces/${persona}`,
      why: "the operator may not hold this role; the page then shows its forbidden state",
    },
  ],
});

const ENTRIES: readonly Entry[] = [
  { route: "/" },
  { route: "/actions", rows: "action-row" },
  {
    route: "/actions/detail",
    via: { list: "/actions", link: "a[href^='/actions/detail']" },
  },
  {
    route: "/actions/propose",
    via: { list: "/actions", link: "a[href^='/actions/propose']" },
  },
  { route: "/catalog/publication" },
  { route: "/dashboards/cost" },
  { route: "/dashboards/coverage" },
  { route: "/dashboards/latency" },
  { route: "/gateways" },
  { route: "/map" },
  { route: "/map/table" },
  { route: "/mcp-admin", rows: "server-row" },
  {
    route: "/mcp-admin/server",
    via: { list: "/mcp-admin", link: "a[href^='/mcp-admin/server']" },
  },
  { route: "/quality" },
  { route: "/recommendations", rows: "recommendation-row" },
  {
    route: "/recommendations/detail",
    via: { list: "/recommendations", link: "a[href^='/recommendations/detail']" },
  },
  { route: "/reconciliation" },
  { route: "/replay/traces" },
  { route: "/reports", rows: "report-row" },
  {
    route: "/reports/view",
    via: { list: "/reports", link: "a[href^='/reports/view']" },
  },
  { route: "/review", rows: "review-row" },
  {
    route: "/review/item",
    via: { list: "/review", link: "a[href^='/review/item']" },
  },
  {
    route: "/sandbox",
    expected: [
      {
        status: 503,
        pathPrefix: "/api/v1/sandbox/status",
        why: "sandbox mode reads the isolated sandbox database, which only `make seed` creates",
      },
    ],
  },
  workspace("admin"),
  workspace("analyst"),
  workspace("auditor"),
  workspace("steward"),
  workspace("viewer"),
];

/**
 * Routes whose seeded data is known to be absent for the operator: the reason, as reported.
 * Empty since PRP-29 E2 (recent-dated seed, catalog entities, an operator report). The review
 * queue needs a reviewer role: grant the operator `domain_steward` as well as `admin`.
 */
const NO_DATA: Readonly<Record<string, string>> = {};

const manifest = JSON.parse(
  readFileSync(resolve(process.cwd(), "src/app/route-manifest.json"), "utf8"),
) as { routes: string[] };

async function readableDomains(page: Page): Promise<string[]> {
  const answered = page.waitForResponse(
    (r) => r.url().includes("/api/v1/me/domains") && r.status() === 200,
  );
  await page.goto("/");
  const body = (await (await answered).json()) as { items: { domain_id: string }[] };
  return body.items.map((item) => item.domain_id);
}

const withDomain = (route: string, domain: string): string =>
  `${route}?domain_id=${encodeURIComponent(domain)}`;

function unexpected(answers: readonly ApiAnswer[], expected: readonly Expected[]): string[] {
  return answers
    .filter((a) => a.status >= 400)
    .filter((a) => !expected.some((e) => e.status === a.status && a.path.startsWith(e.pathPrefix)))
    .map((a) => `${a.method} ${a.path} -> ${a.status}`);
}

test("the entries cover exactly the route manifest", () => {
  expect(ENTRIES.map((e) => e.route).sort()).toEqual([...manifest.routes].sort());
});

for (const entry of ENTRIES) {
  test(`route ${entry.route} renders without demo banner or unexpected errors`, async ({
    visit,
  }, testInfo) => {
    const { page, answers } = visit;
    const domains = await readableDomains(page);
    expect(domains.length).toBeGreaterThan(0);
    const noData = NO_DATA[entry.route];

    let opened = false;
    for (const domain of domains) {
      if (entry.via !== undefined) {
        await page.goto(withDomain(entry.via.list, domain));
        await page.locator("main h1").first().waitFor();
        // The list loads after the heading: settle on a link or the empty state before counting.
        await page.locator(`${entry.via.link}, [data-testid='empty-state']`).first().waitFor();
        const link = page.locator(entry.via.link).first();
        if ((await link.count()) === 0) continue;
        await link.click();
      } else {
        await page.goto(withDomain(entry.route, domain));
        if (entry.rows !== undefined) {
          await page.locator("main h1").first().waitFor();
          // The list settles on rows or on its empty state.
          await page
            .locator(`[data-testid='${entry.rows}'], [data-testid='empty-state']`)
            .first()
            .waitFor();
          if ((await page.getByTestId(entry.rows).count()) === 0) continue;
        }
      }
      opened = true;
      break;
    }

    if (!opened) {
      testInfo.annotations.push({ type: "OPEN", description: noData ?? "no page with data" });
      test.skip(noData !== undefined, noData ?? "");
      throw new Error(`no readable domain has data for ${entry.route}`);
    }

    if (noData !== undefined) {
      testInfo.annotations.push({ type: "OPEN", description: `renders, but empty: ${noData}` });
    }
    await expect(page.locator("main h1").first()).toBeVisible();
    await expect(page.getByTestId("demo-banner")).toHaveCount(0);
    await expect(page.getByTestId("error-state")).toHaveCount(0);
    await page.waitForLoadState("networkidle");
    if (entry.rows !== undefined) {
      await expect(page.getByTestId(entry.rows).first()).toBeVisible();
    }
    expect(unexpected(answers, entry.expected ?? [])).toEqual([]);
  });
}
