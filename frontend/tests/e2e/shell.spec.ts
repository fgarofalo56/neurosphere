import AxeBuilder from "@axe-core/playwright";
import type { Page } from "@playwright/test";
import { expect, test } from "../e2e-support/fixtures.ts";
import { WCAG_TAGS } from "../helpers/axe.ts";
import { DOMAIN_OK } from "../mock-api/server.ts";

// PRP-28 item 2: the app shell (grouped navigation, domain switcher, skip link, user menu) against
// the mock API. The stub caller holds only the Viewer role.

/** Same rules as `axeViolations`, minus Fluent's own focus sentinels (see copilot.spec.ts). */
async function axeViolationsIgnoringTabster(page: Page) {
  const results = await new AxeBuilder({ page })
    .withTags([...WCAG_TAGS])
    .exclude("[data-tabster-dummy]")
    .analyze();
  return results.violations.map((v) => ({ id: v.id, impact: v.impact, nodes: v.nodes.length }));
}

const GROUPS: Record<string, string[]> = {
  Overview: ["Home", "Viewer"],
  "Cost & usage": ["Cost dashboard", "Latency dashboard", "Coverage dashboard", "Reconciliation"],
  Agents: ["Map", "Map table", "Trace replay"],
  Quality: ["Quality", "Recommendations"],
  Governance: ["Review", "Actions"],
  Reports: ["Reports"],
};

test("navigation shows the six groups with permission-aware entries", async ({ page }) => {
  await page.goto("/");
  const nav = page.getByRole("navigation", { name: "Primary" });
  for (const [group, links] of Object.entries(GROUPS)) {
    const region = nav.getByRole("group", { name: group });
    await expect(region).toBeVisible();
    for (const name of links) {
      await expect(region.getByRole("link", { name, exact: true })).toBeVisible();
    }
  }
  // The Viewer stub is not suggested the Admin workspace; the route itself still answers 403
  // (hidden-route.spec.ts).
  await expect(nav.getByRole("link", { name: "Admin", exact: true })).toHaveCount(0);
});

test("domain switcher lists domains, writes the URL and carries it into nav links", async ({
  page,
}) => {
  await page.goto("/quality");
  const switcher = page.getByRole("combobox", { name: "Domain" });
  await expect(switcher).toBeVisible();
  await switcher.click();
  await expect(page.getByRole("option", { name: "Finance" })).toBeVisible();
  await expect(
    page.getByRole("option", {
      name: "commercial:e2e:sandbox:domain:viewer-only (name unavailable)",
    }),
  ).toBeVisible();
  await page.getByRole("option", { name: "Finance" }).click();

  await expect(page).toHaveURL(new RegExp(`domain_id=${encodeURIComponent(DOMAIN_OK)}`));
  expect(new URL(page.url()).pathname).toBe("/quality");
  const link = page
    .getByRole("navigation", { name: "Primary" })
    .getByRole("link", { name: "Reports", exact: true });
  await expect(link).toHaveAttribute("href", `/reports?domain_id=${encodeURIComponent(DOMAIN_OK)}`);

  // Only the domain id is remembered, under a pseudonymous key.
  const stored = await page.evaluate(() => ({ ...localStorage }));
  const keys = Object.keys(stored);
  expect(keys).toHaveLength(1);
  expect(keys[0]).toMatch(/^ns\.lastDomain\.[0-9a-f]{32}$/);
  expect(Object.values(stored)).toEqual([DOMAIN_OK]);
});

test("skip link, navigation and menus work from the keyboard", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("main")).toBeVisible();
  await page.keyboard.press("Tab");
  const skip = page.getByRole("link", { name: "Skip to main content" });
  await expect(skip).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("main")).toBeFocused();

  // The user menu opens with the keyboard and offers sign out.
  const account = page.getByRole("button", { name: "Account: Viewer" });
  await account.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("menuitem", { name: "Sign out" })).toBeVisible();
  await page.keyboard.press("Escape");

  // The domain switcher opens and selects with the keyboard.
  const switcher = page.getByRole("combobox", { name: "Domain" });
  await switcher.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("option", { name: "Finance" })).toBeVisible();
  await page.keyboard.press("Escape");
});

test("shell has no axe violations", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("combobox", { name: "Domain" })).toBeVisible();
  expect(await axeViolationsIgnoringTabster(page)).toEqual([]);
  await page.getByRole("combobox", { name: "Domain" }).click();
  await expect(page.getByRole("option", { name: "Finance" })).toBeVisible();
  expect(await axeViolationsIgnoringTabster(page)).toEqual([]);
});
