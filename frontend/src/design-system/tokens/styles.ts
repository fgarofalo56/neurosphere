import type { Theme } from "@fluentui/react-components";
import { highContrastPalette as hc } from "./brand";

/**
 * PRP-30 UI style palettes. Hex literals for style overrides, chart themes and health palettes
 * live here (and only here, per tokens.test.ts). The styles/ module composes them.
 */

export type StyleKey = "ops-console" | "enterprise-fluent";
export type StyleColourMode = "light" | "dark";

export interface ChartSeriesStyle {
  stroke: string;
  /** SVG stroke-dasharray, or null for a solid line. */
  dash: string | null;
  strokeWidth: number;
  fill: string;
  fillOpacity: number;
}

export interface ChartPalette {
  categorical: readonly string[];
  /** Estimated series: dashed, lighter fill. */
  estimated: ChartSeriesStyle;
  /** Invoiced series: solid. */
  invoiced: ChartSeriesStyle;
  grid: string;
  axis: string;
  unknownGap: string;
  incompleteMarker: string;
  tooltip: { background: string; foreground: string; border: string };
}

export interface HealthColours {
  /** Text and glyph colour, at least 3:1 against colorNeutralBackground1. */
  fg: string;
  /** Tinted fill behind the indicator. */
  bg: string;
  /** Icon glyph colour, at least 3:1 against colorNeutralBackground1. */
  icon: string;
}

export interface HealthPaletteTokens {
  ok: HealthColours;
  degraded: HealthColours;
  failing: HealthColours;
  unknown: HealthColours;
}

type StyleOverrideTokens = Partial<Record<StyleColourMode, Partial<Theme>>>;

/** Candidate neutral surface, stroke, shadow and radius overrides (guarded again at resolve time). */
export const styleOverrideTokens: Readonly<Record<StyleKey, StyleOverrideTokens>> = {
  "ops-console": {
    light: {
      colorNeutralBackground2: "#f1f3f5",
      colorNeutralBackground3: "#e6e9ec",
      colorNeutralStroke2: "#d0d5db",
      borderRadiusSmall: "2px",
      borderRadiusMedium: "2px",
      borderRadiusLarge: "4px",
      shadow4: "0 1px 2px rgba(0, 0, 0, 0.2)",
    },
    dark: {
      colorNeutralBackground2: "#15191e",
      colorNeutralBackground3: "#0f1216",
      colorNeutralStroke2: "#3a424b",
      borderRadiusSmall: "2px",
      borderRadiusMedium: "2px",
      borderRadiusLarge: "4px",
      shadow4: "0 1px 2px rgba(0, 0, 0, 0.6)",
    },
  },
  "enterprise-fluent": {
    light: {
      colorNeutralBackground2: "#fafafa",
      colorNeutralBackground3: "#f5f5f5",
      borderRadiusMedium: "4px",
      borderRadiusLarge: "8px",
      shadow4: "0 0 2px rgba(0, 0, 0, 0.12), 0 2px 4px rgba(0, 0, 0, 0.14)",
    },
    dark: {
      colorNeutralBackground2: "#1f1f1f",
      colorNeutralBackground3: "#1a1a1a",
      borderRadiusMedium: "4px",
      borderRadiusLarge: "8px",
      shadow4: "0 0 2px rgba(0, 0, 0, 0.24), 0 2px 4px rgba(0, 0, 0, 0.28)",
    },
  },
};

export const chartPalettes: Readonly<Record<StyleKey, Record<StyleColourMode, ChartPalette>>> = {
  "enterprise-fluent": {
    light: {
      categorical: [
        "#0f6cbd",
        "#107c10",
        "#c239b3",
        "#bc4b09",
        "#5c2e91",
        "#008272",
        "#8e562e",
        "#4f6bed",
      ],
      invoiced: {
        stroke: "#0f6cbd",
        dash: null,
        strokeWidth: 2,
        fill: "#0f6cbd",
        fillOpacity: 0.28,
      },
      estimated: {
        stroke: "#4f6bed",
        dash: "6 4",
        strokeWidth: 2,
        fill: "#4f6bed",
        fillOpacity: 0.1,
      },
      grid: "#e0e0e0",
      axis: "#616161",
      unknownGap: "#8a8886",
      incompleteMarker: "#bc4b09",
      tooltip: { background: "#ffffff", foreground: "#242424", border: "#d1d1d1" },
    },
    dark: {
      categorical: [
        "#479ef5",
        "#6ccb5f",
        "#e47ad6",
        "#f4a261",
        "#b49cdb",
        "#4cc2b4",
        "#d4a373",
        "#8ea2ff",
      ],
      invoiced: {
        stroke: "#479ef5",
        dash: null,
        strokeWidth: 2,
        fill: "#479ef5",
        fillOpacity: 0.3,
      },
      estimated: {
        stroke: "#8ea2ff",
        dash: "6 4",
        strokeWidth: 2,
        fill: "#8ea2ff",
        fillOpacity: 0.12,
      },
      grid: "#3d3d3d",
      axis: "#c7c7c7",
      unknownGap: "#a6a6a6",
      incompleteMarker: "#f4a261",
      tooltip: { background: "#333333", foreground: "#ffffff", border: "#5c5c5c" },
    },
  },
  "ops-console": {
    light: {
      categorical: [
        "#0b6a9b",
        "#0e700e",
        "#a4262c",
        "#7a5200",
        "#5b3a9d",
        "#00695c",
        "#7a4a1f",
        "#2f4fc4",
      ],
      invoiced: {
        stroke: "#0b6a9b",
        dash: null,
        strokeWidth: 1.5,
        fill: "#0b6a9b",
        fillOpacity: 0.25,
      },
      estimated: {
        stroke: "#2f4fc4",
        dash: "4 3",
        strokeWidth: 1.5,
        fill: "#2f4fc4",
        fillOpacity: 0.08,
      },
      grid: "#d9dde2",
      axis: "#4d555e",
      unknownGap: "#7b838c",
      incompleteMarker: "#7a5200",
      tooltip: { background: "#ffffff", foreground: "#1b1f24", border: "#aab1b9" },
    },
    dark: {
      categorical: [
        "#4fc3f7",
        "#6ccb5f",
        "#ff8f98",
        "#ffd335",
        "#b9a3f0",
        "#4dd0c0",
        "#e0a96d",
        "#8fa6ff",
      ],
      invoiced: {
        stroke: "#4fc3f7",
        dash: null,
        strokeWidth: 1.5,
        fill: "#4fc3f7",
        fillOpacity: 0.28,
      },
      estimated: {
        stroke: "#8fa6ff",
        dash: "4 3",
        strokeWidth: 1.5,
        fill: "#8fa6ff",
        fillOpacity: 0.1,
      },
      grid: "#2b323a",
      axis: "#b4bcc5",
      unknownGap: "#8f98a2",
      incompleteMarker: "#ffd335",
      tooltip: { background: "#1b2027", foreground: "#f2f4f6", border: "#46505b" },
    },
  },
};

export const healthPalettes: Readonly<
  Record<StyleKey, Record<StyleColourMode, HealthPaletteTokens>>
> = {
  "enterprise-fluent": {
    light: {
      ok: { fg: "#107c10", bg: "#dff6dd", icon: "#107c10" },
      degraded: { fg: "#835b00", bg: "#fff4ce", icon: "#835b00" },
      failing: { fg: "#b10e1c", bg: "#fde7e9", icon: "#b10e1c" },
      unknown: { fg: "#616161", bg: "#f0f0f0", icon: "#616161" },
    },
    dark: {
      ok: { fg: "#54b054", bg: "#0e2f0e", icon: "#54b054" },
      degraded: { fg: "#fce100", bg: "#3b3000", icon: "#fce100" },
      failing: { fg: "#f1707b", bg: "#3f1011", icon: "#f1707b" },
      unknown: { fg: "#a6a6a6", bg: "#2e2e2e", icon: "#a6a6a6" },
    },
  },
  "ops-console": {
    light: {
      ok: { fg: "#0e700e", bg: "#d8f0d5", icon: "#0e700e" },
      degraded: { fg: "#7a5200", bg: "#fbefc2", icon: "#7a5200" },
      failing: { fg: "#a4262c", bg: "#fadcdf", icon: "#a4262c" },
      unknown: { fg: "#5c5c5c", bg: "#eceeef", icon: "#5c5c5c" },
    },
    dark: {
      ok: { fg: "#6ccb5f", bg: "#0c2a10", icon: "#6ccb5f" },
      degraded: { fg: "#ffd335", bg: "#352b00", icon: "#ffd335" },
      failing: { fg: "#ff8f98", bg: "#3a0f13", icon: "#ff8f98" },
      unknown: { fg: "#b0b0b0", bg: "#262b31", icon: "#b0b0b0" },
    },
  },
};

/** High-contrast variants, built only from the PRP-04 HC palette. Style colours never apply. */
export const highContrastChartPalette: ChartPalette = {
  categorical: [hc.yellow, hc.cyan, hc.green, hc.white, hc.red],
  invoiced: { stroke: hc.white, dash: null, strokeWidth: 3, fill: hc.white, fillOpacity: 0.35 },
  estimated: { stroke: hc.yellow, dash: "6 4", strokeWidth: 3, fill: hc.yellow, fillOpacity: 0.12 },
  grid: hc.gray,
  axis: hc.white,
  unknownGap: hc.cyan,
  incompleteMarker: hc.yellow,
  tooltip: { background: hc.black, foreground: hc.white, border: hc.white },
};

export const highContrastHealthPalette: HealthPaletteTokens = {
  ok: { fg: hc.green, bg: hc.gray, icon: hc.green },
  degraded: { fg: hc.yellow, bg: hc.gray, icon: hc.yellow },
  failing: { fg: hc.red, bg: hc.gray, icon: hc.red },
  unknown: { fg: hc.white, bg: hc.gray, icon: hc.white },
};
