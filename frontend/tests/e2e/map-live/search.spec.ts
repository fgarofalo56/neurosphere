import { expect, test } from "../../e2e-support/fixtures.ts";
import {
  INCIDENT_IDS as I,
  incidentDomain,
  mapUrl,
  openLiveMap,
  searchAndSelect,
} from "./support.ts";

// PRP-77 item 6, story: the architect finds any node by name from the search box and jumps to it.
// Type at least 2 characters, pick a result with the keyboard, the node is selected and its panel
// opens; a node outside the viewport is fetched through the neighbourhood route first.

const DOMAIN = incidentDomain("search");

test.describe("map search", () => {
  test("needs two characters, announces the count and shows kind, environment and health as text", async ({
    page,
  }) => {
    await openLiveMap(page, mapUrl(DOMAIN));
    const searches: string[] = [];
    page.on("request", (r) => {
      if (r.url().includes("/search") && r.url().includes("q=")) searches.push(r.url());
    });
    const box = page.getByTestId("map-search");
    await box.fill("a");
    await expect(page.getByTestId("map-search-status")).toHaveText("");
    expect(searches.filter((u) => /[?&]q=a(&|$)/.test(u))).toEqual([]);

    await box.fill("agent");
    await expect(page.getByTestId("map-search-status")).toHaveText("6 matches");
    const row = page.getByTestId("map-search-result").filter({ hasText: "refund-agent" });
    await expect(row).toContainText("Agent · environment production · health ok");
    await expect(page.getByTestId("map-search-result")).toHaveCount(6);

    // A person is found by pseudonym only.
    await box.fill("Person-");
    await expect(page.getByTestId("map-search-result")).toHaveCount(1);
    await expect(page.getByTestId("map-search-result")).toContainText("Person-3fa9");

    await box.fill("no-such-node");
    await expect(page.getByTestId("map-search-status")).toHaveText("No matching nodes");
  });

  test("keyboard jump to a node on screen selects it and opens its panel", async ({ page }) => {
    await openLiveMap(page, mapUrl(DOMAIN));
    await expect(page.getByTestId("node-panel")).toHaveCount(0);
    const neighbourhoodCalls: string[] = [];
    page.on("request", (r) => {
      if (r.url().includes("/neighborhood/")) neighbourhoodCalls.push(r.url());
    });

    await searchAndSelect(page, "ledger", "ledger-service");
    const panel = page.getByTestId("node-panel");
    await expect(panel).toBeVisible();
    await expect(page.getByTestId("panel-label")).toHaveText("ledger-service");
    await expect(page.getByTestId("panel-kind")).toHaveText("Service");
    await expect(page.getByTestId("facet-environment")).toContainText("production");
    await expect(page.getByTestId("panel-recent-errors")).toBeVisible();
    // Already on screen: no neighbourhood fetch.
    expect(neighbourhoodCalls).toEqual([]);
    await expect(page.getByTestId("node-count")).toContainText("12 nodes");
  });

  test("Escape closes the result list without selecting anything", async ({ page }) => {
    await openLiveMap(page, mapUrl(DOMAIN));
    const box = page.getByTestId("map-search");
    await box.fill("agent");
    await expect(page.getByTestId("map-search-result").first()).toBeVisible();
    await expect(box).toHaveAttribute("aria-expanded", "true");
    await page.keyboard.press("Escape");
    await expect(box).toHaveAttribute("aria-expanded", "false");
    await expect(page.getByTestId("map-search-result").first()).toBeHidden();
    await expect(page.getByTestId("node-panel")).toHaveCount(0);
  });

  test("a result outside the viewport is fetched through the neighbourhood route and selected", async ({
    page,
  }) => {
    await openLiveMap(page, mapUrl(DOMAIN));
    await expect(page.getByTestId("node-count")).toContainText("12 nodes, ");
    const neighbourhood = page.waitForResponse(
      (r) => r.url().includes(`/neighborhood/${encodeURIComponent(I.archive)}`) && r.ok(),
    );
    await searchAndSelect(page, "archive", "archive-agent");
    await neighbourhood;
    // The node (and no other new one: its neighbour is already loaded) joined the graph.
    await expect(page.getByTestId("node-count")).toContainText("13 nodes, 11 edges");
    await expect(page.getByTestId("panel-label")).toHaveText("archive-agent");
    await expect(page.getByTestId("node-panel")).toBeVisible();
    await expect(page.getByTestId("map-search-jump-note")).toHaveCount(0);
  });

  test("the active filters narrow the search", async ({ page }) => {
    await openLiveMap(page, mapUrl(DOMAIN, { environment: "staging" }));
    await expect(page.getByTestId("node-count")).toContainText("4 nodes");
    const box = page.getByTestId("map-search");
    await box.fill("agent");
    await expect(page.getByTestId("map-search-result")).toHaveCount(1);
    await expect(page.getByTestId("map-search-result")).toContainText("report-agent");
  });
});
