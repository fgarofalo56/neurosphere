import AxeBuilder from "@axe-core/playwright";
import type { Page } from "@playwright/test";
import { expect, test } from "../../e2e-support/fixtures.ts";
import { WCAG_TAGS } from "../../helpers/axe.ts";
import { DOMAIN_OK } from "../../mock-api/server.ts";

// PRP-43 item 7: the relationship review queue against the mock API. The stub session is a
// Viewer, so the spec swaps the bearer token per call (as curation.spec.ts does): the mock stands
// in for the API's catalog.curate check. The page never decides anything.

const STEWARD = "ns-e2e-fake-token.Steward";

async function actAs(page: Page, token: string): Promise<void> {
  await page.route("**/api/v1/me/domains", async (route) => {
    const response = await route.fetch();
    const body = (await response.json()) as {
      items: { domain_id: string; permissions: string[] }[];
    };
    for (const item of body.items) {
      if (item.domain_id === DOMAIN_OK) item.permissions = [...item.permissions, "catalog.curate"];
    }
    await route.fulfill({ response, json: body });
  });
  await page.route("**/api/v1/catalog/**", (route) =>
    route.continue({
      headers: { ...route.request().headers(), authorization: `Bearer ${token}` },
    }),
  );
}

async function axeBlocking(page: Page) {
  const results = await new AxeBuilder({ page })
    .withTags([...WCAG_TAGS])
    .exclude("[data-tabster-dummy]")
    .analyze();
  return results.violations
    .filter((v) => v.impact === "serious" || v.impact === "critical")
    .map((v) => ({ id: v.id, impact: v.impact, targets: v.nodes.map((n) => n.target.join(" ")) }));
}

test("a steward sees open items, resolves one, and the list reloads", async ({ page }) => {
  await actAs(page, STEWARD);
  await page.goto(`/catalog/review-queue?domain_id=${encodeURIComponent(DOMAIN_OK)}`);
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  const rows = page.getByTestId("review-row");
  await expect(rows).toHaveCount(2);
  expect(await axeBlocking(page)).toEqual([]);

  await rows.first().getByTestId("resolve-open").click();
  const dialog = page.getByTestId("change-confirm-dialog");
  await expect(dialog).toBeVisible();
  await expect(dialog.getByRole("textbox")).toHaveCount(0);
  await dialog.getByRole("button", { name: "Confirm change" }).click();
  await expect(page.getByTestId("resolve-done")).toBeVisible();
  await expect(rows).toHaveCount(1);
});

test("a viewer without catalog.curate sees the forbidden state", async ({ page }) => {
  await page.goto(`/catalog/review-queue?domain_id=${encodeURIComponent(DOMAIN_OK)}`);
  await expect(page.getByTestId("forbidden-state")).toBeVisible();
  expect(await axeBlocking(page)).toEqual([]);
});
