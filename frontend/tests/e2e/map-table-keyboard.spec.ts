import type { Page } from "@playwright/test";
import { expect, test } from "../e2e-support/fixtures.ts";
import { axeViolations } from "../helpers/axe.ts";
import { DOMAIN_FORBIDDEN, DOMAIN_OK } from "../mock-api/server.ts";

// PRP-18 item 4: the accessible table alternative to the map, driven by keyboard only.

function tableUrl(domain: string): string {
  return `/map/table?domain_id=${encodeURIComponent(domain)}`;
}

async function seriousOrCritical(page: Page): Promise<unknown[]> {
  const all = await axeViolations(page);
  return all.filter((v) => v.impact === "serious" || v.impact === "critical");
}

/** Tab until `done` holds for the focused element; bounded so a regression cannot hang. */
async function tabUntil(page: Page, done: () => Promise<boolean>): Promise<void> {
  for (let i = 0; i < 40; i += 1) {
    await page.keyboard.press("Tab");
    if (await done()) return;
  }
  throw new Error("focus never reached the expected element within 40 Tab presses");
}

const focusedRowLabel = (page: Page) =>
  page.evaluate(
    () =>
      document.activeElement?.closest("tr[data-row-key]")?.querySelector("[data-testid='label']")
        ?.textContent ?? null,
  );

test.describe("map table keyboard", () => {
  test("is fully operable from the keyboard", async ({ page }) => {
    await page.goto(tableUrl(DOMAIN_OK));
    const grid = page.getByRole("treegrid", { name: "Map nodes" });
    await expect(grid).toBeVisible();
    await expect(page.getByTestId("coverage")).toHaveText("Coverage: partial");
    await expect(page.getByTestId("truncation-banner")).toContainText("node budget reached");
    expect(await seriousOrCritical(page)).toEqual([]);

    // Tab reaches the grid: exactly one row is in the tab order (roving tabindex).
    await tabUntil(page, () =>
      page.evaluate(() => document.activeElement?.matches("tr[data-row-key]") ?? false),
    );
    await expect(grid.locator("tr[data-row-key][tabindex='0']")).toHaveCount(1);
    expect(await focusedRowLabel(page)).toBe("Agents");

    // Arrow keys move between rows; Home returns to the first.
    await page.keyboard.press("ArrowDown");
    expect(await focusedRowLabel(page)).toBe("Models");
    await page.keyboard.press("ArrowDown");
    expect(await focusedRowLabel(page)).toBe("support-agent");
    await page.keyboard.press("Home");
    expect(await focusedRowLabel(page)).toBe("Agents");

    // Enter expands the cluster; focus stays on the row.
    const clusterRow = grid.locator("tr[data-row-key]").first();
    await page.keyboard.press("Enter");
    await expect(clusterRow).toHaveAttribute("aria-expanded", "true");
    await expect(grid.getByText("agent-0", { exact: true })).toBeVisible();
    await expect(clusterRow).toBeFocused();
    expect(await seriousOrCritical(page)).toEqual([]);

    // Load page 2 by keyboard; focus moves to the first new row.
    await tabUntil(page, async () =>
      page.evaluate(() => document.activeElement?.tagName === "BUTTON"),
    );
    await expect(page.getByRole("button", { name: "Load more in Agents" })).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(grid.getByText("agent-5", { exact: true })).toBeVisible();
    await expect(page.getByText("Coverage: delayed (300 s lag)")).toBeVisible();
    await expect(grid.locator("tr[data-row-key]:focus")).toContainText("agent-5");

    // Load page 3 (last): the button disappears.
    await page.keyboard.press("Tab");
    await expect(page.getByRole("button", { name: "Load more in Agents" })).toBeFocused();
    await page.keyboard.press("Space");
    await expect(grid.getByText("agent-10", { exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: /Load more/ })).toHaveCount(0);
    await expect(grid.locator("tr[data-row-key]:focus")).toContainText("agent-10");

    // Open a row's detail; it is announced through the polite live region.
    await page.keyboard.press("Enter");
    const detail = page.getByTestId("detail");
    await expect(detail).toHaveAttribute("aria-live", "polite");
    await expect(detail).toContainText("Agent agent-10");
    await expect(detail).toContainText("health Healthy");

    // Connections are listed with provenance as text.
    const edges = page.getByTestId("connections-table");
    await expect(edges.getByText("Observed").first()).toBeVisible();
    await expect(edges.getByText("Declared").first()).toBeVisible();
    await expect(edges.getByText("Inferred").first()).toBeVisible();

    // "View as map" is reachable by keyboard.
    const link = page.getByRole("link", { name: "View as map" });
    await link.focus();
    await expect(link).toBeFocused();
    await expect(link).toHaveAttribute("href", /^\/map\?domain_id=/);

    expect(await seriousOrCritical(page)).toEqual([]);
  });

  test("shows an error, not data, for a domain the caller cannot read", async ({ page }) => {
    await page.goto(tableUrl(DOMAIN_FORBIDDEN));
    await expect(page.getByTestId("forbidden-state")).toBeVisible();
    await expect(page.getByRole("treegrid")).toHaveCount(0);
  });
});
