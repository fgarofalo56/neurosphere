import type { Locator, Page } from "@playwright/test";
import { expect, test } from "../../e2e-support/fixtures.ts";
import { INCIDENT_IDS as I, incidentDomain, tableUrl } from "./support.ts";

// PRP-77 item 6, story: nothing is mouse-only. The table view reads the same filters from the
// URL, has the same search (focusing the row), the same columns, and an impact toggle that adds a
// depth column and narrows the rows to the affected ones. Parallel to filters, search and incident
// specs on the map.

const DOMAIN = incidentDomain("table");

const labels = (page: Page): Locator => page.getByTestId("map-grid").getByTestId("label");

async function focusedLabel(page: Page): Promise<string | null> {
  return page.evaluate(
    () =>
      document.activeElement?.closest("tr[data-row-key]")?.querySelector("[data-testid='label']")
        ?.textContent ?? null,
  );
}

test.describe("map table parity", () => {
  test("opens with the filters from the URL and shows the new columns as text", async ({
    page,
  }) => {
    await page.goto(tableUrl(DOMAIN, { environment: "production" }));
    await expect(page.getByRole("treegrid", { name: "Map nodes" })).toBeVisible();
    await expect(page.getByTestId("filter-environment")).toHaveValue("production");
    await expect(page.getByTestId("map-filter-bar")).toHaveAttribute("data-active-filters", "1");
    await expect(labels(page)).toHaveText([
      "ledger-service",
      "billing-agent",
      "refund-agent",
      "reconcile-sub-agent",
      "docs-mcp",
      "notify-agent",
    ]);

    const ledger = page.getByTestId("node-row").filter({ hasText: "ledger-service" });
    await expect(ledger.getByTestId("kind-text")).toHaveText("Service");
    await expect(ledger.getByTestId("environment")).toHaveText("Production");
    await expect(ledger.getByTestId("cloud")).toHaveText("Commercial");
    await expect(ledger.getByTestId("health")).toContainText("Failing");
    await expect(ledger.getByTestId("error-rate")).toHaveText("31.0%");
    // Unknown is said, never 0%.
    await expect(
      page.getByTestId("node-row").filter({ hasText: "refund-agent" }).getByTestId("error-rate"),
    ).toHaveText("Unknown");
    await expect(
      page.getByTestId("node-row").filter({ hasText: "docs-mcp" }).getByTestId("cloud"),
    ).toHaveText("Government");
  });

  test("changing and clearing a filter updates the rows and the URL", async ({ page }) => {
    await page.goto(tableUrl(DOMAIN));
    await expect(labels(page)).toHaveCount(12);
    await page.getByTestId("filter-health").selectOption("failing");
    await expect(page).toHaveURL(/health=failing/);
    await expect(labels(page)).toHaveText(["ledger-service"]);
    await page.getByTestId("filter-clear").click();
    await expect(labels(page)).toHaveCount(12);
    await expect(page).not.toHaveURL(/health=/);
  });

  test("the map link carries the filters, so the same view opens on the map", async ({ page }) => {
    await page.goto(tableUrl(DOMAIN, { environment: "staging", node_type: "tool" }));
    await expect(labels(page)).toHaveText(["tax-tool"]);
    const href = await page.getByRole("link", { name: "View as map" }).getAttribute("href");
    expect(href).toContain("environment=staging");
    expect(href).toContain("node_type=tool");
    await page.getByRole("link", { name: "View as map" }).click();
    await expect(page).toHaveURL(/\/map\?/);
    await expect(page.getByTestId("filter-environment")).toHaveValue("staging");
    await expect(page.getByTestId("node-count")).toContainText("1 nodes");
  });

  test("search focuses the matching row and says so in words", async ({ page }) => {
    await page.goto(tableUrl(DOMAIN));
    await expect(labels(page)).toHaveCount(12);
    const box = page.getByTestId("map-search");
    await box.fill("report");
    const result = page.getByTestId("map-search-result").filter({ hasText: "report-agent" });
    await expect(result).toBeVisible();
    const resultId = await result.getAttribute("id");
    await page.keyboard.press("ArrowDown");
    await expect(box).toHaveAttribute("aria-activedescendant", resultId ?? "");
    await page.keyboard.press("Enter");
    await expect(page.getByTestId("search-note")).toHaveText("Focused report-agent in the table.");
    await expect.poll(() => focusedLabel(page)).toBe("report-agent");
    await expect(page.getByTestId("detail")).toContainText("report-agent");
  });

  test("a result that is not in the table is said in text, not dropped silently", async ({
    page,
  }) => {
    await page.goto(tableUrl(DOMAIN));
    await expect(labels(page)).toHaveCount(12);
    const box = page.getByTestId("map-search");
    await box.fill("archive");
    await expect(page.getByTestId("map-search-result")).toHaveCount(1);
    await page.keyboard.press("ArrowDown");
    await page.keyboard.press("Enter");
    await expect(page.getByTestId("search-note")).toContainText(
      "archive-agent is not in the table with the current filters.",
    );
  });

  test("impact toggle adds the depth column and narrows the rows to the affected ones", async ({
    page,
  }) => {
    await page.goto(tableUrl(DOMAIN));
    await expect(labels(page)).toHaveCount(12);
    await expect(page.getByTestId("depth")).toHaveCount(0);
    const toggle = page.getByTestId("show-impact");
    await expect(toggle).toBeDisabled();

    // Select the row by keyboard (Enter), then toggle impact.
    const ledger = page.getByTestId("node-row").filter({ hasText: "ledger-service" });
    await ledger.focus();
    await page.keyboard.press("Enter");
    await expect(page.getByTestId("detail")).toContainText("ledger-service");
    const request = page.waitForRequest(
      (r) => r.method() === "POST" && r.url().includes("/impact"),
    );
    await expect(toggle).toBeEnabled();
    await toggle.click();
    expect((await request).postDataJSON()).toEqual({ node_id: I.ledger, max_depth: 2 });

    await expect(page.getByRole("columnheader", { name: "Depth" })).toBeVisible();
    await expect(page.getByTestId("impact-status")).toHaveText(
      "5 dependents affected by ledger-service",
    );
    await expect(labels(page)).toHaveText([
      "ledger-service",
      "billing-agent",
      "refund-agent",
      "reconcile-sub-agent",
      "report-agent",
    ]);
    const depthOf = (name: string): Locator =>
      page.getByTestId("node-row").filter({ hasText: name }).getByTestId("depth");
    await expect(depthOf("ledger-service")).toHaveText("Selected");
    await expect(depthOf("billing-agent")).toHaveText("1");
    await expect(depthOf("report-agent")).toHaveText("2");
    // The dependent that is not in the table is named in text.
    await expect(page.getByTestId("impact-not-loaded")).toContainText("archive-agent");

    // Depth control and clearing.
    await page.getByTestId("impact-depth").selectOption("1");
    await expect(page.getByTestId("impact-status")).toHaveText(
      "2 dependents affected by ledger-service",
    );
    await expect(labels(page)).toHaveText(["ledger-service", "billing-agent", "refund-agent"]);
    await toggle.click();
    await expect(page.getByTestId("depth")).toHaveCount(0);
    await expect(labels(page)).toHaveCount(12);
  });

  test("the I key on a focused row toggles impact", async ({ page }) => {
    await page.goto(tableUrl(DOMAIN));
    await expect(labels(page)).toHaveCount(12);
    const row = page.getByTestId("node-row").filter({ hasText: "billing-agent" });
    await row.focus();
    await page.keyboard.press("i");
    await expect(page.getByTestId("impact-status")).toHaveText(
      "1 dependent affected by billing-agent",
    );
    await expect(labels(page)).toHaveText(["billing-agent", "reconcile-sub-agent"]);
    await page.keyboard.press("i");
    await expect(page.getByTestId("depth")).toHaveCount(0);
  });
});
