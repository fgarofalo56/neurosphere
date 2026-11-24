import { expect, test } from "../../e2e-support/fixtures.ts";
import {
  analyze,
  blocking,
  describeBlocking,
  MODES,
  seedPreferences,
} from "../a11y/axe-support.ts";
import {
  INCIDENT_IDS as I,
  control,
  incidentDomain,
  mapUrl,
  openLiveMap,
  searchAndSelect,
  sendHealthDelta,
  tableUrl,
} from "./support.ts";

// PRP-77 item 6, accessibility: the route-samples axe run covers /map and /map/table with the
// filter bar SET (filters in the URL; see route-samples.ts). A sample cannot press buttons, so the
// state it cannot reach, the impact view, is checked here with the same axe helper the a11y suite
// uses (serious and critical findings block). Reduced motion keeps the highlight, without motion.

const DOMAIN = incidentDomain("a11y");

/**
 * KNOWN APP DEFECT (reported with PRP-77 item 6, not fixed here: src/ is another lane's): the
 * "Show on map" buttons of the impact list carry aria-label="Show <node> on map" while their
 * visible text is "Show on map", which axe reports as serious `label-content-name-mismatch`
 * (WCAG 2.5.3). Only that finding, only on those buttons, is set aside for the impact-view runs;
 * every other finding still blocks. The `test.fail` below flips to "unexpected pass" when the app
 * is fixed, which is the cue to delete this filter.
 */
function blockingExceptKnown(violations: Awaited<ReturnType<typeof analyze>>["violations"]) {
  return blocking(violations).filter(
    (v) =>
      !(
        v.id === "label-content-name-mismatch" &&
        v.targets.every((t) => t.startsWith('button[aria-label="Show '))
      ),
  );
}

test("show-on-map buttons expose their visible text in their accessible name", async ({ page }) => {
  test.fail(true, "app defect: aria-label drops the visible text (ImpactPanel show-on-map)");
  await openLiveMap(page, mapUrl(DOMAIN));
  await searchAndSelect(page, "ledger", "ledger-service");
  await page.getByTestId("show-impact").click();
  await expect(page.getByTestId("impact-offscreen-row")).toHaveCount(1);
  const { violations } = await analyze(page);
  expect(blocking(violations), describeBlocking(violations)).toEqual([]);
});

for (const mode of MODES) {
  test(`axe: map with filters set and the impact view on (${mode})`, async ({ page }) => {
    await seedPreferences(page, { mode });
    await openLiveMap(page, mapUrl(DOMAIN, { environment: "production", cloud: "commercial" }));
    await expect(page.getByTestId("map-filter-bar")).toHaveAttribute("data-active-filters", "2");
    await searchAndSelect(page, "ledger", "ledger-service");
    await page.getByTestId("show-impact").click();
    await expect(page.getByTestId("impact-status")).toContainText("dependents affected by");
    await expect(page.getByTestId("impact-list")).toContainText("billing-agent");
    const { violations } = await analyze(page);
    expect(blockingExceptKnown(violations), describeBlocking(violations)).toEqual([]);
  });
}

test("axe: map with the search results open", async ({ page }) => {
  await seedPreferences(page, { mode: "light" });
  await openLiveMap(page, mapUrl(DOMAIN));
  await page.getByTestId("map-search").fill("agent");
  await expect(page.getByTestId("map-search-result").first()).toBeVisible();
  const { violations } = await analyze(page);
  expect(blocking(violations), describeBlocking(violations)).toEqual([]);
});

test("axe: map with the impact banner showing", async ({ page, request }) => {
  const domain = incidentDomain("a11y-banner");
  await seedPreferences(page, { mode: "light" });
  await openLiveMap(page, mapUrl(domain));
  await control(request, domain, { action: "flip", node_id: I.tax, health: "failing" });
  await sendHealthDelta(page, [{ id: I.tax, kind: "tool", label: "tax-tool", health: "failing" }]);
  await expect(page.getByTestId("impact-banner")).toBeVisible();
  const { violations } = await analyze(page);
  expect(blocking(violations), describeBlocking(violations)).toEqual([]);
});

for (const mode of MODES) {
  test(`axe: table with filters set and the impact toggle on (${mode})`, async ({ page }) => {
    await seedPreferences(page, { mode });
    await page.goto(tableUrl(DOMAIN, { cloud: "commercial" }));
    await expect(page.getByRole("treegrid", { name: "Map nodes" })).toBeVisible();
    const row = page.getByTestId("node-row").filter({ hasText: "ledger-service" });
    await row.focus();
    await page.keyboard.press("i");
    await expect(page.getByRole("columnheader", { name: "Depth" })).toBeVisible();
    await expect(page.getByTestId("impact-status")).toContainText("dependents affected by");
    const { violations } = await analyze(page);
    expect(blocking(violations), describeBlocking(violations)).toEqual([]);
  });
}

test.describe("reduced motion", () => {
  test.use({ reducedMotion: "reduce" });

  test("the impact highlight stays, the edge animation is off", async ({ page }) => {
    await openLiveMap(page, mapUrl(incidentDomain("a11y-motion")));
    const canvas = page.getByTestId("map-canvas");
    await expect(canvas).toHaveAttribute("data-edge-animation", "off");
    const size = (id: string): Promise<number> =>
      page.evaluate((nodeId) => {
        const el = document.querySelector('[data-testid="map-canvas"]') as HTMLElement & {
          __nsMap?: { sigma: { getNodeDisplayData(id: string): { size: number } | undefined } };
        };
        return el.__nsMap?.sigma.getNodeDisplayData(nodeId)?.size ?? 0;
      }, id);
    const idle = await size(I.billing);

    await searchAndSelect(page, "ledger", "ledger-service");
    await page.getByTestId("show-impact").click();
    await expect(page.getByTestId("impact-status")).toContainText("5 dependents affected by");
    // Highlight (larger affected node) and the text list are both there, with no animation.
    await expect.poll(() => size(I.billing)).toBeGreaterThan(idle * 1.2);
    await expect(page.getByTestId("impact-list")).toContainText("billing-agent");
    await expect(canvas).toHaveAttribute("data-edge-animation", "off");
    await expect(canvas).toHaveAttribute("data-animated-edges", "0");
  });
});
