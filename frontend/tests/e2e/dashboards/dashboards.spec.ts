import type { Page } from "@playwright/test";
import { expect, test } from "../../e2e-support/fixtures.ts";
import { axeViolations } from "../../helpers/axe.ts";
import {
  DOMAIN_FORBIDDEN,
  DOMAIN_OK,
  ESTIMATED_PRICE_VERSION,
  FIXTURE_LAG_SECONDS,
  FIXTURE_WATERMARK,
  INVOICED_PRICE_VERSION,
} from "../../mock-api/server.ts";

// PRP-14 item 5: the dashboards and reconciliation routes through the stubbed sign-in, against
// the mock API. The domain rides in the APP url (`domain_id`) and in the API PATH.

function dashboardUrl(page: string, domain: string): string {
  return `/dashboards/${page}?domain_id=${encodeURIComponent(domain)}`;
}

function seriesBlock(page: Page, heading: string) {
  return page
    .getByTestId("series-block")
    .filter({ has: page.getByRole("heading", { name: heading }) });
}

test.describe("cost dashboard", () => {
  test("shows unknown, estimated and invoiced badges, price versions and the lag", async ({
    page,
  }) => {
    const api = page.waitForResponse(
      (r) => r.url().includes("/api/v1/dashboards/domains/") && r.status() === 200,
    );
    await page.goto(dashboardUrl("cost", DOMAIN_OK));
    const response = await api;
    // The domain is a path segment, not a scope parameter.
    expect(new URL(response.url()).pathname).toBe(
      `/api/v1/dashboards/domains/${encodeURIComponent(DOMAIN_OK)}/cost`,
    );
    expect(new URL(response.url()).searchParams.has("domain_id")).toBe(false);

    const estimated = seriesBlock(page, "Cost (estimated, USD)");
    const invoiced = seriesBlock(page, "Cost (invoiced, USD)");
    await expect(estimated).toBeVisible();
    await expect(invoiced).toBeVisible();

    // Separate estimated and invoiced series, each with its own badge.
    await expect(estimated.getByTestId("kind-badge").first()).toHaveText("estimated");
    await expect(invoiced.getByTestId("kind-badge").first()).toHaveText("invoiced");

    // The price version is visible without hover, with its effective date.
    await expect(estimated.getByTestId("price-version-badge").first()).toContainText(
      `${ESTIMATED_PRICE_VERSION.id} (effective ${ESTIMATED_PRICE_VERSION.effective_date})`,
    );
    await expect(invoiced.getByTestId("price-version-badge").first()).toContainText(
      `${INVOICED_PRICE_VERSION.id} (effective ${INVOICED_PRICE_VERSION.effective_date})`,
    );

    // A day with no known amount renders exactly "unknown", never 0; the total of the other
    // days is a partial sum flagged incomplete.
    await expect(
      estimated.getByTestId("metric-value").filter({ hasText: /^unknown$/ }),
    ).toHaveCount(1);
    await expect(estimated.getByTestId("incomplete-marker").first()).toBeVisible();
    // A real 0 from the API stays "0".
    await expect(invoiced.getByTestId("metric-value").filter({ hasText: /^0$/ })).toHaveCount(1);
  });

  test("shows the data watermark and lag", async ({ page }) => {
    await page.goto(dashboardUrl("cost", DOMAIN_OK));
    const indicator = page.getByTestId("lag-indicator");
    await expect(indicator).toBeVisible();
    // A Timestamp: the raw ISO value rides in the `datetime` attribute, not as visible text.
    await expect(indicator.getByTestId("watermark").locator("time")).toHaveAttribute(
      "datetime",
      new Date(FIXTURE_WATERMARK).toISOString(),
    );
    await expect(indicator.getByTestId("lag")).toHaveText(`${FIXTURE_LAG_SECONDS} s`);
    await expect(indicator.getByTestId("billing-freshness")).toBeVisible();
    await expect(page.getByTestId("analytics-chip")).toContainText("analytics: available");
  });

  test("draws estimated and invoiced of one currency together in one chart", async ({ page }) => {
    await page.goto(dashboardUrl("cost", DOMAIN_OK));
    const usd = page.getByTestId("chart-panel").filter({ hasText: "Cost in USD" });
    await expect(usd).toBeVisible();
    await expect(usd.getByRole("img").first()).toBeVisible();
    await expect(usd.locator("[data-series]")).toHaveCount(2);
    // The accessible data table stays beside the chart.
    await expect(
      page.getByRole("region", { name: "Cost (estimated, USD) data table" }),
    ).toBeVisible();
  });

  test("has no axe violations", async ({ page }) => {
    await page.goto(dashboardUrl("cost", DOMAIN_OK));
    await expect(page.getByTestId("section-cost")).toBeVisible();
    expect(await axeViolations(page)).toEqual([]);
  });
});

test.describe("latency, errors and coverage dashboards", () => {
  test("latency shows unknown totals (percentiles do not combine) and errors are labelled", async ({
    page,
  }) => {
    await page.goto(dashboardUrl("latency", DOMAIN_OK));
    const p95 = seriesBlock(page, "Latency p95");
    await expect(p95).toBeVisible();
    await expect(p95.getByTestId("metric-value").first()).toHaveText("unknown");
    await expect(page.getByTestId("section-errors")).toBeVisible();
    await expect(seriesBlock(page, "Error rate")).toBeVisible();
  });

  test("coverage renders and has no axe violations", async ({ page }) => {
    await page.goto(dashboardUrl("coverage", DOMAIN_OK));
    await expect(seriesBlock(page, "Coverage")).toBeVisible();
    expect(await axeViolations(page)).toEqual([]);
  });

  test("latency has no axe violations", async ({ page }) => {
    await page.goto(dashboardUrl("latency", DOMAIN_OK));
    await expect(page.getByTestId("section-latency")).toBeVisible();
    expect(await axeViolations(page)).toEqual([]);
  });
});

test.describe("forbidden domain", () => {
  test("dashboards answer 403 and the page shows the forbidden state, not an empty result", async ({
    page,
  }) => {
    const api = page.waitForResponse((r) => r.url().includes("/api/v1/dashboards/domains/"));
    await page.goto(dashboardUrl("cost", DOMAIN_FORBIDDEN));
    expect((await api).status()).toBe(403);
    await expect(page.getByTestId("forbidden-state").first()).toBeVisible();
    await expect(page.getByTestId("series-block")).toHaveCount(0);
  });

  test("reconciliation answers 403 for the same domain", async ({ page }) => {
    const api = page.waitForResponse((r) => r.url().includes("/api/v1/reconciliation/domains/"));
    await page.goto(`/reconciliation?domain_id=${encodeURIComponent(DOMAIN_FORBIDDEN)}`);
    expect((await api).status()).toBe(403);
    await expect(page.getByTestId("forbidden-state")).toBeVisible();
    await expect(page.getByTestId("reconciliation-view")).toHaveCount(0);
  });
});

test.describe("reconciliation view", () => {
  const url = `/reconciliation?domain_id=${encodeURIComponent(DOMAIN_OK)}`;

  test("labels each source's granularity and shows unknown coverage, not 0 percent", async ({
    page,
  }) => {
    const api = page.waitForResponse(
      (r) => r.url().includes("/api/v1/reconciliation/domains/") && r.status() === 200,
    );
    await page.goto(url);
    const response = await api;
    expect(new URL(response.url()).pathname).toBe(
      `/api/v1/reconciliation/domains/${encodeURIComponent(DOMAIN_OK)}`,
    );

    await expect(page.getByTestId("reconciliation-view")).toBeVisible();
    await expect(page.getByTestId("disclaimer")).toContainText("Not all spend is observable");

    const gateway = page.getByTestId("source-gateway");
    await expect(gateway.getByTestId("granularity")).toHaveText("per request");
    await expect(gateway.getByTestId("coverage")).toHaveText("75%");

    // Billing reported vendor totals only: vendor-level label, known amount, unknown coverage.
    const billing = page.getByTestId("source-billing");
    await expect(billing.getByTestId("granularity")).toHaveText("vendor total (not per request)");
    await expect(billing.getByTestId("coverage")).toHaveText("unknown");
    await expect(billing.getByTestId("coverage")).not.toHaveText(/0\s*%/);

    // The reference counts each request once; entries with an unknown amount are counted apart.
    await expect(page.getByTestId("reference-amount")).toContainText("20");
    await expect(page.getByTestId("unknown-remainder")).toContainText("3");
    await expect(page.getByTestId("lag")).toHaveText(`${FIXTURE_LAG_SECONDS} s`);
  });

  test("has no axe violations", async ({ page }) => {
    await page.goto(url);
    await expect(page.getByTestId("reconciliation-view")).toBeVisible();
    expect(await axeViolations(page)).toEqual([]);
  });
});

test("navigation lists the dashboards and reconciliation entries", async ({ page }) => {
  await page.goto("/");
  const nav = page.getByRole("navigation", { name: "Primary" });
  await expect(nav.getByRole("link", { name: "Cost dashboard" })).toBeVisible();
  await expect(nav.getByRole("link", { name: "Reconciliation" })).toBeVisible();
});
