import type { TimeGrain } from "./scale";

export type ChartUnit = "currency" | "ms" | "ratio" | "count";
export type ChartBasis = "estimated" | "invoiced";

export interface ChartPoint {
  /** ISO 8601 timestamp (day-grain points are UTC midnight). */
  readonly t: string;
  /** null means unknown: the line breaks and a gap marker is drawn. Never plotted as 0. */
  readonly value: number | null;
  /** false draws a hollow marker (partial data). Defaults to true. */
  readonly complete?: boolean;
}

export interface ChartSeries {
  readonly key: string;
  readonly label: string;
  /** Estimated draws dashed with a lighter fill; invoiced is solid; null uses the categorical palette. */
  readonly kind: ChartBasis | null;
  readonly unit: ChartUnit;
  /** ISO 4217 code; required when unit is "currency". */
  readonly currency: string | null;
  readonly points: readonly ChartPoint[];
}

export interface ChartSize {
  /** SVG viewBox width in px (the SVG scales to its container). */
  readonly width?: number;
  readonly height?: number;
}

export type { TimeGrain };
