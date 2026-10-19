import { expect, test } from "../../e2e-support/fixtures.ts";
import { axeViolations } from "../../helpers/axe.ts";
import {
  ANALYTICS_DISABLED_REASON,
  DOMAIN_ANALYTICS_DOWN,
  FIXTURE_LAG_SECONDS,
} from "../../mock-api/server.ts";

// PRP-14 item 5, analytics-down: the batch analytics backend is disabled, the hot aggregates keep
// serving, and the UI says so with the reason instead of going blank.

const url = `/dashboards/cost?domain_id=${encodeURIComponent(DOMAIN_ANALYTICS_DOWN)}`;

test("data stays rendered while the analytics chip shows disabled with its reason", async ({
  page,
}) => {
  const api = page.waitForResponse(
    (r) => r.url().includes("/api/v1/dashboards/domains/") && r.status() === 200,
  );
  await page.goto(url);
  const body = (await (await api).json()) as {
    analytics: { state: string; reason: string | null };
    series: unknown[];
  };
  expect(body.analytics.state).toBe("disabled");
  expect(body.series.length).toBeGreaterThan(0);

  // Continuity: figures, badges, lag and coverage metadata are all still there.
  await expect(page.getByTestId("series-block").first()).toBeVisible();
  await expect(page.getByTestId("kind-badge").first()).toBeVisible();
  await expect(page.getByTestId("price-version-badge").first()).toBeVisible();
  await expect(page.getByTestId("lag")).toHaveText(`${FIXTURE_LAG_SECONDS} s`);

  // And the disabled state is explicit, with the capability-matrix reason, not hidden.
  const chip = page.getByTestId("analytics-chip");
  await expect(chip).toContainText("analytics: disabled");
  await expect(chip.getByTestId("analytics-reason")).toContainText(ANALYTICS_DISABLED_REASON);
  // No error or forbidden state: analytics being down is not a failure of the dashboard.
  await expect(page.getByTestId("error-state")).toHaveCount(0);
  await expect(page.getByTestId("forbidden-state")).toHaveCount(0);
});

test("reconciliation also keeps serving while analytics is down", async ({ page }) => {
  await page.goto(`/reconciliation?domain_id=${encodeURIComponent(DOMAIN_ANALYTICS_DOWN)}`);
  await expect(page.getByTestId("reconciliation-view")).toBeVisible();
  await expect(page.getByTestId("source-billing").getByTestId("coverage")).toHaveText("unknown");
});

test("the analytics-down view has no axe violations", async ({ page }) => {
  await page.goto(url);
  await expect(page.getByTestId("analytics-chip")).toContainText("analytics: disabled");
  expect(await axeViolations(page)).toEqual([]);
});
