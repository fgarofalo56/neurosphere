import { readFile } from "node:fs/promises";
import AxeBuilder from "@axe-core/playwright";
import type { Page } from "@playwright/test";
import { expect, test } from "../../e2e-support/fixtures.ts";
import { WCAG_TAGS } from "../../helpers/axe.ts";
import {
  DEPLOY_SUB_HIDDEN,
  DEPLOY_SUB_VISIBLE,
  DEPLOY_VISIBILITY_NOTE,
} from "../../mock-api/features/deploy.ts";

// PRP-31 item 7: scan -> choices -> plan against the mock API, and the capability matrix.
// The page has no apply control; the manifest is the only output and it is a local download.

const MODES = ["light", "dark", "high-contrast"] as const;

async function axeViolations(page: Page) {
  const results = await new AxeBuilder({ page })
    .withTags([...WCAG_TAGS])
    .exclude("[data-tabster-dummy]")
    .analyze();
  return results.violations.map((v) => ({ id: v.id, impact: v.impact, nodes: v.nodes.length }));
}

async function runScan(page: Page): Promise<void> {
  await page.getByLabel(/Subscription ids/).fill(`${DEPLOY_SUB_VISIBLE}\n${DEPLOY_SUB_HIDDEN}`);
  await page.getByLabel(/Consent record id/).fill("consent-e2e-1");
  await page.getByLabel(/Attestation reference/).fill("ticket-4711");
  await page.getByTestId("scan-run").click();
  await expect(page.getByTestId("visibility-note")).toContainText(DEPLOY_VISIBILITY_NOTE);
}

test("scan, choose and plan; shows the disabled row and downloads the manifest", async ({
  page,
}) => {
  await page.goto("/deploy");
  await expect(page.getByRole("heading", { level: 1, name: "Deployment" })).toBeVisible();
  await runScan(page);
  await expect(page.getByTestId("scan-sub")).toHaveCount(2);
  await expect(page.getByTestId("scan-sub").nth(1)).toHaveAttribute("data-status", "not_visible");

  await page.getByTestId("step-next").click();
  await page.getByRole("radio", { name: "government" }).click();
  await expect(page.getByRole("radio", { name: "eastus", exact: true })).toHaveCount(0);

  await page.getByTestId("step-next").click();
  await page.getByTestId("plan-build").click();
  await expect(page.getByTestId("plan-row")).toHaveCount(12);
  const disabled = page.locator('[data-testid="plan-row"][data-status="disabled"]');
  await expect(disabled).toHaveCount(1);
  await expect(disabled).toContainText("The plan does not route to Commercial");
  await expect(page.getByText("needs_consent").first()).toBeVisible();
  await expect(page.getByText("neurosphere_created").first()).toBeVisible();

  // No control may apply, provision or delete.
  await expect(page.getByRole("button", { name: /apply|provision|delete|execute/i })).toHaveCount(
    0,
  );

  const download = page.waitForEvent("download");
  await page.getByTestId("manifest-download").click();
  const file = await download;
  expect(file.suggestedFilename()).toBe("deploy-mock-manifest.json");
  const path = await file.path();
  const manifest = JSON.parse(await readFile(path, "utf8")) as { deployment_id: string };
  expect(manifest.deployment_id).toBe("deploy-mock");

  const stored = await page.evaluate(() => JSON.stringify({ ...window.localStorage }));
  expect(stored).not.toContain(DEPLOY_SUB_VISIBLE);
});

test("capabilities: unverified and unavailable rows are disabled, Government shows no Commercial row", async ({
  page,
}) => {
  await page.goto("/deploy/capabilities");
  await expect(page.getByTestId("cap-row").first()).toBeVisible();
  await page.getByRole("radio", { name: "government" }).click();
  await page.getByTestId("cap-apply").click();
  await expect(page.getByTestId("cap-row")).toHaveCount(3);
  await expect(page.getByTestId("cap-row").filter({ hasText: "commercial" })).toHaveCount(0);
  const disabled = page.locator('[data-testid="cap-row"][data-enabled="false"]');
  await expect(disabled).toHaveCount(2);
  await expect(page.getByText("Availability is unverified").first()).toBeVisible();
  await expect(page.getByRole("columnheader", { name: "Availability" })).toBeVisible();
  await expect(page.getByRole("columnheader", { name: "GA status" })).toBeVisible();
  await expect(page.getByRole("columnheader", { name: /Authorization scope/ })).toBeVisible();
});

for (const mode of MODES) {
  test(`deployment pages have no axe violations in ${mode}`, async ({ page }) => {
    await page.addInitScript((themeName) => {
      window.localStorage.setItem("ns.theme", JSON.stringify({ packId: "default", themeName }));
    }, mode);
    await page.goto("/deploy");
    await runScan(page);
    await page.waitForLoadState("networkidle");
    expect(await axeViolations(page)).toEqual([]);

    await page.getByTestId("step-next").click();
    expect(await axeViolations(page)).toEqual([]);
    await page.getByTestId("step-next").click();
    await page.getByTestId("plan-build").click();
    await expect(page.getByTestId("plan-row").first()).toBeVisible();
    expect(await axeViolations(page)).toEqual([]);

    await page.goto("/deploy/capabilities");
    await expect(page.getByTestId("cap-row").first()).toBeVisible();
    expect(await axeViolations(page)).toEqual([]);
  });
}
