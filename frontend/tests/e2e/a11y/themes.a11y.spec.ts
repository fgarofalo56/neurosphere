import { expect, test } from "../../e2e-support/fixtures.ts";
import {
  analyze,
  blocking,
  describeBlocking,
  MODES,
  openSample,
  PACKS,
  record,
  seedPreferences,
  writeAggregate,
} from "./axe-support.ts";
import { ROUTE_SAMPLES, THEME_MATRIX_PATTERNS } from "./route-samples.ts";

// PRP-24 item 3: every theme pack x light/dark/high-contrast on a representative route set, with
// colour-contrast included (axe runs it in a real browser). Zero serious or critical.

test.afterAll(() => {
  writeAggregate();
});

for (const pattern of THEME_MATRIX_PATTERNS) {
  const sample = ROUTE_SAMPLES.find((s) => s.pattern === pattern);
  if (!sample) throw new Error(`no route sample for ${pattern}`);
  for (const packId of PACKS) {
    for (const mode of MODES) {
      test(`axe: ${pattern} with pack ${packId} in ${mode}`, async ({ page }) => {
        await seedPreferences(page, { mode, packId });
        await openSample(page, sample);
        // The stored preference must have been applied, or the matrix proves nothing.
        const stored = await page.evaluate(() => window.localStorage.getItem("ns.theme"));
        expect(JSON.parse(stored ?? "{}")).toEqual({ packId, themeName: mode });
        const { violations, counts } = await analyze(page);
        record({
          kind: "theme",
          pattern,
          name: sample.name,
          url: sample.url,
          mode,
          packId,
          sandboxMode: false,
          counts,
          violations,
        });
        expect(blocking(violations), describeBlocking(violations)).toEqual([]);
      });
    }
  }
}
