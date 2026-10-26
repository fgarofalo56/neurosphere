import type { Theme } from "@fluentui/react-components";
import { highContrastChartPalette, highContrastHealthPalette } from "../tokens";
import type { ThemeName } from "../tokens";
import { TEXT_MIN, TEXT_PAIRS, UI_MIN, UI_PAIRS, pairRatio, resolveTheme } from "../themes";
import type { ThemePack } from "../themes";
import type { UiStyle, UiStyleState } from "./types";

/**
 * Neutral surface, stroke, shadow and radius tokens a style may override. Brand, foreground and
 * focus tokens belong to the pack and the PRP-04 sets, so a style can never touch them.
 */
export const STYLE_OVERRIDE_ALLOWLIST: ReadonlySet<string> = new Set<keyof Theme>([
  "colorNeutralBackground2",
  "colorNeutralBackground3",
  "colorNeutralBackground4",
  "colorNeutralBackground5",
  "colorNeutralBackground6",
  "colorNeutralStroke1",
  "colorNeutralStroke2",
  "colorNeutralStroke3",
  "shadow2",
  "shadow4",
  "shadow8",
  "shadow16",
  "borderRadiusNone",
  "borderRadiusSmall",
  "borderRadiusMedium",
  "borderRadiusLarge",
  "borderRadiusXLarge",
]);

/** True when every PRP-24 guarded pair keeps its minimum (4.5:1 text, 3:1 UI). */
function passesGuards(theme: Theme): boolean {
  return (
    TEXT_PAIRS.every(([fg, bg]) => pairRatio(theme, fg, bg) >= TEXT_MIN) &&
    UI_PAIRS.every(([fg, bg]) => pairRatio(theme, fg, bg) >= UI_MIN)
  );
}

/**
 * Composes mode x pack x style into a Fluent theme. The pack/mode theme is resolved first; the
 * style's allowlisted overrides are layered on top only if every guarded pair still passes,
 * otherwise they are dropped as a whole. High-contrast ignores style colours entirely.
 */
export function resolveStyledTheme(pack: ThemePack, mode: ThemeName, style: UiStyle): Theme {
  const base = resolveTheme(pack, mode);
  if (mode === "high-contrast") return base;
  const raw = style.overrides?.[mode];
  if (!raw) return base;
  const allowed: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(raw)) {
    if (STYLE_OVERRIDE_ALLOWLIST.has(key)) allowed[key] = value;
  }
  if (Object.keys(allowed).length === 0) return base;
  const candidate: Theme = { ...base, ...(allowed as Partial<Theme>) };
  return passesGuards(candidate) ? candidate : base;
}

/** Density and treatment apply in every mode; chart and health use the HC variants in HC. */
export function resolveUiStyle(style: UiStyle, mode: ThemeName): UiStyleState {
  if (mode === "high-contrast") {
    return {
      id: style.id,
      density: style.density,
      chart: highContrastChartPalette,
      health: highContrastHealthPalette,
      treatment: { ...style.treatment, surface: "flat", border: "strong" },
    };
  }
  return {
    id: style.id,
    density: style.density,
    chart: style.chart[mode],
    health: style.health[mode],
    treatment: style.treatment,
  };
}
