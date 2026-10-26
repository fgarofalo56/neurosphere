import { expect, test } from "../../e2e-support/fixtures.ts";
import { openSample, seedPreferences, STYLES } from "../a11y/axe-support.ts";
import { ROUTE_SAMPLES } from "../a11y/route-samples.ts";

// PRP-30 item 10: no StatusPill may overflow its parent on home or the cost dashboard, in either
// UI style. Runs in the default chromium project (no pixel baselines needed).

const PILL = "[data-slot='status-pill']";
const PAGES = ["/", "/dashboards/cost"] as const;

interface Overflow {
  readonly text: string;
  readonly reason: string;
}

for (const pattern of PAGES) {
  const sample = ROUTE_SAMPLES.find((s) => s.pattern === pattern);
  if (!sample) throw new Error(`no route sample for ${pattern}`);
  for (const styleId of STYLES) {
    test(`status pills stay inside their parent on ${pattern} in ${styleId}`, async ({ page }) => {
      await page.setViewportSize({ width: 1440, height: 900 });
      await seedPreferences(page, { mode: "light", styleId });
      await openSample(page, sample);
      await expect(page.locator(PILL).first()).toBeVisible();

      const result = await page.evaluate((selector) => {
        const pills = Array.from(document.querySelectorAll<HTMLElement>(selector));
        const bad: Overflow[] = [];
        for (const pill of pills) {
          const text = (pill.textContent ?? "").trim();
          if (pill.scrollWidth > pill.clientWidth + 1) {
            bad.push({
              text,
              reason: `own content wider (${pill.scrollWidth} > ${pill.clientWidth})`,
            });
          }
          const parent = pill.parentElement;
          if (!parent) continue;
          const a = pill.getBoundingClientRect();
          const b = parent.getBoundingClientRect();
          if (a.right > b.right + 1 || a.left < b.left - 1) {
            bad.push({
              text,
              reason: `outside parent horizontally (pill ${a.left}..${a.right}, parent ${b.left}..${b.right})`,
            });
          }
        }
        return { count: pills.length, bad };
      }, PILL);

      expect(result.count).toBeGreaterThan(0);
      expect(result.bad, JSON.stringify(result.bad)).toEqual([]);
    });
  }
}
