/**
 * The map's canvas theme (no sigma): everything WebGL needs as concrete colour strings, derived
 * from the active UI style (`useUiStyle()`) and, where the style has no value, from Fluent
 * tokens resolved to computed colours at render time. No colour literal lives here: the health
 * colours come from the style's health palette, the rest from the chart theme or Fluent tokens.
 */
import { tokens } from "@fluentui/react-components";
import {
  DEFAULT_UI_STYLE_ID,
  getUiStyle,
  resolveUiStyle,
  type HealthPalette,
  type UiStyleId,
  type UiStyleState,
} from "../../design-system";
import type { Provenance } from "./types";

/** Fluent tokens behind each provenance edge: the legend draws with the same values. */
export const EDGE_TOKEN: Readonly<Record<Provenance, string>> = {
  observed: tokens.colorBrandStroke1,
  declared: tokens.colorNeutralForeground2,
  inferred: tokens.colorNeutralForeground3,
};

/** Resolves a CSS value (a `var(--token)` string) to a concrete value; "" when it cannot. */
export type CssResolver = (property: "color" | "fontFamily", value: string) => string;

export interface MapTheme {
  readonly styleId: UiStyleId;
  readonly health: HealthPalette;
  readonly edge: Readonly<Record<Provenance, string>>;
  readonly label: {
    readonly color: string;
    readonly font: string;
    readonly size: number;
    /** Pill behind each label so it stays legible over edges and the grid. */
    readonly background: string;
  };
  /** Ops console: health halos also glow. */
  readonly glow: boolean;
  /** Changes whenever any resolved value changes (renderer rebuild key). */
  readonly key: string;
}

const LABEL_SIZE = 12;
const SANS_FALLBACK = "sans-serif";
const MONO_FALLBACK = "monospace";

/**
 * Builds the theme. `resolve` is null where there is no DOM to compute against (tests, first
 * render): the style palette values are used instead of resolved tokens.
 */
export function buildMapTheme(style: UiStyleState, resolve: CssResolver | null): MapTheme {
  const pick = (property: "color" | "fontFamily", css: string, fallback: string): string => {
    const value = resolve?.(property, css) ?? "";
    return value !== "" ? value : fallback;
  };
  const mono = style.treatment.monoNumerals;
  const edge: Record<Provenance, string> = {
    observed: pick("color", EDGE_TOKEN.observed, style.chart.categorical[0] ?? style.chart.axis),
    declared: pick("color", EDGE_TOKEN.declared, style.chart.axis),
    inferred: pick("color", EDGE_TOKEN.inferred, style.chart.unknownGap),
  };
  const label = {
    color: pick("color", tokens.colorNeutralForeground1, style.chart.tooltip.foreground),
    font: pick(
      "fontFamily",
      mono ? tokens.fontFamilyMonospace : tokens.fontFamilyBase,
      mono ? MONO_FALLBACK : SANS_FALLBACK,
    ),
    size: LABEL_SIZE,
    background: pick("color", tokens.colorNeutralBackground1, style.chart.tooltip.background),
  };
  const glow = style.id === "ops-console";
  const key = [
    style.id,
    glow,
    edge.observed,
    edge.declared,
    edge.inferred,
    label.color,
    label.font,
    label.background,
    ...(["ok", "degraded", "failing", "unknown"] as const).map((h) => style.health[h].icon),
  ].join("|");
  return { styleId: style.id, health: style.health, edge, label, glow, key };
}

/** The built-in default theme (default style, light), for code that runs outside React. */
export const DEFAULT_MAP_THEME: MapTheme = buildMapTheme(
  resolveUiStyle(getUiStyle(DEFAULT_UI_STYLE_ID), "light"),
  null,
);

/**
 * A resolver that asks the browser: a probe element is attached inside `host` (so it inherits
 * the Fluent provider's CSS variables), the value is assigned and the computed value read back.
 */
export function createDomResolver(host: HTMLElement): CssResolver {
  const cache = new Map<string, string>();
  return (property, value) => {
    const cacheKey = `${property}:${value}`;
    const hit = cache.get(cacheKey);
    if (hit !== undefined) return hit;
    const probe = host.ownerDocument.createElement("span");
    probe.style.position = "absolute";
    probe.style.visibility = "hidden";
    probe.style[property] = value;
    host.appendChild(probe);
    const computed = host.ownerDocument.defaultView?.getComputedStyle(probe)[property] ?? "";
    host.removeChild(probe);
    // An unresolved var() or an empty value means "no answer": the caller falls back.
    const result = computed.includes("var(") ? "" : computed;
    cache.set(cacheKey, result);
    return result;
  };
}
