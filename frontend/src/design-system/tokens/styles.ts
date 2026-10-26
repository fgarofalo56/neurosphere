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
    // NOC console: panels sit on Background2 over a cool canvas on Background3; elevation is a
    // 1px hairline (Stroke2), never a shadow.
    light: {
      colorNeutralBackground2: "#ffffff",
      colorNeutralBackground3: "#e7ebf0",
      colorNeutralStroke2: "#c9d1da",
      borderRadiusSmall: "2px",
      borderRadiusMedium: "2px",
      borderRadiusLarge: "3px",
      shadow4: "none",
    },
    dark: {
      colorNeutralBackground2: "#12161b",
      colorNeutralBackground3: "#080a0d",
      colorNeutralStroke2: "#232a32",
      borderRadiusSmall: "2px",
      borderRadiusMedium: "2px",
      borderRadiusLarge: "3px",
      shadow4: "none",
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
        strokeWidth: 2.25,
        fill: "#0f6cbd",
        fillOpacity: 0.12,
      },
      estimated: {
        stroke: "#b4009e",
        dash: "6 4",
        strokeWidth: 2,
        fill: "#b4009e",
        fillOpacity: 0.03,
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
        strokeWidth: 2.25,
        fill: "#479ef5",
        fillOpacity: 0.14,
      },
      estimated: {
        stroke: "#e47ad6",
        dash: "6 4",
        strokeWidth: 2,
        fill: "#e47ad6",
        fillOpacity: 0.04,
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
        "#0e7490",
        "#0f766e",
        "#6d28d9",
        "#0369a1",
        "#4f46e5",
        "#7e22ce",
        "#155e75",
        "#3b6b3a",
      ],
      invoiced: {
        stroke: "#0e7490",
        dash: null,
        strokeWidth: 2,
        fill: "#0e7490",
        fillOpacity: 0.1,
      },
      estimated: {
        stroke: "#7c3aed",
        dash: "4 3",
        strokeWidth: 1.75,
        fill: "#7c3aed",
        fillOpacity: 0.03,
      },
      grid: "#e1e6ec",
      axis: "#4a5663",
      unknownGap: "#6b7785",
      incompleteMarker: "#9a5b00",
      tooltip: { background: "#ffffff", foreground: "#141a21", border: "#aab4bf" },
    },
    dark: {
      categorical: [
        "#22d3ee",
        "#2dd4bf",
        "#a78bfa",
        "#38bdf8",
        "#818cf8",
        "#c084fc",
        "#67e8f9",
        "#5eead4",
      ],
      invoiced: {
        stroke: "#22d3ee",
        dash: null,
        strokeWidth: 2,
        fill: "#22d3ee",
        fillOpacity: 0.12,
      },
      estimated: {
        stroke: "#a78bfa",
        dash: "4 3",
        strokeWidth: 1.75,
        fill: "#a78bfa",
        fillOpacity: 0.04,
      },
      grid: "#1d242c",
      axis: "#9fabb8",
      unknownGap: "#7f8b98",
      incompleteMarker: "#fbbf24",
      tooltip: { background: "#0e1216", foreground: "#e8edf2", border: "#2f3945" },
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
