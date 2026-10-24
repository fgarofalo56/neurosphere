import { Badge } from "@fluentui/react-components";
import type { ReactElement } from "react";
import { STRINGS, lagText, priceVersionText } from "./strings";
import type {
  AnalyticsState,
  DashboardResponse,
  Freshness,
  MetricValue,
  PriceVersion,
  Series,
  SeriesKind,
} from "./types";

const fmt = new Intl.NumberFormat("en-US", { maximumFractionDigits: 4 });

/** Exactly "unknown" for unknown/null; 0 renders "0" only when the API value is 0. */
export function metricValueText(m: MetricValue): string {
  if (m.status === "unknown" || m.value === null) return STRINGS.unknown;
  return fmt.format(m.value);
}

export function MetricText({
  metric,
  unit,
}: {
  readonly metric: MetricValue;
  readonly unit?: string;
}): ReactElement {
  const known = metric.status === "known" && metric.value !== null;
  return (
    <div style={{ display: "inline-block" }}>
      <span data-testid="metric-value">{metricValueText(metric)}</span>
      {known && unit !== undefined && unit !== "" ? <span> {unit}</span> : null}
      {!metric.complete ? (
        <Badge appearance="outline" color="warning" data-testid="incomplete-marker">
          {STRINGS.incompleteTotal}
        </Badge>
      ) : null}
    </div>
  );
}

/**
 * Fluent's filled success badge puts colorNeutralForegroundOnBrand (black in the
 * high-contrast pack) on colorPaletteGreenBackground3 (#107c10): 3.91:1, fails
 * WCAG 1.4.3 (A11Y-003). The tint appearance uses the palette green foreground 1
 * on green background 1 tokens instead.
 */
export const INVOICED_BADGE_APPEARANCE = "tint" as const;

export function KindBadge({ kind }: { readonly kind: SeriesKind }): ReactElement {
  return (
    <Badge
      appearance={kind === "invoiced" ? INVOICED_BADGE_APPEARANCE : "filled"}
      color={kind === "invoiced" ? "success" : "informative"}
      data-testid="kind-badge"
    >
      {STRINGS[kind]}
    </Badge>
  );
}

export function PriceVersionBadge({
  version,
}: {
  readonly version: PriceVersion | null;
}): ReactElement {
  return (
    <Badge appearance="outline" data-testid="price-version-badge">
      {version === null ? STRINGS.priceVersionUnknown : priceVersionText(version)}
    </Badge>
  );
}

export function LagIndicator({ freshness }: { readonly freshness: Freshness }): ReactElement {
  return (
    <dl data-testid="lag-indicator" aria-label="Data freshness">
      <dt>{STRINGS.watermarkLabel}</dt>
      <dd data-testid="watermark">{freshness.watermark ?? STRINGS.unknown}</dd>
      <dt>{STRINGS.lagLabel}</dt>
      <dd data-testid="lag">
        {freshness.lag_seconds === null ? STRINGS.unknown : lagText(freshness.lag_seconds)}
      </dd>
      {freshness.billing_source_freshness !== null ? (
        <>
          <dt>{STRINGS.billingFreshnessLabel}</dt>
          <dd data-testid="billing-freshness">{freshness.billing_source_freshness}</dd>
        </>
      ) : null}
    </dl>
  );
}

const CHIP_COLOR: Record<AnalyticsState, "success" | "warning" | "danger"> = {
  available: "success",
  delayed: "warning",
  disabled: "danger",
};

export function AnalyticsChip({
  analytics,
}: {
  readonly analytics: DashboardResponse["analytics"];
}): ReactElement {
  const reason =
    analytics.state === "disabled" ? (analytics.reason ?? STRINGS.noReason) : analytics.reason;
  return (
    <div data-testid="analytics-chip">
      <Badge appearance="tint" color={CHIP_COLOR[analytics.state]}>
        {STRINGS.analyticsState[analytics.state]}
      </Badge>
      {reason !== null ? <span data-testid="analytics-reason"> {reason}</span> : null}
    </div>
  );
}

function unitLabel(s: Series): string {
  return s.unit === "currency" ? (s.currency ?? "") : s.unit;
}

/** Simple SVG line chart. Decorative: the data table is the accessible primary representation. */
export function SeriesChart({ series }: { readonly series: Series }): ReactElement {
  const w = 320;
  const h = 80;
  const known = series.points
    .map((p, i) => ({ i, v: p.value.status === "known" ? p.value.value : null }))
    .filter((p): p is { i: number; v: number } => p.v !== null);
  const max = Math.max(1, ...known.map((p) => p.v));
  const n = Math.max(1, series.points.length - 1);
  const pts = known.map((p) => `${(p.i / n) * w},${h - (p.v / max) * h}`).join(" ");
  return (
    <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} aria-hidden="true" focusable="false">
      <polyline points={pts} fill="none" stroke="currentColor" strokeWidth="2" />
    </svg>
  );
}

export function SeriesBlock({
  series,
  showPrice,
}: {
  readonly series: Series;
  readonly showPrice: boolean;
}): ReactElement {
  const unit = unitLabel(series);
  const headingId = `series-${series.key}`;
  return (
    <section role="group" aria-labelledby={headingId} data-testid="series-block">
      <h3 id={headingId}>{series.label}</h3>
      <div>
        Total: <MetricText metric={series.total} unit={unit} />{" "}
        {series.kind !== null ? <KindBadge kind={series.kind} /> : null}{" "}
        {showPrice ? <PriceVersionBadge version={series.total.price_version} /> : null}
      </div>
      <SeriesChart series={series} />
      <div
        role="region"
        aria-label={`${series.label} data table`}
        tabIndex={0}
        style={{ maxHeight: 320, overflow: "auto" }}
      >
        <table>
          <caption>{series.label}</caption>
          <thead>
            <tr>
              <th scope="col">Time</th>
              <th scope="col">Value</th>
              {series.kind !== null ? <th scope="col">Basis</th> : null}
              {showPrice ? <th scope="col">Price version</th> : null}
            </tr>
          </thead>
          <tbody>
            {series.points.map((p) => (
              <tr key={p.t}>
                <th scope="row">{p.t}</th>
                <td>
                  <MetricText metric={p.value} unit={unit} />
                </td>
                {series.kind !== null ? (
                  <td>
                    <KindBadge kind={series.kind} />
                  </td>
                ) : null}
                {showPrice ? (
                  <td>
                    <PriceVersionBadge version={p.value.price_version} />
                  </td>
                ) : null}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
