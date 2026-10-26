import { describe, expect, it } from "vitest";
import { THEME_PACKS } from "../themes";
import { UI_STYLES, resolveStyledTheme, resolveUiStyle } from "./index";

const PACKS = Object.values(THEME_PACKS);
const STYLES = Object.values(UI_STYLES);

describe("Ops console is its own personality (PRP-30 rework round 1)", () => {
  it("applies the near-black canvas and hairline treatment in every pack (all guards pass)", () => {
    for (const pack of PACKS) {
      const dark = resolveStyledTheme(pack, "dark", UI_STYLES["ops-console"]);
      expect(dark.colorNeutralBackground3).toBe("#080a0d");
      expect(dark.colorNeutralBackground2).toBe("#12161b");
      expect(dark.shadow4).toBe("none");
      const light = resolveStyledTheme(pack, "light", UI_STYLES["ops-console"]);
      expect(light.colorNeutralBackground3).toBe("#e7ebf0");
      expect(light.shadow4).toBe("none");
    }
  });

  it("differs from Enterprise Fluent in treatment, not only in case and radius", () => {
    const ops = UI_STYLES["ops-console"].treatment;
    const ent = UI_STYLES["enterprise-fluent"].treatment;
    expect(ops.kpiAccent).not.toBe(ent.kpiAccent);
    expect(ops.numerals).not.toBe(ent.numerals);
    expect(ops.panelSurface).not.toBe(ent.panelSurface);
    expect(ops.liveIndicator).not.toBe(ent.liveIndicator);
  });

  it("estimated and invoiced have distinct strokes and light fills in every style and mode", () => {
    for (const style of STYLES) {
      for (const mode of ["light", "dark"] as const) {
        const { chart } = resolveUiStyle(style, mode);
        expect(chart.estimated.stroke).not.toBe(chart.invoiced.stroke);
        expect(chart.invoiced.fillOpacity).toBeLessThanOrEqual(0.15);
      }
    }
  });
});
