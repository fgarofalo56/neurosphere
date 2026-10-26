import { chartPalettes, healthPalettes, styleOverrideTokens } from "../tokens";
import type { UiStyle, UiStyleId } from "./types";

export const DEFAULT_UI_STYLE_ID: UiStyleId = "enterprise-fluent";

export const UI_STYLE_IDS: readonly UiStyleId[] = ["ops-console", "enterprise-fluent"];

export const opsConsoleStyle: UiStyle = {
  id: "ops-console",
  displayName: "Ops console",
  preferredMode: "dark",
  density: "compact",
  treatment: {
    surface: "flat",
    border: "strong",
    tableStripes: true,
    uppercaseLabels: true,
    radius: "small",
    panelSurface: "lifted",
    kpiAccent: "edge",
    numerals: "tabular",
    monoNumerals: true,
    kpiMaxAcross: 6,
    liveIndicator: true,
  },
  overrides: styleOverrideTokens["ops-console"],
  chart: chartPalettes["ops-console"],
  health: healthPalettes["ops-console"],
};

export const enterpriseFluentStyle: UiStyle = {
  id: "enterprise-fluent",
  displayName: "Enterprise Fluent",
  preferredMode: "light",
  density: "comfortable",
  treatment: {
    surface: "raised",
    border: "subtle",
    tableStripes: false,
    uppercaseLabels: false,
    radius: "medium",
    panelSurface: "base",
    kpiAccent: "none",
    numerals: "proportional",
    monoNumerals: false,
    kpiMaxAcross: 5,
    liveIndicator: false,
  },
  overrides: styleOverrideTokens["enterprise-fluent"],
  chart: chartPalettes["enterprise-fluent"],
  health: healthPalettes["enterprise-fluent"],
};

export const UI_STYLES: Readonly<Record<UiStyleId, UiStyle>> = {
  "ops-console": opsConsoleStyle,
  "enterprise-fluent": enterpriseFluentStyle,
};

export function isUiStyleId(value: unknown): value is UiStyleId {
  return typeof value === "string" && Object.prototype.hasOwnProperty.call(UI_STYLES, value);
}

/** Unknown or missing ids fall back to the built-in default style. */
export function getUiStyle(id: string | null | undefined): UiStyle {
  return isUiStyleId(id) ? UI_STYLES[id] : UI_STYLES[DEFAULT_UI_STYLE_ID];
}
