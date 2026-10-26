import type { Theme } from "@fluentui/react-components";
import type {
  ChartPalette,
  ChartSeriesStyle,
  HealthColours,
  HealthPaletteTokens,
  StyleColourMode,
} from "../tokens";

/**
 * A UI style is presentation DATA only (NS-10): density, component treatment, chart theme,
 * health palette and allowlisted neutral token overrides. It never carries roles, permissions,
 * routes or API behaviour; no-api-import.test.ts enforces that.
 */

export type UiStyleId = "ops-console" | "enterprise-fluent";

export type UiDensity = "compact" | "comfortable";

/** Colours are token values (hex lives in design-system/tokens/). */
export type ChartTheme = ChartPalette;
export type ChartSeriesTheme = ChartSeriesStyle;
export type HealthColour = HealthColours;
export type HealthPalette = HealthPaletteTokens;
export type HealthState = keyof HealthPaletteTokens;

/** Non-colour component treatment hints read by the item 2 primitives. */
export interface ComponentTreatment {
  /** "flat" cards rely on a stroke; "raised" cards use the style shadow. */
  surface: "flat" | "raised";
  /** Card and table border emphasis. */
  border: "subtle" | "strong";
  /** Zebra striping in dense tables. */
  tableStripes: boolean;
  /**
   * Uppercase applies ONLY to short labels: KPI captions, table column headers and card section
   * titles. Never to sentences, status pills or health indicators.
   */
  uppercaseLabels: boolean;
  /** Corner radius step used by custom cards. */
  radius: "small" | "medium";
  /** "lifted" cards sit on colorNeutralBackground2 over a darker canvas; "base" uses Background1. */
  panelSurface: "base" | "lifted";
  /** "edge" draws a slim status-coloured strip on the leading edge of each KPI card. */
  kpiAccent: "edge" | "none";
  /** "tabular" sets tabular numerals on KPI values and numeric table cells. */
  numerals: "tabular" | "proportional";
  /** Use the monospace font token for KPI values. */
  monoNumerals: boolean;
  /** Most KPI cards laid out on one row before the grid wraps into even rows. */
  kpiMaxAcross: number;
  /** Show a "live" freshness indicator in the app header area. */
  liveIndicator: boolean;
}

export type StyleOverrides = Readonly<Partial<Record<StyleColourMode, Partial<Theme>>>>;

export interface UiStyle {
  id: UiStyleId;
  displayName: string;
  /** Mode applied when neither the user nor the deployment chose one. */
  preferredMode: StyleColourMode;
  density: UiDensity;
  treatment: ComponentTreatment;
  /** Allowlisted neutral surface, stroke, shadow and radius overrides per colour mode. */
  overrides?: StyleOverrides;
  chart: Readonly<Record<StyleColourMode, ChartTheme>>;
  health: Readonly<Record<StyleColourMode, HealthPalette>>;
}

/** What `useUiStyle()` returns for the active style and mode. */
export interface UiStyleState {
  id: UiStyleId;
  density: UiDensity;
  chart: ChartTheme;
  health: HealthPalette;
  treatment: ComponentTreatment;
}
