import { useMemo, useState } from "react";
import type { PointerEvent, ReactElement } from "react";
import { tokens } from "@fluentui/react-components";
import { useUiStyle } from "../styles";
import { ChartLegend } from "./ChartLegend";
import {
  ChartError,
  ChartTooltip,
  areaPath,
  basisWord,
  formatAxisDate,
  formatFullDate,
  formatNumber,
  formatSeriesValue,
  knownValues,
  linePath,
  plotPoints,
  seriesStyle,
  summarize,
  useMotionAllowed,
} from "./internal";
import type { TooltipRow } from "./internal";
import { linearScale, niceTicks, timeTicks } from "./scale";
import type { TimeGrain } from "./scale";
import type { ChartSeries, ChartSize } from "./types";
import { checkSeries } from "./validate";

export interface TimeSeriesChartProps extends ChartSize {
  /** All series must share ONE unit and ONE currency, otherwise an error state renders. */
  readonly series: readonly ChartSeries[];
  readonly grain?: TimeGrain;
  readonly variant?: "line" | "area";
  /** Overrides the generated summary label. */
  readonly ariaLabel?: string;
  /** Render the legend under the plot (default true). */
  readonly legend?: boolean;
}

const MARGIN = { top: 10, right: 14, bottom: 28, left: 64 };

export function TimeSeriesChart({
  series,
  grain = "day",
  variant = "line",
  width = 640,
  height = 240,
  ariaLabel,
  legend = true,
}: TimeSeriesChartProps): ReactElement {
  const { chart } = useUiStyle();
  const motion = useMotionAllowed();
  const [hover, setHover] = useState<number | null>(null);
  const error = checkSeries(series);

  const model = useMemo(() => {
    const plotted = series.map((s) => plotPoints(s.points));
    const times = [...new Set(plotted.flatMap((pts) => pts.map((p) => p.ms)))].sort(
      (a, b) => a - b,
    );
    const values = knownValues(series);
    const lo = values.length > 0 ? Math.min(0, ...values) : 0;
    const hi = values.length > 0 ? Math.max(...values) : 1;
    const yTicks = niceTicks(lo, hi, 5);
    return { plotted, times, yTicks };
  }, [series]);

  if (error) return <ChartError error={error} />;

  const first = series[0];
  const plotW = width - MARGIN.left - MARGIN.right;
  const plotH = height - MARGIN.top - MARGIN.bottom;
  const t0 = model.times[0] ?? 0;
  const t1 = model.times[model.times.length - 1] ?? 1;
  const yMin = model.yTicks[0] ?? 0;
  const yMax = model.yTicks[model.yTicks.length - 1] ?? 1;
  const x = linearScale(t0, t1, MARGIN.left, MARGIN.left + plotW);
  const y = linearScale(yMin, yMax, MARGIN.top + plotH, MARGIN.top);
  const baseline = MARGIN.top + plotH;
  const xTicks = timeTicks(t0, t1, grain, Math.max(2, Math.floor(plotW / 90)));
  const label = ariaLabel ?? summarize(series, grain);

  const onMove = (event: PointerEvent<SVGSVGElement>): void => {
    if (model.times.length === 0) return;
    const rect = event.currentTarget.getBoundingClientRect();
    const raw = event.clientX - rect.left;
    const px = Number.isFinite(raw) ? (rect.width > 0 ? (raw / rect.width) * width : raw) : 0;
    let best = 0;
    let bestDist = Infinity;
    model.times.forEach((ms, i) => {
      const d = Math.abs(x(ms) - px);
      if (d < bestDist) {
        bestDist = d;
        best = i;
      }
    });
    setHover(best);
  };

  const hoverMs = hover === null ? null : (model.times[hover] ?? null);
  const rows: TooltipRow[] =
    hoverMs === null
      ? []
      : series.map((s, i) => {
          const p = model.plotted[i]?.find((q) => q.ms === hoverMs);
          return {
            key: s.key,
            label: s.label,
            basis: basisWord(s),
            value: p && p.value !== null ? formatSeriesValue(s, p.value) : "unknown",
            complete: p ? p.complete : true,
          };
        });

  return (
    <div style={{ position: "relative", width: "100%" }} data-chart="time-series">
      <svg
        role="img"
        aria-label={label}
        viewBox={`0 0 ${width} ${height}`}
        width="100%"
        data-motion={motion ? "on" : "off"}
        style={{ display: "block", maxWidth: "100%" }}
        onPointerMove={onMove}
        onPointerLeave={() => setHover(null)}
      >
        {model.yTicks.map((tick) => (
          <g key={`y${tick}`}>
            <line
              x1={MARGIN.left}
              x2={MARGIN.left + plotW}
              y1={y(tick)}
              y2={y(tick)}
              stroke={chart.grid}
              strokeWidth={1}
            />
            <text
              x={MARGIN.left - 6}
              y={y(tick)}
              textAnchor="end"
              dominantBaseline="middle"
              fontSize={11}
              fill={chart.axis}
            >
              {first ? formatNumber(tick, first.unit, first.currency, true) : String(tick)}
            </text>
          </g>
        ))}
        {xTicks.map((tick) => (
          <text
            key={`x${tick}`}
            x={x(tick)}
            y={height - 8}
            textAnchor="middle"
            fontSize={11}
            fill={chart.axis}
          >
            {formatAxisDate(tick, grain)}
          </text>
        ))}
        {series.map((s, i) => {
          const pts = model.plotted[i] ?? [];
          const style = seriesStyle(s, i, series, chart);
          const xy = pts.map((p) => (p.value === null ? null : ([x(p.ms), y(p.value)] as const)));
          const transition = motion ? "opacity 200ms ease-out" : undefined;
          return (
            <g key={s.key} data-series={s.key} data-basis={basisWord(s)}>
              {variant === "area" && !(s.kind === "estimated" && series.length > 1) && (
                <path
                  d={areaPath(xy, y(Math.max(yMin, Math.min(0, yMax))))}
                  fill={style.fill}
                  fillOpacity={style.fillOpacity}
                  stroke="none"
                />
              )}
              <path
                d={linePath(xy)}
                data-testid={`line-${s.key}`}
                fill="none"
                stroke={style.stroke}
                strokeWidth={style.strokeWidth}
                strokeDasharray={style.dash ?? undefined}
                strokeLinejoin="round"
                strokeLinecap="round"
                style={{ transition }}
              />
              {pts.map((p, j) => {
                if (p.value === null) {
                  return (
                    <line
                      key={`gap${p.ms}`}
                      data-testid="gap-marker"
                      x1={x(p.ms)}
                      x2={x(p.ms)}
                      y1={MARGIN.top}
                      y2={baseline}
                      stroke={chart.unknownGap}
                      strokeWidth={1.5}
                      strokeDasharray="2 3"
                    />
                  );
                }
                const isolated = pts[j - 1]?.value == null && pts[j + 1]?.value == null;
                if (!p.complete) {
                  return (
                    <circle
                      key={`inc${p.ms}`}
                      data-testid="incomplete-marker"
                      cx={x(p.ms)}
                      cy={y(p.value)}
                      r={4}
                      fill="none"
                      stroke={chart.incompleteMarker}
                      strokeWidth={2}
                    />
                  );
                }
                return isolated ? (
                  <circle
                    key={`pt${p.ms}`}
                    cx={x(p.ms)}
                    cy={y(p.value)}
                    r={3}
                    fill={style.stroke}
                  />
                ) : null;
              })}
            </g>
          );
        })}
        {hoverMs !== null && (
          <line
            x1={x(hoverMs)}
            x2={x(hoverMs)}
            y1={MARGIN.top}
            y2={baseline}
            stroke={chart.axis}
            strokeWidth={1}
            data-testid="hover-line"
          />
        )}
      </svg>
      {hoverMs !== null && (
        <ChartTooltip
          chart={chart}
          date={formatFullDate(hoverMs, grain)}
          rows={rows}
          leftPct={(x(hoverMs) / width) * 100}
          motion={motion}
        />
      )}
      {legend && (
        <div style={{ marginTop: tokens.spacingVerticalXS }}>
          <ChartLegend series={series} />
        </div>
      )}
    </div>
  );
}
