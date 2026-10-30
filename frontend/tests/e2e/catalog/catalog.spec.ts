import AxeBuilder from "@axe-core/playwright";
import type { Page } from "@playwright/test";
import { expect, test } from "../../e2e-support/fixtures.ts";
import { WCAG_TAGS } from "../../helpers/axe.ts";
import { DOMAIN_OK } from "../../mock-api/server.ts";

// PRP-31 item 3: the catalog explorer against the mock API. The stub caller is a Viewer, so
// reads work and changes are 403; the change flows swap the bearer token to Admin on the catalog
// calls only (the mock reads the persona from the token suffix, standing in for catalog.curate).

const API = "**/api/v1/catalog/**";
const ADMIN_TOKEN = "ns-e2e-fake-token.Admin";
const CONTESTED = "commercial:e2e:catalog:owner:contested-team";
const D = encodeURIComponent(DOMAIN_OK);

async function actAsAdmin(page: Page): Promise<void> {
  await page.route(API, (route) =>
    route.continue({
      headers: { ...route.request().headers(), authorization: `Bearer ${ADMIN_TOKEN}` },
    }),
  );
}

async function axeViolations(page: Page) {
  const results = await new AxeBuilder({ page })
    .withTags([...WCAG_TAGS])
    .exclude("[data-tabster-dummy]")
    .analyze();
  return results.violations.map((v) => ({ id: v.id, impact: v.impact, nodes: v.nodes.length }));
}

test("search leads to the entity, a recertify hits a 409, reloads and then succeeds", async ({
  page,
}) => {
  await actAsAdmin(page);
  await page.goto(`/catalog?domain_id=${D}`);
  // The list is clamped to 4 per page by the mock, so the count carries a "+".
  await expect(page.getByTestId("entity-count")).toContainText("4+ entities");
  await page.getByRole("textbox", { name: "Search entities" }).fill("contested");
  await page.getByTestId("search-submit").click();
  const row = page.getByTestId("entity-row");
  await expect(row).toHaveCount(1);
  await row.getByRole("link").click();

  await expect(page).toHaveURL(
    new RegExp(`/catalog/entity\\?.*entity_id=${encodeURIComponent(CONTESTED)}`),
  );
  await expect(page.getByTestId("entity-etag")).toBeVisible();
  const before = (await page.getByTestId("entity-etag").textContent()) ?? "";

  await page.getByTestId("recertify-open").click();
  await expect(page.getByTestId("change-target")).toHaveText(CONTESTED);
  await page.getByRole("textbox", { name: /Reason/ }).fill("annual review");
  await page.getByRole("button", { name: "Confirm change" }).click();

  await expect(page.getByTestId("change-error")).toContainText("changed since you opened it");
  await expect(page.getByTestId("change-version")).not.toHaveText(before);
  await page.getByRole("button", { name: "Confirm change" }).click();
  await expect(page.getByTestId("change-done")).toContainText("Recertified");
});

test("lineage rows link to the edge page with an encoded id and to the map", async ({ page }) => {
  const agent = "commercial:e2e:catalog:agent:sample-agent";
  await page.goto(`/catalog/entity?domain_id=${D}&entity_id=${encodeURIComponent(agent)}`);
  const row = page.getByTestId("neighbor-row").first();
  await expect(row).toBeVisible();
  const edge = row.getByRole("link").first();
  await expect(edge).toHaveAttribute("href", /\/catalog\/edge\?edge_id=commercial%3Ae2e%3Aedge%3A/);
  await expect(row.getByRole("link", { name: "Show on map" })).toHaveAttribute(
    "href",
    `/map?domain_id=${D}`,
  );
});

test("the recertification queue and stale-agent flow are forbidden for a viewer on confirm", async ({
  page,
}) => {
  await page.goto(`/catalog/recertifications?domain_id=${D}`);
  await expect(page.getByTestId("recert-row").first()).toBeVisible();
  await expect(page.getByTestId("recert-row").first()).toContainText(DOMAIN_OK);

  await page.goto(`/catalog/stale-agents?domain_id=${D}`);
  await page.getByTestId("dry-run").click();
  await expect(page.getByTestId("candidate-row")).toHaveCount(2);
  await page.getByTestId("confirm-open").click();
  await page.getByTestId("confirm-submit").click();
  await expect(page.getByTestId("confirm-dialog-error")).toContainText("declined");
});

test("an administrator confirms the stale-agent plan and sees per-item outcomes", async ({
  page,
}) => {
  await actAsAdmin(page);
  await page.goto(`/catalog/stale-agents?domain_id=${D}`);
  await page.getByTestId("dry-run").click();
  await expect(page.getByTestId("plan-id")).toHaveText("plan-e2e-0001");
  await page.getByTestId("confirm-open").click();
  await page.getByTestId("confirm-submit").click();
  const rows = page.getByTestId("outcome-row");
  await expect(rows).toHaveCount(2);
  await expect(rows.nth(0)).toContainText("Marked");
  await expect(rows.nth(1)).toContainText("Failed");
});

for (const mode of ["light", "dark", "high-contrast"] as const) {
  test(`catalog pages have no axe violations in ${mode}`, async ({ page }) => {
    await page.addInitScript((themeName) => {
      window.localStorage.setItem(
        "ns.theme",
        JSON.stringify({ packId: "default", themeName, styleId: "enterprise-fluent" }),
      );
    }, mode);
    await page.goto(`/catalog?domain_id=${D}`);
    await expect(page.getByTestId("entity-row").first()).toBeVisible();
    expect(await axeViolations(page)).toEqual([]);

    const agent = encodeURIComponent("commercial:e2e:catalog:agent:sample-agent");
    await page.goto(`/catalog/entity?domain_id=${D}&entity_id=${agent}`);
    await expect(page.getByTestId("impact-row").first()).toBeVisible();
    expect(await axeViolations(page)).toEqual([]);

    await page.goto(`/catalog/recertifications?domain_id=${D}`);
    await expect(page.getByTestId("recert-row").first()).toBeVisible();
    expect(await axeViolations(page)).toEqual([]);

    await page.goto(`/catalog/stale-agents?domain_id=${D}`);
    await page.getByTestId("dry-run").click();
    await expect(page.getByTestId("candidate-row").first()).toBeVisible();
    expect(await axeViolations(page)).toEqual([]);
  });
}
