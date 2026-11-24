import { expect, test } from "../../e2e-support/fixtures.ts";
import { incidentDomain, mapUrl, openLiveMap } from "./support.ts";

// PRP-77 item 6, story: the architect narrows the map by environment, health, type, cloud and tag.
// Filters live in the URL (shareable, reload-safe, back button), counts follow them, "clear all"
// resets them, and an invalid tag never reaches the server.

const DOMAIN = incidentDomain("filters");
const nodeCount = (page: import("@playwright/test").Page) => page.getByTestId("node-count");

test.describe("map filters", () => {
  test("narrows the map, keeps filters in the URL, survives reload and back, and clears", async ({
    page,
  }) => {
    await openLiveMap(page, mapUrl(DOMAIN));
    // 12 nodes are on screen; the archive agent is outside the viewport.
    await expect(nodeCount(page)).toContainText("12 nodes");
    const bar = page.getByTestId("map-filter-bar");
    await expect(bar).toHaveAttribute("data-active-filters", "0");
    await expect(page.getByTestId("filter-clear")).toHaveCount(0);

    // Options and their counts come from the server search counts (all matching nodes).
    await expect(page.getByTestId("filter-environment").locator("option")).toContainText([
      "All",
      "Production (7)",
      "Staging (4)",
    ]);

    // Environment: the viewport is refetched with the parameter and the count drops.
    const refetch = page.waitForRequest(
      (r) => r.url().includes("/viewport") && r.url().includes("environment=staging"),
    );
    await page.getByTestId("filter-environment").selectOption("staging");
    await refetch;
    await expect(nodeCount(page)).toContainText("4 nodes");
    await expect(page).toHaveURL(/environment=staging/);
    await expect(bar).toHaveAttribute("data-active-filters", "1");
    await expect(page.getByTestId("filter-clear")).toHaveText("1 filter applied, clear all");

    // A second filter narrows further (staging tools: only the tax tool).
    await page.getByTestId("filter-node_type").selectOption("tool");
    await expect(nodeCount(page)).toContainText("1 nodes");
    await expect(page).toHaveURL(/node_type=tool/);
    await expect(page.getByTestId("filter-clear")).toHaveText("2 filters applied, clear all");

    // Reload keeps the filters (the URL is the state).
    await page.reload();
    await expect(page.getByTestId("filter-environment")).toHaveValue("staging");
    await expect(page.getByTestId("filter-node_type")).toHaveValue("tool");
    await expect(nodeCount(page)).toContainText("1 nodes");

    // Back restores the previous filter set.
    await page.goBack();
    await expect(page.getByTestId("filter-node_type")).toHaveValue("");
    await expect(page.getByTestId("filter-environment")).toHaveValue("staging");
    await expect(nodeCount(page)).toContainText("4 nodes");

    // Clear all removes every filter from the URL and the map returns to the full view.
    await page.getByTestId("filter-clear").click();
    await expect(page.getByTestId("filter-clear")).toHaveCount(0);
    await expect(nodeCount(page)).toContainText("12 nodes");
    await expect(page).not.toHaveURL(/environment=/);
    await expect(page.getByTestId("filter-environment")).toHaveValue("");
  });

  test("health, cloud and tag filters each refetch with their own parameter", async ({ page }) => {
    await openLiveMap(page, mapUrl(DOMAIN));
    await expect(nodeCount(page)).toContainText("12 nodes");

    await page.getByTestId("filter-health").selectOption("failing");
    await expect(nodeCount(page)).toContainText("1 nodes");
    await page.getByTestId("filter-clear").click();
    await expect(nodeCount(page)).toContainText("12 nodes");

    await page.getByTestId("filter-cloud").selectOption("government");
    await expect(nodeCount(page)).toContainText("1 nodes");
    await page.getByTestId("filter-clear").click();
    await expect(nodeCount(page)).toContainText("12 nodes");

    await page.getByTestId("filter-tag").fill("payments");
    await page.getByTestId("filter-tag").press("Enter");
    await expect(page).toHaveURL(/tag=payments/);
    await expect(nodeCount(page)).toContainText("3 nodes");
    // Every payments node is on screen; the other kinds are gone.
    await expect(page.getByTestId("filter-clear")).toHaveText("1 filter applied, clear all");
  });

  test("an invalid tag is rejected in the field before any request", async ({ page }) => {
    await openLiveMap(page, mapUrl(DOMAIN));
    const requests: string[] = [];
    page.on("request", (r) => {
      if (r.url().includes("/viewport") || r.url().includes("/search")) requests.push(r.url());
    });
    await page.getByTestId("filter-tag").fill("Not A Tag!");
    await page.getByTestId("filter-tag-apply").click();
    await expect(page.getByText("Not a valid tag.")).toBeVisible();
    await expect(page).not.toHaveURL(/tag=/);
    await expect(page.getByTestId("map-filter-bar")).toHaveAttribute("data-active-filters", "0");
    expect(requests).toEqual([]);
    // Correcting it clears the error and applies the filter.
    await page.getByTestId("filter-tag").fill("payments");
    await expect(page.getByText("Not a valid tag.")).toHaveCount(0);
  });

  test("a filtered URL opens with the filters applied and a hand-edited bad value is ignored", async ({
    page,
  }) => {
    await openLiveMap(page, mapUrl(DOMAIN, { environment: "production", health: "bogus" }));
    await expect(page.getByTestId("filter-environment")).toHaveValue("production");
    await expect(page.getByTestId("filter-health")).toHaveValue("");
    await expect(page.getByTestId("map-filter-bar")).toHaveAttribute("data-active-filters", "1");
    await expect(nodeCount(page)).toContainText("6 nodes");
  });
});
