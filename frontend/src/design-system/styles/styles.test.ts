import { describe, expect, it } from "vitest";
import {
  THEME_PACKS,
  TEXT_MIN,
  TEXT_PAIRS,
  UI_MIN,
  UI_PAIRS,
  contrastRatio,
  pairRatio,
} from "../themes";
import { THEME_NAMES, highContrastTheme } from "../tokens";
import type { ThemeName } from "../tokens";
import {
  DEFAULT_UI_STYLE_ID,
  STYLE_OVERRIDE_ALLOWLIST,
  UI_STYLES,
  UI_STYLE_IDS,
  getUiStyle,
  isUiStyleId,
  resolveStyledTheme,
  resolveUiStyle,
} from "./index";
import type { UiStyle } from "./index";

const STYLES = Object.values(UI_STYLES);
const PACKS = Object.values(THEME_PACKS);

describe("registry", () => {
  it("has exactly the two styles", () => {
    expect([...UI_STYLE_IDS].sort()).toEqual(["enterprise-fluent", "ops-console"]);
    expect(Object.keys(UI_STYLES).sort()).toEqual(["enterprise-fluent", "ops-console"]);
    expect(DEFAULT_UI_STYLE_ID).toBe("enterprise-fluent");
  });

  it("validates ids and falls back to the default", () => {
    expect(isUiStyleId("ops-console")).toBe(true);
    expect(isUiStyleId("nope")).toBe(false);
    expect(isUiStyleId(undefined)).toBe(false);
    expect(isUiStyleId("toString")).toBe(false);
    expect(getUiStyle("nope").id).toBe("enterprise-fluent");
    expect(getUiStyle(null).id).toBe("enterprise-fluent");
  });

  it("declares preferred modes and densities", () => {
    expect(UI_STYLES["ops-console"].preferredMode).toBe("dark");
    expect(UI_STYLES["enterprise-fluent"].preferredMode).toBe("light");
    expect(UI_STYLES["ops-console"].density).toBe("compact");
    expect(UI_STYLES["enterprise-fluent"].density).toBe("comfortable");
  });
});

describe("every style x mode x pack keeps the PRP-24 guards", () => {
  for (const style of STYLES) {
    for (const mode of THEME_NAMES) {
      for (const pack of PACKS) {
        it(`${style.id} / ${mode} / ${pack.id}`, () => {
          const theme = resolveStyledTheme(pack, mode, style);
          const min = mode === "high-contrast" ? 7 : undefined;
          for (const [fg, bg] of TEXT_PAIRS) {
            expect(pairRatio(theme, fg, bg), `${fg} on ${bg}`).toBeGreaterThanOrEqual(
              min ?? TEXT_MIN,
            );
          }
          for (const [fg, bg] of UI_PAIRS) {
            expect(pairRatio(theme, fg, bg), `${fg} on ${bg}`).toBeGreaterThanOrEqual(
              min ?? UI_MIN,
            );
          }
        });
      }
    }
  }
});

describe("override guard", () => {
  const pack = THEME_PACKS["default"]!;
  const base = UI_STYLES["enterprise-fluent"];

  it("applies safe allowlisted overrides", () => {
    const theme = resolveStyledTheme(pack, "light", base);
    expect(theme.borderRadiusLarge).toBe("8px");
    const ops = resolveStyledTheme(pack, "dark", UI_STYLES["ops-console"]);
    expect(ops.colorNeutralBackground3).toBe("#0f1216");
  });

  it("drops a deliberately failing override as a whole", () => {
    const failing: UiStyle = {
      ...base,
      overrides: {
        light: { colorNeutralBackground2: "#202020", borderRadiusLarge: "20px" },
      },
    };
    const plain = resolveStyledTheme(pack, "light", { ...base, overrides: undefined });
    const theme = resolveStyledTheme(pack, "light", failing);
    expect(theme).toEqual(plain);
    expect(theme.borderRadiusLarge).not.toBe("20px");
  });

  it("drops keys outside the allowlist", () => {
    const sneaky: UiStyle = {
      ...base,
      overrides: {
        light: {
          colorNeutralForeground1: "#ff00ff",
          colorBrandBackground: "#00ff00",
          borderRadiusMedium: "6px",
        },
      },
    };
    const theme = resolveStyledTheme(pack, "light", sneaky);
    const plain = resolveStyledTheme(pack, "light", { ...base, overrides: undefined });
    expect(theme.colorNeutralForeground1).toBe(plain.colorNeutralForeground1);
    expect(theme.colorBrandBackground).toBe(plain.colorBrandBackground);
    expect(theme.borderRadiusMedium).toBe("6px");
    expect(STYLE_OVERRIDE_ALLOWLIST.has("colorNeutralForeground1")).toBe(false);
    expect(STYLE_OVERRIDE_ALLOWLIST.has("colorNeutralBackground1")).toBe(false);
  });

  it("high-contrast ignores style colours but keeps density and treatment", () => {
    const loud: UiStyle = {
      ...base,
      overrides: { light: {}, dark: { colorNeutralBackground2: "#123456" } },
    };
    for (const style of [...STYLES, loud]) {
      for (const pack of PACKS) {
        expect(resolveStyledTheme(pack, "high-contrast", style)).toEqual(
          resolveStyledTheme(pack, "high-contrast", { ...style, overrides: undefined }),
        );
      }
    }
    expect(resolveStyledTheme(pack, "high-contrast", base).colorNeutralBackground1).toBe(
      highContrastTheme.colorNeutralBackground1,
    );
    const hcOps = resolveUiStyle(UI_STYLES["ops-console"], "high-contrast");
    expect(hcOps.density).toBe("compact");
    expect(hcOps.treatment.uppercaseLabels).toBe(true);
    expect(hcOps.treatment.border).toBe("strong");
    const hcEnt = resolveUiStyle(UI_STYLES["enterprise-fluent"], "high-contrast");
    expect(hcEnt.density).toBe("comfortable");
    // Chart and health colours are the same HC set for both styles.
    expect(hcEnt.chart).toEqual(hcOps.chart);
    expect(hcEnt.health).toEqual(hcOps.health);
  });
});

describe("health palettes", () => {
  for (const style of STYLES) {
    for (const mode of THEME_NAMES) {
      it(`${style.id} / ${mode}: fg and icon are at least 3:1 on colorNeutralBackground1`, () => {
        for (const pack of PACKS) {
          const theme = resolveStyledTheme(pack, mode, style);
          const surface = String(theme.colorNeutralBackground1);
          const { health } = resolveUiStyle(style, mode);
          for (const state of ["ok", "degraded", "failing", "unknown"] as const) {
            expect(contrastRatio(health[state].fg, surface), `${state} fg`).toBeGreaterThanOrEqual(
              3,
            );
            expect(
              contrastRatio(health[state].icon, surface),
              `${state} icon`,
            ).toBeGreaterThanOrEqual(3);
          }
        }
      });

      it(`${style.id} / ${mode}: health fg is readable on its own tint`, () => {
        const { health } = resolveUiStyle(style, mode);
        for (const state of ["ok", "degraded", "failing", "unknown"] as const) {
          expect(
            contrastRatio(health[state].fg, health[state].bg),
            `${state}`,
          ).toBeGreaterThanOrEqual(4.5);
        }
      });
    }
  }
});

describe("chart themes", () => {
  it("distinguish estimated (dashed) from invoiced (solid) in every style and mode", () => {
    for (const style of STYLES) {
      for (const mode of THEME_NAMES) {
        const { chart } = resolveUiStyle(style, mode);
        expect(chart.invoiced.dash).toBeNull();
        expect(chart.estimated.dash).not.toBeNull();
        expect(chart.estimated.fillOpacity).toBeLessThan(chart.invoiced.fillOpacity);
        expect(chart.categorical.length).toBeGreaterThanOrEqual(5);
      }
    }
  });

  it("chart lines and axes are at least 3:1 on the surface", () => {
    for (const style of STYLES) {
      for (const mode of THEME_NAMES as readonly ThemeName[]) {
        const theme = resolveStyledTheme(THEME_PACKS["default"]!, mode, style);
        const surface = String(theme.colorNeutralBackground1);
        const { chart } = resolveUiStyle(style, mode);
        for (const colour of [chart.invoiced.stroke, chart.estimated.stroke, chart.axis]) {
          expect(
            contrastRatio(colour, surface),
            `${style.id} ${mode} ${colour}`,
          ).toBeGreaterThanOrEqual(3);
        }
      }
    }
  });
});
