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
  readonly via?: { readonly list: string; readonly link: string; readonly then?: string };
  /** `data-testid` of a row that must be visible when the page has data. */
  readonly rows?: string;
  /** `data-testid` of the page's empty state; defaults to `empty-state`. */
  readonly empty?: string;
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
  {
    route: "/admin/execution-control",
    expected: [
      {
        status: 403,
        pathPrefix: "/api/v1/actions/emergency-disable",
        why: "reading the switch needs config.manage, which the operator may not hold; the page then shows its forbidden state",
      },
    ],
  },
  // PRP-53: the admin console. OPEN until PRP-38's job seeds a principal and covers these pages;
  // the operator may not hold the deployment-admin scope, and each page then shows its forbidden
  // state (a 403 on the first call of the page).
  {
    route: "/admin/audit",
    expected: [
      {
        status: 403,
        pathPrefix: "/api/v1/audit/",
        why: "audit search needs audit.read; the customer-wide denials and SIEM views need it on the control domain",
      },
    ],
  },
  {
    route: "/admin/domains",
    expected: [
      {
        status: 403,
        pathPrefix: "/api/v1/admin/platform/",
        why: "the domain registry needs the deployment-admin scope, which the operator may not hold",
      },
    ],
  },
  {
    route: "/admin/identity",
    expected: [
      {
        status: 403,
        pathPrefix: "/api/v1/admin/identity/",
        why: "identity administration needs the deployment-admin scope, which the operator may not hold",
      },
    ],
  },
  {
    route: "/admin/identity/principal",
    via: { list: "/admin/identity", link: "a[href^='/admin/identity/principal']" },
    expected: [
      {
        status: 403,
        pathPrefix: "/api/v1/admin/identity/",
        why: "identity administration needs the deployment-admin scope, which the operator may not hold",
      },
    ],
  },
  {
    route: "/admin/system",
    expected: [
      {
        status: 403,
        pathPrefix: "/api/v1/admin/system/",
        why: "system status needs the deployment-admin scope (PRP-48), which the operator may not hold",
      },
    ],
  },
  // PRP-57: admin console part 2. OPEN until PRP-38's job covers these pages; the operator may
  // not hold the deployment-admin scope, and each data page then shows its forbidden state.
  {
    route: "/admin/sources/producers",
    expected: [
      {
        status: 403,
        pathPrefix: "/api/v1/admin/sources/",
        why: "ingest producers need config.manage, which the operator may not hold",
      },
      {
        status: 503,
        pathPrefix: "/api/v1/admin/sources/",
        why: "the producer registry answers 503 when the composed stack has no producer store wired",
      },
    ],
  },
  {
    route: "/admin/sources/connectors",
    expected: [
      {
        status: 403,
        pathPrefix: "/api/v1/admin/sources/",
        why: "connector configurations need config.manage, which the operator may not hold",
      },
    ],
  },
  { route: "/admin/gateways" },
  { route: "/admin/catalog-import" },
  {
    route: "/admin/pricing",
    expected: [
      {
        status: 403,
        pathPrefix: "/api/v1/admin/platform/",
        why: "price sheets and budgets need the deployment-admin scope, which the operator may not hold",
      },
    ],
  },
  {
    route: "/admin/features",
    expected: [
      {
        status: 403,
        pathPrefix: "/api/v1/admin/system/",
        why: "stored settings need the deployment-admin scope, which the operator may not hold",
      },
    ],
  },
  {
    route: "/admin/review-policy",
    expected: [
      {
        status: 403,
        pathPrefix: "/api/v1/admin/platform/",
        why: "the review policy needs the deployment-admin scope, which the operator may not hold",
      },
    ],
  },
  { route: "/actions", rows: "action-row" },
  {
    route: "/actions/detail",
    via: { list: "/actions", link: "a[href^='/actions/detail']" },
  },
  {
    route: "/actions/propose",
    via: { list: "/actions", link: "a[href^='/actions/propose']" },
  },
  {
    route: "/audit",
    expected: [
      {
        status: 403,
        pathPrefix: "/api/v1/audit/",
        why: "the audit log needs the Auditor or Admin role, which the operator may not hold; the page then shows its forbidden state",
      },
    ],
  },
  {
    route: "/compliance",
    expected: [
      {
        status: 403,
        pathPrefix: "/api/v1/",
        why: "the compliance evidence page needs the Auditor role (evidence.read and audit.read), which the operator may not hold; the page then shows its forbidden state",
      },
    ],
  },
  { route: "/compliance/control" },
  { route: "/catalog", rows: "entity-row" },
  {
    // Two hops: catalog list -> entity -> a relationship link on the entity page. An entity with
    // no relationship has no edge link, so the test reports OPEN when no seeded entity has one.
    route: "/catalog/edge",
    via: {
      list: "/catalog",
      link: "a[href^='/catalog/entity']",
      then: "a[href^='/catalog/edge']",
    },
  },
  {
    route: "/catalog/entity",
    via: { list: "/catalog", link: "a[href^='/catalog/entity']" },
  },
  { route: "/catalog/access" },
  { route: "/catalog/publication" },
  { route: "/catalog/recertifications" },
  { route: "/catalog/review-queue" },
  { route: "/catalog/stale-agents" },
  { route: "/dashboards/cost" },
  { route: "/dashboards/coverage" },
  { route: "/dashboards/latency" },
  {
    route: "/deploy",
    // No API call until a scan is submitted, so there is nothing to expect.
  },
  { route: "/deploy/capabilities" },
  { route: "/evaluations", rows: "evaluation-row", empty: "evaluations-empty" },
  {
    route: "/federation",
    expected: [
      {
        status: 403,
        pathPrefix: "/api/v1/federation",
        why: "the federation summary is permission-scoped; without it the page shows its forbidden state",
      },
    ],
  },
  {
    route: "/finops/forecast",
    expected: [
      {
        status: 409,
        pathPrefix: "/api/v1/finops/domains/",
        why: "the dev price sheet prices only synthetic-model, so the seeded world has no price version (price_version_unresolved); the page shows its unavailable state",
      },
    ],
  },
  { route: "/gateways" },
  {
    route: "/gateways/detail",
    via: { list: "/gateways", link: "a[href^='/gateways/detail']" },
    expected: [
      {
        status: 404,
        pathPrefix: "/api/v1/gateways/domains/",
        why: "the seed registers one gateway but no inventory snapshot for it; the page shows its empty inventory state (PRP-38 #209)",
      },
    ],
  },
  { route: "/map" },
  { route: "/map/table" },
  { route: "/mcp-admin", rows: "server-row" },
  {
    route: "/mcp-admin/server",
    via: { list: "/mcp-admin", link: "a[href^='/mcp-admin/server']" },
  },
  { route: "/quality" },
  { route: "/recommendations", rows: "recommendation-row" },
  // PRP-75: the page renders without data; the match itself is exercised by the test below.
  {
    route: "/recommendations/find",
    expected: [
      {
        status: 404,
        pathPrefix: "/api/v1/catalog/completeness",
        why: "the completeness tile is optional; the page then shows 'Not available' (PRP-75)",
      },
    ],
  },
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
 * The review queue needs a reviewer role: grant the operator `domain_steward` as well as `admin`.
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

/** Opens up to 10 first-hop links in turn until one page offers the second-hop link; clicks it. */
async function secondHop(page: Page, first: string, second: string): Promise<boolean> {
  const hrefs = await page
    .locator(first)
    .evaluateAll((els) => els.slice(0, 10).map((el) => el.getAttribute("href") ?? ""));
  for (const href of new Set(hrefs.filter((h) => h !== ""))) {
    await page.goto(href);
    await page.locator("main h1").first().waitFor();
    await page.waitForLoadState("networkidle");
    const next = page.locator(second).first();
    if ((await next.count()) > 0) {
      await next.click();
      return true;
    }
  }
  return false;
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
    const emptyId = entry.empty ?? "empty-state";

    let opened = false;
    for (const domain of domains) {
      if (entry.via !== undefined) {
        await page.goto(withDomain(entry.via.list, domain));
        await page.locator("main h1").first().waitFor();
        // The list loads after the heading: settle on a link or the empty state before counting.
        await page.locator(`${entry.via.link}, [data-testid='${emptyId}']`).first().waitFor();
        const link = page.locator(entry.via.link).first();
        if ((await link.count()) === 0) continue;
        if (entry.via.then === undefined) {
          await link.click();
        } else if (!(await secondHop(page, entry.via.link, entry.via.then))) {
          continue;
        }
      } else {
        await page.goto(withDomain(entry.route, domain));
        if (entry.rows !== undefined) {
          await page.locator("main h1").first().waitFor();
          // The list settles on rows or on its empty state.
          await page
            .locator(`[data-testid='${entry.rows}'], [data-testid='${emptyId}']`)
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
    // A forecast the API cannot price (409) is a stated state, not a retryable error.
    if (
      entry.route === "/finops/forecast" &&
      answers.some((a) => a.status === 409 && a.path.startsWith("/api/v1/finops/domains/"))
    ) {
      await expect(page.getByTestId("forecast-unavailable")).toBeVisible();
    }
  });
}

// PRP-75 item 5: Find an agent against the composed stack. A tagged seed (the PRP-71 demo seed)
// must yield at least one candidate; none is a FAILURE, never a silent skip.
// The original PRD story (5c). The plain stack seed has no tags, so it matches on agent names
// ("Customer Support <role> nnnn"); the PRP-71 demo seed matches on tags and capabilities too.
const MATCH_TASK = "Summarize this customer support ticket";

test("route /recommendations/find ranks a task, records an accept and counts it after reload", async ({
  visit,
}) => {
  const { page } = visit;
  const domains = await readableDomains(page);
  expect(domains.length).toBeGreaterThan(0);
  const acceptsOf = async (): Promise<number> => {
    const card = page
      .getByTestId("match-metrics")
      .getByText("Accepts", { exact: true })
      .locator("..");
    const text = ((await card.textContent()) ?? "").replace("Accepts", "").trim();
    return Number(/(\d+)\s*$/.exec(text)?.[1] ?? Number.NaN);
  };

  // The first readable domain can be the customer control domain, which holds no agents: try each
  // readable domain until one returns a candidate.
  const candidates = page.getByTestId("match-candidate");
  let before = Number.NaN;
  let found = false;
  for (const domain of domains) {
    await page.goto(withDomain("/recommendations/find", domain));
    await expect(page.getByTestId("match-task-input")).toBeVisible();
    await expect(page.getByTestId("match-acceptance-rate")).toBeVisible();
    before = await acceptsOf();
    expect(Number.isFinite(before)).toBe(true);
    await page.getByTestId("match-task-input").fill(MATCH_TASK);
    await page.getByTestId("match-submit").click();
    await page
      .locator(
        "[data-testid='match-candidate'], [data-testid='match-empty'], [data-testid='error-state']",
      )
      .first()
      .waitFor();
    if ((await candidates.count()) > 0) {
      found = true;
      break;
    }
  }
  if (!found) {
    throw new Error(
      `no candidate returned in any of ${String(domains.length)} readable domain(s): no tagged seed, run the PRP-71 demo seed (make demo-up)`,
    );
  }
  await candidates.first().getByTestId("match-accept").click();
  await expect(candidates.first().getByTestId("match-decision")).toHaveText("Accepted");

  await page.reload();
  await expect(page.getByTestId("match-acceptance-rate")).toBeVisible();
  await expect.poll(acceptsOf).toBeGreaterThanOrEqual(before + 1);
});
