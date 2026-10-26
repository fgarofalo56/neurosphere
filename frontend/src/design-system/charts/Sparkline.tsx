import type { ReactElement } from "react";
import { useUiStyle } from "../styles";
import { formatNumber, linePath } from "./internal";
import { linearScale, niceTicks } from "./scale";
import type { ChartBasis, ChartUnit } from "./types";

export interface SparklineProps {
  /** Ordered values; null is unknown (the line breaks, never 0). */
  readonly values: readonly (number | null)[];
  /** Accessible name, e.g. "Cost, last 14 days". A short min/max/unknown summary is appended. */
  readonly label: string;
  readonly kind?: ChartBasis | null;
  /** Unit and currency used to format min/max/latest in the text alternative. */
  readonly unit?: ChartUnit;
  readonly currency?: string | null;
  readonly width?: number;
  readonly height?: number;
}

export function Sparkline({
  values,
  label,
  kind = null,
  unit = "count",
  currency = null,
  width = 96,
  height = 28,
}: SparklineProps): ReactElement {
  const { chart } = useUiStyle();
  const style =
    kind === "estimated"
      ? chart.estimated
      : kind === "invoiced"
        ? chart.invoiced
        : { ...chart.invoiced, stroke: chart.categorical[0] ?? chart.invoiced.stroke };
  const known = values.filter((v): v is number => v !== null && Number.isFinite(v));
  const unknown = values.length - known.length;
  const ticks = known.length > 0 ? niceTicks(Math.min(...known), Math.max(...known), 3) : [0, 1];
  const pad = 3;
  const x = linearScale(0, Math.max(1, values.length - 1), pad, width - pad);
  const y = linearScale(ticks[0] ?? 0, ticks[ticks.length - 1] ?? 1, height - pad, pad);
  const xy = values.map((v, i) =>
    v === null || !Number.isFinite(v) ? null : ([x(i), y(v)] as const),
  );
  const fmt = (v: number): string => formatNumber(v, unit, currency);
  const summary =
    known.length === 0
      ? `${label}: no known values, ${unknown} unknown`
      : `${label}: min ${fmt(Math.min(...known))}, max ${fmt(Math.max(...known))}, latest ${fmt(known[known.length - 1] as number)}, ${unknown} unknown`;
  return (
    <svg
      role="img"
      aria-label={summary}
      viewBox={`0 0 ${width} ${height}`}
      width={width}
      height={height}
    >
      <path
        d={linePath(xy)}
        data-testid="sparkline-path"
        fill="none"
        stroke={style.stroke}
        strokeWidth={Math.min(style.strokeWidth, 2)}
        strokeDasharray={style.dash ?? undefined}
        strokeLinejoin="round"
        strokeLinecap="round"
      />
      {values.map((v, i) =>
        v === null || !Number.isFinite(v) ? (
          <line
            key={i}
            data-testid="sparkline-gap"
            x1={x(i)}
            x2={x(i)}
            y1={pad}
            y2={height - pad}
            stroke={chart.unknownGap}
            strokeDasharray="2 2"
          />
        ) : null,
      )}
    </svg>
  );
}
