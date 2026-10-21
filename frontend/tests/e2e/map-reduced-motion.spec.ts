import type { Page } from "@playwright/test";
import { expect, test } from "../e2e-support/fixtures.ts";
import { DOMAIN_OK } from "../mock-api/server.ts";

// PRP-18 item 3: edge animation honours prefers-reduced-motion AND the in-app toggle, and only
// OBSERVED edges ever animate. The signals are attributes on the map container:
//   data-edge-animation   "on" | "off"
//   data-animated-edges   number of edges the animator moves (observed only, 0 when off)
//   data-animation-frames frames the animator has run since it was (re)started

const MAP_URL = `/map?domain_id=${encodeURIComponent(DOMAIN_OK)}`;

interface ViewportBody {
  edges: { provenance: string }[];
}

async function openMap(page: Page): Promise<{ observed: number; others: number }> {
  const viewport = page.waitForResponse((r) => r.url().includes("/viewport") && r.status() === 200);
  await page.goto(MAP_URL);
  const body = (await (await viewport).json()) as ViewportBody;
  await expect(page.getByTestId("map-canvas")).toHaveAttribute("data-node-count", /^[1-9]/);
  const observed = body.edges.filter((e) => e.provenance === "observed").length;
  return { observed, others: body.edges.length - observed };
}

const frames = async (page: Page): Promise<number> =>
  Number(await page.getByTestId("map-canvas").getAttribute("data-animation-frames"));

test.describe("map reduced motion", () => {
  test("no preference: only observed edges animate", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "no-preference" });
    const { observed, others } = await openMap(page);
    expect(observed).toBeGreaterThan(0);
    expect(others).toBeGreaterThan(0); // declared and inferred edges exist and stay static
    const canvas = page.getByTestId("map-canvas");
    await expect(canvas).toHaveAttribute("data-edge-animation", "on");
    await expect(canvas).toHaveAttribute("data-animated-edges", String(observed));
    await expect.poll(() => frames(page)).toBeGreaterThan(3);
    await expect(page.getByTestId("animation-status")).toHaveText("Observed edges animate");
  });

  test("system prefers-reduced-motion: no animation frames at all", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await openMap(page);
    const canvas = page.getByTestId("map-canvas");
    await expect(canvas).toHaveAttribute("data-edge-animation", "off");
    await expect(canvas).toHaveAttribute("data-animated-edges", "0");
    await page.waitForTimeout(600);
    expect(await frames(page)).toBe(0);
    await expect(page.getByTestId("animation-status")).toHaveText("Edge animation is off");
    // The system preference cannot be switched back on from the app.
    const toggle = page.getByRole("switch", { name: /reduce motion/i });
    await expect(toggle).toBeChecked();
    await expect(toggle).toBeDisabled();
  });

  test("in-app toggle turns animation off and back on", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "no-preference" });
    const { observed } = await openMap(page);
    const canvas = page.getByTestId("map-canvas");
    const toggle = page.getByRole("switch", { name: /reduce motion/i });
    await expect(canvas).toHaveAttribute("data-edge-animation", "on");

    await toggle.click();
    await expect(canvas).toHaveAttribute("data-edge-animation", "off");
    await expect(canvas).toHaveAttribute("data-animated-edges", "0");
    await page.waitForTimeout(400);
    expect(await frames(page)).toBe(0);

    await toggle.click();
    await expect(canvas).toHaveAttribute("data-edge-animation", "on");
    await expect(canvas).toHaveAttribute("data-animated-edges", String(observed));
    await expect.poll(() => frames(page)).toBeGreaterThan(3);
  });
});

// The same page, but the labels that must never be missing from the map (coverage, truncation,
// the table alternative, the live-updates state). The mock API has no realtime gateway, so the
// page must say live updates are unavailable instead of pretending to be live.
test.describe("map page states", () => {
  test("labels coverage and truncation, links to the table, and says live is unavailable", async ({
    page,
  }) => {
    await openMap(page);
    await expect(page.getByTestId("coverage-label")).toHaveAttribute(
      "data-coverage-state",
      "partial",
    );
    await expect(page.getByTestId("truncation-banner")).toContainText("node budget reached");
    const table = page.getByRole("link", { name: "View as table" });
    await expect(table).toBeVisible();
    await expect(table).toHaveAttribute("href", /^\/map\/table\?domain_id=/);
    await expect(page.getByRole("region", { name: /Agent topology map/ })).toBeVisible();
    await expect(page.getByTestId("live-status")).toHaveAttribute(
      "data-live-status",
      "unavailable",
      { timeout: 15_000 },
    );
    await expect(page.getByTestId("map-legend")).toContainText("no data (never shown as 0)");
  });

  test("expands a cluster and labels the delayed page", async ({ page }) => {
    await openMap(page);
    const canvas = page.getByTestId("map-canvas");
    await canvas.scrollIntoViewIfNeeded();
    const box = await canvas.boundingBox();
    if (box === null) throw new Error("map has no box");
    const at = await page.evaluate(() => {
      const hook = (
        document.querySelector('[data-testid="map-canvas"]') as HTMLElement & {
          __nsMap: {
            sigma: {
              getNodeDisplayData(id: string): { x: number; y: number };
              framedGraphToViewport(c: { x: number; y: number }): { x: number; y: number };
            };
          };
        }
      ).__nsMap;
      const d = hook.sigma.getNodeDisplayData("cluster:agents");
      return hook.sigma.framedGraphToViewport({ x: d.x, y: d.y });
    });
    await page.mouse.click(box.x + at.x, box.y + at.y);
    const panel = page.getByTestId("node-panel");
    await expect(panel).toBeVisible();
    const before = Number(
      (await page.getByTestId("node-count").innerText()).match(/^(\d+) nodes/)?.[1],
    );
    await panel.getByRole("button", { name: "Expand cluster" }).click();
    // Page 1 of the cluster; page 2 (served with ?cursor=page-2) is the delayed one.
    await panel.getByRole("button", { name: "Load more" }).click();
    await expect(page.getByTestId("coverage-label")).toHaveAttribute(
      "data-coverage-state",
      "delayed",
    );
    await expect(page.getByTestId("coverage-label")).toContainText("300 s behind");
    const after = Number(
      (await page.getByTestId("node-count").innerText()).match(/^(\d+) nodes/)?.[1],
    );
    expect(after).toBeGreaterThan(before);
  });
});
