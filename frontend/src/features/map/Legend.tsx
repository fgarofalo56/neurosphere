import { Select, makeStyles, tokens } from "@fluentui/react-components";
import type { ReactElement } from "react";
import { HealthIndicator, NODE_TYPES, NodeTypeIcon, useUiStyle } from "../../design-system";
import { UNKNOWN_OPACITY, type MetricRange } from "./appearance";
import { useCardClasses } from "./card";
import { EDGE_TOKEN } from "./mapTheme";
import { HEALTH_LABEL, KIND_LABEL, PROVENANCE_LABEL, SIZE_METRIC_LABEL, STRINGS } from "./strings";
import { HEALTHS, PROVENANCES, SIZE_METRICS, type Provenance, type SizeMetric } from "./types";

const useStyles = makeStyles({
  group: { margin: 0, padding: 0, border: "none", minWidth: 0 },
  legendTitle: {
    padding: 0,
    marginBottom: tokens.spacingVerticalXS,
    color: tokens.colorNeutralForeground2,
    fontSize: tokens.fontSizeBase200,
    fontWeight: tokens.fontWeightSemibold,
  },
  list: { listStyle: "none", margin: 0, padding: 0, display: "grid", rowGap: "4px" },
  item: { display: "flex", alignItems: "center", columnGap: tokens.spacingHorizontalS },
  note: { margin: 0, color: tokens.colorNeutralForeground2, fontSize: tokens.fontSizeBase200 },
});

/** Formats a metric for display; null is "unknown", never 0. */
export function formatMetric(value: number | null): string {
  if (value === null) return STRINGS.unknown;
  return Number.isInteger(value) ? String(value) : value.toFixed(2);
}

const DASH: Readonly<Record<Provenance, string | undefined>> = {
  observed: undefined,
  declared: "8 4",
  inferred: "2 4",
};

function EdgeSample({ provenance }: { readonly provenance: Provenance }): ReactElement {
  return (
    <svg width="36" height="10" aria-hidden="true" focusable="false">
      <line
        x1="1"
        y1="5"
        x2="35"
        y2="5"
        style={{ stroke: EDGE_TOKEN[provenance] }}
        strokeWidth={provenance === "observed" ? 2.5 : 2}
        strokeDasharray={DASH[provenance]}
        strokeLinecap="round"
      />
    </svg>
  );
}

export interface LegendProps {
  readonly sizeBy: SizeMetric;
  readonly onSizeBy: (metric: SizeMetric) => void;
  readonly range: MetricRange | null;
  readonly unknownCount: number;
}

export function Legend({ sizeBy, onSizeBy, range, unknownCount }: LegendProps): ReactElement {
  const styles = useStyles();
  const card = useCardClasses();
  const { health } = useUiStyle();
  const unknownColour = health.unknown.icon;
  return (
    <section className={card.card} aria-label={STRINGS.legendHeading} data-testid="map-legend">
      <h2 className={card.title}>{STRINGS.legendHeading}</h2>

      <fieldset className={styles.group}>
        <legend className={styles.legendTitle}>{STRINGS.sizeBy}</legend>
        <Select
          aria-label={STRINGS.sizeBy}
          value={sizeBy}
          onChange={(_, data) => onSizeBy(data.value as SizeMetric)}
        >
          {SIZE_METRICS.map((m) => (
            <option key={m} value={m}>
              {SIZE_METRIC_LABEL[m]}
            </option>
          ))}
        </Select>
        <ul className={styles.list} data-testid="size-legend">
          <li>
            Smallest: <span data-testid="size-min">{formatMetric(range?.min ?? null)}</span>
          </li>
          <li>
            Largest: <span data-testid="size-max">{formatMetric(range?.max ?? null)}</span>
          </li>
          <li className={styles.item} data-testid="size-unknown">
            <svg width="14" height="14" aria-hidden="true" focusable="false">
              <circle
                cx="7"
                cy="7"
                r="3"
                fillOpacity={UNKNOWN_OPACITY}
                strokeDasharray="2 2"
                style={{ fill: unknownColour, stroke: unknownColour }}
              />
            </svg>
            <span>
              {STRINGS.unknown}: {STRINGS.unknownLegend} ({unknownCount})
            </span>
          </li>
        </ul>
        <p className={styles.note}>{STRINGS.clusterSizeNote}</p>
      </fieldset>

      <fieldset className={styles.group}>
        <legend className={styles.legendTitle}>{STRINGS.colourBy}</legend>
        <ul className={styles.list} data-testid="health-legend">
          {HEALTHS.map((h) => (
            <li key={h} className={styles.item}>
              <HealthIndicator state={h} label={HEALTH_LABEL[h]} />
            </li>
          ))}
        </ul>
      </fieldset>

      <fieldset className={styles.group}>
        <legend className={styles.legendTitle}>{STRINGS.nodeKinds}</legend>
        <ul className={styles.list} data-testid="kind-legend">
          {NODE_TYPES.map((t) => (
            <li key={t}>
              <NodeTypeIcon type={t} showLabel />
            </li>
          ))}
          <li className={styles.item}>
            <svg width="32" height="32" aria-hidden="true" focusable="false">
              <polygon
                points="16,5 28,27 4,27"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.5"
              />
            </svg>
            <span>{KIND_LABEL.cluster}</span>
          </li>
        </ul>
      </fieldset>

      <fieldset className={styles.group}>
        <legend className={styles.legendTitle}>{STRINGS.edgeStyles}</legend>
        <ul className={styles.list} data-testid="edge-legend">
          {PROVENANCES.map((p) => (
            <li key={p} className={styles.item} data-provenance={p}>
              <EdgeSample provenance={p} />
              <span>{PROVENANCE_LABEL[p]}</span>
            </li>
          ))}
        </ul>
      </fieldset>
    </section>
  );
}
