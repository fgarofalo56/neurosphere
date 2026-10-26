import type { Page } from "@playwright/test";
import { expect, test } from "../../e2e-support/fixtures.ts";
import {
  openSample,
  seedPreferences,
  STYLES,
  type Mode,
  type StyleId,
} from "../a11y/axe-support.ts";
import { ROUTE_SAMPLES } from "../a11y/route-samples.ts";

// PRP-30 item 10: pixel baselines (Linux only, authoritative in the pinned Playwright image; see
// frontend/scripts/update-visual-baselines.mjs). 2 styles x {light, dark} x 6 pages = 24, plus
// high-contrast home in both styles = 26. Only the `visual` project runs this file.

test.use({
  viewport: { width: 1440, height: 900 },
  timezoneId: "UTC",
  locale: "en-US",
  colorScheme: "light",
  reducedMotion: "reduce",
});

const FIXED_NOW = new Date("2026-10-24T12:00:00.000Z");

const PAGES = [
  { slug: "home", pattern: "/" },
  { slug: "cost-dashboard", pattern: "/dashboards/cost" },
  { slug: "map", pattern: "/map" },
  { slug: "map-table", pattern: "/map/table" },
  { slug: "recommendations", pattern: "/recommendations" },
  { slug: "actions", pattern: "/actions" },
] as const;

function sampleFor(pattern: string) {
  const sample = ROUTE_SAMPLES.find((s) => s.pattern === pattern);
  if (!sample) throw new Error(`no route sample for ${pattern}`);
  return sample;
}

async function shoot(
  page: Page,
  opts: { slug: string; pattern: string; style: StyleId; mode: Mode },
): Promise<void> {
  // A fixed (non-ticking) clock makes every "x minutes ago" label deterministic.
  await page.clock.setFixedTime(FIXED_NOW);
  await seedPreferences(page, { mode: opts.mode, styleId: opts.style });
  await openSample(page, sampleFor(opts.pattern));
  await page.evaluate(() => document.fonts.ready);
  // The map is WebGL (software rendered in headless); the canvas is masked, never compared.
  const masks = [page.locator("canvas"), page.getByTestId("map-canvas")];
  await expect(page).toHaveScreenshot(`${opts.style}-${opts.mode}-${opts.slug}.png`, {
    animations: "disabled",
    caret: "hide",
    mask: masks,
    maxDiffPixelRatio: 0.01,
    threshold: 0.2,
  });
}

for (const style of STYLES) {
  for (const mode of ["light", "dark"] as const) {
    for (const p of PAGES) {
      test(`visual: ${p.slug} in ${style} ${mode}`, async ({ page }) => {
        await shoot(page, { ...p, style, mode });
      });
    }
  }
  test(`visual: home in ${style} high-contrast`, async ({ page }) => {
    await shoot(page, { slug: "home", pattern: "/", style, mode: "high-contrast" });
  });
}
