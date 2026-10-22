import { Select, makeStyles, tokens } from "@fluentui/react-components";
import type { ReactElement } from "react";
import { NODE_TYPES, NodeTypeIcon } from "../../design-system";
import { EDGE_COLOUR, HEALTH_COLOUR, UNKNOWN_OPACITY, type MetricRange } from "./appearance";
import { HEALTH_LABEL, KIND_LABEL, PROVENANCE_LABEL, SIZE_METRIC_LABEL, STRINGS } from "./strings";
import { HEALTHS, PROVENANCES, SIZE_METRICS, type Provenance, type SizeMetric } from "./types";

const useStyles = makeStyles({
  root: {
    display: "flex",
    flexDirection: "column",
    rowGap: tokens.spacingVerticalM,
    padding: tokens.spacingHorizontalM,
    border: `1px solid ${tokens.colorNeutralStroke2}`,
    borderRadius: tokens.borderRadiusMedium,
    backgroundColor: tokens.colorNeutralBackground2,
    maxWidth: "320px",
  },
  group: { margin: 0, padding: 0, border: "none" },
  list: { listStyle: "none", margin: 0, padding: 0, display: "grid", rowGap: "4px" },
  item: { display: "flex", alignItems: "center", columnGap: tokens.spacingHorizontalS },
  swatch: { width: "14px", height: "14px", flex: "none", boxSizing: "border-box" },
  heading: { margin: 0, fontSize: tokens.fontSizeBase300 },
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
        stroke={EDGE_COLOUR[provenance]}
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
  return (
    <section className={styles.root} aria-label={STRINGS.legendHeading} data-testid="map-legend">
      <h2 className={styles.heading}>{STRINGS.legendHeading}</h2>

      <fieldset className={styles.group}>
        <legend>{STRINGS.sizeBy}</legend>
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
                fill={HEALTH_COLOUR.unknown}
                fillOpacity={UNKNOWN_OPACITY}
                stroke={HEALTH_COLOUR.unknown}
                strokeDasharray="2 2"
              />
            </svg>
            <span>
              {STRINGS.unknown}: {STRINGS.unknownLegend} ({unknownCount})
            </span>
          </li>
        </ul>
        <p>{STRINGS.clusterSizeNote}</p>
      </fieldset>

      <fieldset className={styles.group}>
        <legend>{STRINGS.colourBy}</legend>
        <ul className={styles.list} data-testid="health-legend">
          {HEALTHS.map((h) => (
            <li key={h} className={styles.item}>
              <span
                className={styles.swatch}
                style={{
                  backgroundColor: HEALTH_COLOUR[h],
                  opacity: h === "unknown" ? UNKNOWN_OPACITY : 1,
                }}
                aria-hidden="true"
              />
              <span>{HEALTH_LABEL[h]}</span>
            </li>
          ))}
        </ul>
      </fieldset>

      <fieldset className={styles.group}>
        <legend>{STRINGS.nodeKinds}</legend>
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
        <legend>{STRINGS.edgeStyles}</legend>
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
