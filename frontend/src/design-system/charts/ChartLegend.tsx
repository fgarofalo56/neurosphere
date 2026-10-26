import type { ReactElement } from "react";
import { tokens } from "@fluentui/react-components";
import { useUiStyle } from "../styles";
import { legendLabel, seriesStyle } from "./internal";
import type { ChartSeries } from "./types";

export interface ChartLegendProps {
  readonly series: readonly ChartSeries[];
}

/** Legend that names the basis in words ("estimated"/"invoiced"); line style is never the only cue. */
export function ChartLegend({ series }: ChartLegendProps): ReactElement {
  const { chart } = useUiStyle();
  return (
    <ul
      aria-label="Chart legend"
      style={{
        display: "flex",
        flexWrap: "wrap",
        gap: tokens.spacingHorizontalL,
        listStyle: "none",
        margin: 0,
        padding: 0,
        fontSize: tokens.fontSizeBase200,
        color: tokens.colorNeutralForeground2,
      }}
    >
      {series.map((s, i) => {
        const style = seriesStyle(s, i, series, chart);
        return (
          <li
            key={s.key}
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: tokens.spacingHorizontalXS,
            }}
          >
            <svg width={24} height={10} aria-hidden="true" focusable="false">
              <line
                x1={0}
                y1={5}
                x2={24}
                y2={5}
                stroke={style.stroke}
                strokeWidth={style.strokeWidth}
                strokeDasharray={style.dash ?? undefined}
                data-dash={style.dash ?? "solid"}
              />
            </svg>
            <span>{legendLabel(s)}</span>
          </li>
        );
      })}
    </ul>
  );
}
