import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import type { Page } from "@playwright/test";
import { expect, test } from "../../e2e-support/fixtures.ts";
import {
  analyze,
  blocking,
  describeBlocking,
  MODES,
  openSample,
  record,
  seedPreferences,
  writeAggregate,
  type AxeRecord,
} from "./axe-support.ts";
import { ROUTE_SAMPLES } from "./route-samples.ts";

// PRP-24 item 3: axe over every route in the manifest x light/dark/high-contrast, plus sandbox mode,
// plus the explicit map-table, reduced-motion map and sandboxed-chart-iframe checks. Automated axe
// is necessary, not sufficient (docs/accessibility/README.md); G09 stays OPEN.

const manifest = JSON.parse(
  readFileSync(
    fileURLToPath(new URL("../../../src/app/route-manifest.json", import.meta.url)),
    "utf8",
  ),
) as { routes: string[] };

const BANNER_NAME = "Sandbox mode: synthetic data only";

test.afterAll(() => {
  writeAggregate();
});

test("every route in the manifest has an axe sample and every sample is in the manifest", () => {
  const sampled = new Set(ROUTE_SAMPLES.map((s) => s.pattern));
  const missing = manifest.routes.filter((r) => !sampled.has(r));
  const unknown = [...sampled].filter((p) => !manifest.routes.includes(p));
  expect(missing, "routes without an axe sample (add them to route-samples.ts)").toEqual([]);
  expect(unknown, "samples for patterns that are not in route-manifest.json").toEqual([]);
  const names = ROUTE_SAMPLES.map((s) => `${s.pattern}|${s.name}`);
  expect(new Set(names).size).toBe(names.length);
});

for (const sample of ROUTE_SAMPLES) {
  for (const mode of MODES) {
    test(`axe: ${sample.pattern} (${sample.name}) in ${mode}`, async ({ page }) => {
      await seedPreferences(page, { mode });
      await openSample(page, sample);
      const { violations, counts } = await analyze(page);
      const rec: AxeRecord = {
        kind: "route",
        pattern: sample.pattern,
        name: sample.name,
        url: sample.url,
        mode,
        packId: "default",
        sandboxMode: false,
        counts,
        violations,
      };
      record(rec);
      expect(blocking(violations), describeBlocking(violations)).toEqual([]);
    });
  }

  test(`axe: ${sample.pattern} (${sample.name}) with sandbox mode on shows the banner`, async ({
    page,
  }) => {
    await seedPreferences(page, { mode: "light", sandbox: true });
    await openSample(page, sample);
    const banner = page.getByRole("region", { name: BANNER_NAME });
    await expect(banner).toBeVisible();
    await expect(banner).toContainText("synthetic dataset");
    const { violations, counts } = await analyze(page);
    record({
      kind: "sandbox",
      pattern: sample.pattern,
      name: sample.name,
      url: sample.url,
      mode: "light",
      packId: "default",
      sandboxMode: true,
      counts,
      violations,
    });
    expect(blocking(violations), describeBlocking(violations)).toEqual([]);
  });
}

// ---- explicit coverage -------------------------------------------------------------------------

/** Tab until `done` holds; bounded so a regression cannot hang. */
async function tabUntil(page: Page, done: () => Promise<boolean>): Promise<void> {
  for (let i = 0; i < 60; i += 1) {
    await page.keyboard.press("Tab");
    if (await done()) return;
  }
  throw new Error("focus never reached the expected element within 60 Tab presses");
}

const mapTable = ROUTE_SAMPLES.find((s) => s.pattern === "/map/table");
const mapPage = ROUTE_SAMPLES.find((s) => s.pattern === "/map");
const reportView = ROUTE_SAMPLES.find((s) => s.pattern === "/reports/view");
if (!mapTable || !mapPage || !reportView) throw new Error("route-samples.ts lost a required route");

test("map table view: keyboard traversal reaches the grid, moves through rows and does not trap focus", async ({
  page,
}) => {
  await seedPreferences(page, { mode: "light" });
  await openSample(page, mapTable);
  const grid = page.getByRole("treegrid", { name: "Map nodes" });
  await expect(grid).toBeVisible();

  await tabUntil(page, () =>
    page.evaluate(() => document.activeElement?.matches("tr[data-row-key]") ?? false),
  );
  // Roving tabindex: exactly one row is in the tab order.
  await expect(grid.locator("tr[data-row-key][tabindex='0']")).toHaveCount(1);
  const label = (): Promise<string | null> =>
    page.evaluate(
      () =>
        document.activeElement?.closest("tr[data-row-key]")?.querySelector("[data-testid='label']")
          ?.textContent ?? null,
    );
  const first = await label();
  await page.keyboard.press("ArrowDown");
  const second = await label();
  expect(second).not.toBeNull();
  expect(second).not.toBe(first);
  await page.keyboard.press("Home");
  expect(await label()).toBe(first);

  // The focused row shows a visible focus indicator (not an outline-less element).
  const outline = await page.evaluate(() => {
    const s = getComputedStyle(document.activeElement as Element);
    return { style: s.outlineStyle, width: s.outlineWidth, shadow: s.boxShadow };
  });
  expect(outline.style !== "none" || outline.shadow !== "none").toBe(true);

  // No keyboard trap: Tab leaves the grid and focus ends up outside it.
  await tabUntil(page, () =>
    page.evaluate(() => !document.activeElement?.closest("[role='treegrid']")),
  );
  await expect(grid.locator(":focus")).toHaveCount(0);

  const { violations, counts } = await analyze(page);
  record({
    kind: "special",
    pattern: "/map/table",
    name: "keyboard traversal",
    url: mapTable.url,
    mode: "light",
    packId: "default",
    sandboxMode: false,
    counts,
    violations,
  });
  expect(blocking(violations), describeBlocking(violations)).toEqual([]);
});

test("map page under prefers-reduced-motion: reduce stops animation, links to the table and is axe-clean", async ({
  page,
}) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await seedPreferences(page, { mode: "light" });
  await openSample(page, mapPage);
  const canvas = page.getByTestId("map-canvas");
  await expect(canvas).toHaveAttribute("data-edge-animation", "off");
  await expect(canvas).toHaveAttribute("data-animated-edges", "0");
  // The map is WebGL, so the table view is the accessible alternative and must stay reachable.
  await expect(page.getByRole("link", { name: "View as table" })).toBeVisible();
  const toggle = page.getByRole("switch", { name: /reduce motion/i });
  await expect(toggle).toBeChecked();
  const { violations, counts } = await analyze(page);
  record({
    kind: "special",
    pattern: "/map",
    name: "reduced motion",
    url: mapPage.url,
    mode: "light",
    packId: "default",
    sandboxMode: false,
    counts,
    violations,
    note: "prefers-reduced-motion: reduce via page.emulateMedia. The WebGL canvas itself is not machine-auditable; see docs/accessibility checklists for the manual rows.",
  });
  expect(blocking(violations), describeBlocking(violations)).toEqual([]);
});

const HARNESS = "/src/features/charts/harness/index.html?plan=bar";

test("sandboxed chart iframe: titled, sandboxed without allow-same-origin, with a table outside the frame", async ({
  page,
}) => {
  await seedPreferences(page, { mode: "light" });
  await page.goto(HARNESS);
  await expect
    .poll(
      () =>
        page.evaluate(
          () => (window as unknown as { __chart?: { status: string } }).__chart?.status ?? "none",
        ),
      { timeout: 30_000 },
    )
    .toBe("rendered");

  const iframe = page.locator("iframe");
  await expect(iframe).toHaveCount(1);
  const title = await iframe.getAttribute("title");
  expect((title ?? "").trim().length).toBeGreaterThan(0);
  const sandbox = (await iframe.getAttribute("sandbox")) ?? "";
  const tokens = sandbox.split(/\s+/).filter(Boolean);
  expect(tokens).toContain("allow-scripts");
  expect(tokens).not.toContain("allow-same-origin");

  // Text alternative: the Table tab renders the same data as a real table in the host document.
  await page.getByRole("tab", { name: "Table" }).click();
  const table = page.getByRole("table", { name: "Cost by month" });
  await expect(table).toBeVisible();
  expect(await table.evaluate((el) => el.ownerDocument === document && !el.closest("iframe"))).toBe(
    true,
  );
  await expect(table.getByRole("row")).not.toHaveCount(0);
  await page.getByRole("tab", { name: "Chart" }).click();

  const { violations, counts, analyzedFrames } = await analyze(page);
  record({
    kind: "special",
    pattern: "chart-harness",
    name: "sandboxed chart iframe",
    url: HARNESS,
    mode: "light",
    packId: "default",
    sandboxMode: false,
    counts,
    violations,
    note: analyzedFrames
      ? "axe reached the opaque-origin sandboxed iframe content through Playwright frame injection."
      : "axe results carried no iframe-scoped nodes: the sandboxed frame (opaque origin) content was not analyzed. The host-side contract (title, sandbox tokens, table outside the frame) is asserted instead.",
  });
  expect(blocking(violations), describeBlocking(violations)).toEqual([]);
});

test("reports view hosts the chart in a titled sandboxed iframe", async ({ page }) => {
  await seedPreferences(page, { mode: "light" });
  await openSample(page, reportView);
  const iframes = page.locator("iframe");
  const count = await iframes.count();
  expect(count).toBeGreaterThan(0);
  for (let i = 0; i < count; i += 1) {
    expect(((await iframes.nth(i).getAttribute("title")) ?? "").trim()).not.toBe("");
    const tokens = ((await iframes.nth(i).getAttribute("sandbox")) ?? "").split(/\s+/);
    expect(tokens).not.toContain("allow-same-origin");
  }
});
