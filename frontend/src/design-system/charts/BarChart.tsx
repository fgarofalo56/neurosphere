import { useMemo, useState } from "react";
import type { PointerEvent, ReactElement } from "react";
import { tokens } from "@fluentui/react-components";
import { useUiStyle } from "../styles";
import { ChartLegend } from "./ChartLegend";
import {
  ChartError,
  ChartTooltip,
  basisWord,
  formatAxisDate,
  formatFullDate,
  formatNumber,
  formatSeriesValue,
  knownValues,
  plotPoints,
  seriesStyle,
  summarize,
  useContainerWidth,
  useMotionAllowed,
} from "./internal";
import type { TooltipRow } from "./internal";
import { linearScale, niceTicks } from "./scale";
import type { TimeGrain } from "./scale";
import type { ChartSeries, ChartSize } from "./types";
import { checkSeries } from "./validate";

export interface BarChartProps extends ChartSize {
  /** Grouped bars per time bucket. All series must share ONE unit and ONE currency. */
  readonly series: readonly ChartSeries[];
  readonly grain?: TimeGrain;
  readonly ariaLabel?: string;
  readonly legend?: boolean;
}

const MARGIN = { top: 10, right: 14, bottom: 28, left: 64 };

export function BarChart({
  series,
  grain = "day",
  width: widthProp = 640,
  height = 240,
  ariaLabel,
  legend = true,
}: BarChartProps): ReactElement {
  const { chart } = useUiStyle();
  const motion = useMotionAllowed();
  const { ref, width } = useContainerWidth(widthProp);
  const [hover, setHover] = useState<number | null>(null);
  const error = checkSeries(series);

  const model = useMemo(() => {
    const plotted = series.map((s) => plotPoints(s.points));
    const times = [...new Set(plotted.flatMap((pts) => pts.map((p) => p.ms)))].sort(
      (a, b) => a - b,
    );
    const values = knownValues(series);
    const lo = values.length > 0 ? Math.min(0, ...values) : 0;
    const hi = values.length > 0 ? Math.max(0, ...values) : 1;
    return { plotted, times, yTicks: niceTicks(lo, hi, 5) };
  }, [series]);

  if (error) return <ChartError error={error} />;

  const first = series[0];
  const plotW = width - MARGIN.left - MARGIN.right;
  const plotH = height - MARGIN.top - MARGIN.bottom;
  const yMin = model.yTicks[0] ?? 0;
  const yMax = model.yTicks[model.yTicks.length - 1] ?? 1;
  const y = linearScale(yMin, yMax, MARGIN.top + plotH, MARGIN.top);
  const zero = y(Math.max(yMin, Math.min(0, yMax)));
  const slot = model.times.length > 0 ? plotW / model.times.length : plotW;
  const barW = Math.max(1, (slot * 0.7) / Math.max(1, series.length));
  const slotX = (i: number): number => MARGIN.left + slot * i;
  const labelEvery = Math.max(
    1,
    Math.ceil(model.times.length / Math.max(2, Math.floor(plotW / 90))),
  );
  const label = ariaLabel ?? summarize(series, grain);

  const onMove = (event: PointerEvent<SVGSVGElement>): void => {
    if (model.times.length === 0) return;
    const rect = event.currentTarget.getBoundingClientRect();
    const raw = event.clientX - rect.left;
    const px = Number.isFinite(raw) ? (rect.width > 0 ? (raw / rect.width) * width : raw) : 0;
    const idx = Math.floor((px - MARGIN.left) / slot);
    setHover(Math.max(0, Math.min(model.times.length - 1, idx)));
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
    <div ref={ref} style={{ position: "relative", width: "100%", minWidth: 0 }} data-chart="bar">
      <svg
        role="img"
        aria-label={label}
        viewBox={`0 0 ${width} ${height}`}
        width={width}
        height={height}
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
        {model.times.map((ms, i) =>
          i % labelEvery === 0 ? (
            <text
              key={`x${ms}`}
              x={slotX(i) + slot / 2}
              y={height - 8}
              textAnchor="middle"
              fontSize={11}
              fill={chart.axis}
            >
              {formatAxisDate(ms, grain)}
            </text>
          ) : null,
        )}
        {series.map((s, si) => {
          const style = seriesStyle(s, si, series, chart);
          return (
            <g key={s.key} data-series={s.key} data-basis={basisWord(s)}>
              {model.times.map((ms, i) => {
                const p = model.plotted[si]?.find((q) => q.ms === ms);
                const bx = slotX(i) + slot * 0.15 + si * barW;
                if (!p || p.value === null) {
                  return (
                    <line
                      key={`gap${ms}`}
                      data-testid="gap-marker"
                      x1={bx + barW / 2}
                      x2={bx + barW / 2}
                      y1={MARGIN.top}
                      y2={MARGIN.top + plotH}
                      stroke={chart.unknownGap}
                      strokeWidth={1.5}
                      strokeDasharray="2 3"
                    />
                  );
                }
                const top = y(p.value);
                return (
                  <g key={`bar${ms}`}>
                    <rect
                      data-testid={`bar-${s.key}`}
                      x={bx}
                      y={Math.min(top, zero)}
                      width={barW}
                      height={Math.abs(zero - top)}
                      fill={style.fill}
                      fillOpacity={Math.max(style.fillOpacity, 0.35)}
                      stroke={style.stroke}
                      strokeWidth={Math.min(style.strokeWidth, 2)}
                      strokeDasharray={style.dash ?? undefined}
                      style={{ transition: motion ? "opacity 200ms ease-out" : undefined }}
                    />
                    {!p.complete && (
                      <circle
                        data-testid="incomplete-marker"
                        cx={bx + barW / 2}
                        cy={top}
                        r={4}
                        fill="none"
                        stroke={chart.incompleteMarker}
                        strokeWidth={2}
                      />
                    )}
                  </g>
                );
              })}
            </g>
          );
        })}
      </svg>
      {hoverMs !== null && hover !== null && (
        <ChartTooltip
          chart={chart}
          date={formatFullDate(hoverMs, grain)}
          rows={rows}
          leftPct={((slotX(hover) + slot / 2) / width) * 100}
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
