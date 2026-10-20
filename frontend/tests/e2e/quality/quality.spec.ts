import { expect, test } from "../../e2e-support/fixtures.ts";
import { axeViolations } from "../../helpers/axe.ts";
import {
  DOMAIN_FORBIDDEN,
  DOMAIN_NO_PILOT,
  DOMAIN_OK,
  PILOT_TARGET_LABEL,
} from "../../mock-api/server.ts";

// PRP-16 item 6: the quality page through the stubbed sign-in against the mock API. The domain
// rides in the APP url (`domain_id`) and in the API PATH. Judge scores are shown with their
// uncertainty and calibration state; unknown is "unknown", never 0; no wording implies a guarantee.

function qualityUrl(domain: string, extra = ""): string {
  return `/quality?domain_id=${encodeURIComponent(domain)}${extra}`;
}

test.describe("populated domain", () => {
  test("renders the pilot rate with its interval and the exact target label", async ({ page }) => {
    const api = page.waitForResponse(
      (r) => r.url().includes("/api/v1/evaluation/domains/") && r.status() === 200,
    );
    await page.goto(qualityUrl(DOMAIN_OK));
    const response = await api;
    expect(new URL(response.url()).pathname).toBe(
      `/api/v1/evaluation/domains/${encodeURIComponent(DOMAIN_OK)}/quality`,
    );
    expect(new URL(response.url()).searchParams.has("domain_id")).toBe(false);

    await expect(page.getByRole("heading", { level: 1, name: "Agent quality" })).toBeVisible();
    await expect(page.getByTestId("pilot-target")).toHaveText("pilot-set target: at least 90%");
    await expect(page.getByTestId("pilot-target")).toHaveText(PILOT_TARGET_LABEL);
    await expect(page.getByTestId("pilot-value")).toHaveText("87.5%");
    await expect(page.getByTestId("pilot-interval")).toHaveText("0.7389 to 0.9454 (95% level)");
    await expect(page.getByTestId("pilot-n")).toHaveText("40");
  });

  test("unknown metrics render 'unknown', not 0; a measured zero stays 0%", async ({ page }) => {
    await page.goto(qualityUrl(DOMAIN_OK));
    const grounded = page.getByTestId("trend-groundedness").getByTestId("trend-row");
    await expect(grounded).toHaveCount(2);
    // The online groundedness point has no value: unknown, with no fabricated interval.
    const online = grounded.filter({ hasText: "programmatic" });
    await expect(online.getByTestId("trend-value")).toHaveText("unknown");
    await expect(online).toContainText("not estimable");

    const rows = page.getByTestId("coverage-row");
    await expect(
      rows.filter({ hasText: "restricted" }).getByTestId("coverage-fraction"),
    ).toHaveText("0%");
    const unmapped = rows.filter({ hasText: "unmapped" });
    await expect(unmapped.getByTestId("coverage-fraction")).toHaveText("unknown");
  });

  test("an uncalibrated judge score carries a visible marker", async ({ page }) => {
    await page.goto(qualityUrl(DOMAIN_OK));
    const row = page
      .getByTestId("trend-tool_correctness")
      .getByTestId("trend-row")
      .filter({ hasText: "judge-b" });
    await expect(row.getByTestId("calibration-state")).toHaveText("Uncalibrated");
    await expect(row).toContainText("not validated against human labels");
    const calibrated = page.getByTestId("trend-groundedness").getByTestId("trend-row").first();
    await expect(calibrated.getByTestId("calibration-state")).toHaveText("Calibrated");
  });

  test("missing labels and the drift alert are visible", async ({ page }) => {
    await page.goto(qualityUrl(DOMAIN_OK));
    await expect(page.getByTestId("missing-labels")).toHaveText("6");
    const drift = page.getByTestId("drift-row");
    await expect(drift).toHaveCount(1);
    await expect(drift).toContainText("groundedness");
    await expect(page.getByTestId("drift-empty")).toHaveCount(0);
  });

  test("no wording implies a guarantee or an SLA", async ({ page }) => {
    await page.goto(qualityUrl(DOMAIN_OK));
    await expect(page.getByTestId("pilot-rate")).toBeVisible();
    const text = (await page.locator("main").innerText()).toLowerCase();
    expect(text).not.toMatch(/guarantee|\bsla\b|service level|assured|certif/);
  });

  test("has no axe violations", async ({ page }) => {
    await page.goto(qualityUrl(DOMAIN_OK));
    await expect(page.getByTestId("pilot-value")).toBeVisible();
    expect(await axeViolations(page)).toEqual([]);
  });
});

test.describe("nothing estimable", () => {
  test("everything is 'unknown', never 0, and the reason is stated", async ({ page }) => {
    await page.goto(qualityUrl(DOMAIN_NO_PILOT));
    await expect(page.getByTestId("pilot-target")).toHaveText(PILOT_TARGET_LABEL);
    await expect(page.getByTestId("pilot-value")).toHaveText("unknown");
    await expect(page.getByTestId("pilot-interval")).toHaveCount(0);
    await expect(page.getByTestId("pilot-reason")).toBeVisible();
    await expect(page.getByTestId("trends-empty")).toBeVisible();
    await expect(page.getByTestId("missing-labels")).toHaveText("unknown");
    await expect(page.getByTestId("drift-empty")).toBeVisible();
  });

  test("has no axe violations", async ({ page }) => {
    await page.goto(qualityUrl(DOMAIN_NO_PILOT));
    await expect(page.getByTestId("pilot-reason")).toBeVisible();
    expect(await axeViolations(page)).toEqual([]);
  });
});

test.describe("forbidden domain", () => {
  test("shows the forbidden state, not an empty page", async ({ page }) => {
    const api = page.waitForResponse((r) => r.url().includes("/api/v1/evaluation/domains/"));
    await page.goto(qualityUrl(DOMAIN_FORBIDDEN));
    expect((await api).status()).toBe(403);
    await expect(page.getByTestId("forbidden-state")).toBeVisible();
    await expect(page.getByTestId("forbidden-state")).toContainText(
      "You do not have access to this domain",
    );
    await expect(page.getByTestId("pilot-rate")).toHaveCount(0);
    await expect(page.getByTestId("trend-row")).toHaveCount(0);
  });
});

test("navigation lists the quality entry", async ({ page }) => {
  await page.goto("/");
  const nav = page.getByRole("navigation", { name: "Primary" });
  await expect(nav.getByRole("link", { name: "Quality" })).toBeVisible();
});
