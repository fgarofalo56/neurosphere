import { readFile } from "node:fs/promises";
import AxeBuilder from "@axe-core/playwright";
import type { Page } from "@playwright/test";
import { expect, test } from "../../e2e-support/fixtures.ts";
import { WCAG_TAGS } from "../../helpers/axe.ts";
import {
  DEPLOY_APPLY_DENIED_DOMAIN,
  DEPLOY_APPLY_OFF_DOMAIN,
  DEPLOY_APPLY_REFUSED_DOMAIN,
  DEPLOY_PLAN_HASH,
  DEPLOY_SUB_HIDDEN,
  DEPLOY_SUB_VISIBLE,
  DEPLOY_VISIBILITY_NOTE,
} from "../../mock-api/features/deploy.ts";

// PRP-31 item 7: scan -> choices -> plan against the mock API, and the capability matrix.
// Steps 1-3 have no apply control; the manifest is the only output and it is a local download.

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

// PRP-08 item 13: step 4 (approve, apply, uninstall preview) against the mock of the item 12
// routes. The mock domain selects the variant: default (enabled, apply only drafts), not
// configured (503), denied (403) and refused (422).

const FINANCE = "commercial:contoso:catalog:domain:finance";

/** Scan, make every service create-or-reuse-owned (no shared reuse), plan, open step 4. */
async function reachApply(page: Page, domain: string): Promise<void> {
  await page.goto(`/deploy?domain_id=${encodeURIComponent(domain)}`);
  await runScan(page);
  await page.getByTestId("step-next").click();
  const row = page.locator('[data-testid="choice-row"][data-service="api_management"]');
  await row.getByRole("radio", { name: "create" }).click();
  await page.getByTestId("step-next").click();
  await page.getByTestId("plan-build").click();
  await expect(page.getByTestId("plan-row").first()).toBeVisible();
  await page.getByTestId("step-next").click();
  await expect(page.getByTestId("step-title")).toContainText("Approve and apply");
}

async function approve(page: Page): Promise<void> {
  await page.getByLabel(/Subscription id(?!s)/).fill(DEPLOY_SUB_VISIBLE);
  await page.getByLabel(/Resource group/).fill("rg-neurosphere");
  await page.getByRole("textbox", { name: "Region" }).fill("eastus");
  await page.getByTestId("approve-run").click();
}

test("step 4: approval comes from the API, apply only drafts and is not shown as applied", async ({
  page,
}) => {
  await reachApply(page, FINANCE);
  await expect(page.getByTestId("approval-status")).toHaveText("not approved");
  await expect(page.getByTestId("apply-run")).toBeDisabled();

  await approve(page);
  await expect(page.getByTestId("approval-status")).toHaveText("approved");
  await expect(page.getByTestId("approval-state")).toContainText(DEPLOY_PLAN_HASH);
  await expect(page.getByTestId("approved-resource").first()).toBeVisible();

  await page.getByTestId("apply-run").click();
  await expect(page.getByTestId("apply-result")).toContainText(DEPLOY_PLAN_HASH);
  await expect(page.getByTestId("apply-diff")).toContainText("add /resources/0");
  await expect(page.getByTestId("apply-outcome")).toHaveAttribute("data-applied", "false");
  await expect(page.getByTestId("apply-outcome")).toContainText("Not applied");
  await expect(page.getByText(/Applied and verified/)).toHaveCount(0);
});

test("step 4: uninstall preview lists reused and shared as untouched and cannot delete", async ({
  page,
}) => {
  await reachApply(page, FINANCE);
  await page.getByLabel(/Deployment id to preview/).fill("deploy-mock");
  await page.getByTestId("uninstall-run").click();
  await expect(page.getByTestId("uninstall-result")).toContainText("nothing was deleted");
  const untouched = page.getByTestId("uninstall-untouched");
  await expect(untouched).toHaveCount(2);
  await expect(untouched.nth(0)).toHaveAttribute("data-ownership", "reused");
  await expect(untouched.nth(1)).toHaveAttribute("data-ownership", "shared");
  await expect(page.getByRole("button", { name: /delete|remove|destroy/i })).toHaveCount(0);
});

test("step 4: 503 apply_not_configured is shown as not enabled in this deployment", async ({
  page,
}) => {
  await reachApply(page, DEPLOY_APPLY_OFF_DOMAIN);
  await approve(page);
  await expect(page.getByTestId("apply-not-enabled")).toContainText(
    "not enabled in this deployment",
  );
  await expect(page.getByTestId("approval-status")).toHaveText("not approved");
});

test("step 4: a 403 is shown as a denial", async ({ page }) => {
  await reachApply(page, DEPLOY_APPLY_DENIED_DOMAIN);
  await approve(page);
  await expect(page.getByTestId("apply-forbidden")).toContainText("insufficient_permission");
  await expect(page.getByTestId("approval-status")).toHaveText("not approved");
});

test("step 4: a refused apply shows the reason and no success", async ({ page }) => {
  await reachApply(page, DEPLOY_APPLY_REFUSED_DOMAIN);
  await approve(page);
  await expect(page.getByTestId("approval-status")).toHaveText("approved");
  await page.getByTestId("apply-run").click();
  await expect(page.getByTestId("apply-error")).toContainText("plan_hash_mismatch");
  await expect(page.getByTestId("apply-result")).toHaveCount(0);
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

    await page.getByTestId("step-next").click();
    await expect(page.getByTestId("approval-state")).toBeVisible();
    expect(await axeViolations(page)).toEqual([]);

    await page.goto("/deploy/capabilities");
    await expect(page.getByTestId("cap-row").first()).toBeVisible();
    expect(await axeViolations(page)).toEqual([]);
  });
}
