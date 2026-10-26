import { Badge, makeStyles, mergeClasses, tokens } from "@fluentui/react-components";
import type { ReactElement } from "react";
import {
  DataTable,
  EmptyState,
  formatAbsoluteTime,
  HealthIndicator,
  Panel,
  StatusPill,
  Timestamp,
  type DataTableColumn,
  type HealthState,
  useUiStyle,
} from "../../design-system";
import { STRINGS, lagText, priceVersionText } from "./strings";
import type {
  AnalyticsState,
  DashboardResponse,
  Freshness,
  Grain,
  MetricValue,
  PriceVersion,
  Series,
  SeriesKind,
  SeriesPoint,
} from "./types";

const fmt = new Intl.NumberFormat("en-US", { maximumFractionDigits: 4 });

/** Exactly "unknown" for unknown/null; 0 renders "0" only when the API value is 0. */
export function metricValueText(m: MetricValue): string {
  if (m.status === "unknown" || m.value === null) return STRINGS.unknown;
  return fmt.format(m.value);
}

const useMetricStyles = makeStyles({
  metric: {
    display: "inline-flex",
    flexWrap: "wrap",
    alignItems: "center",
    columnGap: tokens.spacingHorizontalS,
    rowGap: tokens.spacingVerticalXXS,
  },
});

export function MetricText({
  metric,
  unit,
  format,
}: {
  readonly metric: MetricValue;
  readonly unit?: string;
  /** Formats a known value (e.g. as currency). The unit suffix is then omitted. */
  readonly format?: (value: number) => string;
}): ReactElement {
  const styles = useMetricStyles();
  const known = metric.status === "known" && metric.value !== null;
  const text =
    format !== undefined && known && metric.value !== null
      ? format(metric.value)
      : metricValueText(metric);
  return (
    <span className={styles.metric}>
      <span data-testid="metric-value">{text}</span>
      {format === undefined && known && unit !== undefined && unit !== "" ? (
        <span> {unit}</span>
      ) : null}
      {!metric.complete ? (
        <span data-testid="incomplete-marker">
          <StatusPill tone="warning" label={STRINGS.incompleteTotal} />
        </span>
      ) : null}
    </span>
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

/** Price-version text is long (over 24 characters), so it is a wrapping StatusPill, not a Badge. */
export function PriceVersionBadge({
  version,
}: {
  readonly version: PriceVersion | null;
}): ReactElement {
  return (
    <span data-testid="price-version-badge">
      <StatusPill
        tone="neutral"
        label={version === null ? STRINGS.priceVersionUnknown : priceVersionText(version)}
      />
    </span>
  );
}

/** A date-like string renders as a `Timestamp`; anything else is shown as text, never dropped. */
export function FreshTime({ value }: { readonly value: string }): ReactElement {
  return Number.isNaN(new Date(value).getTime()) ? (
    <span>{value}</span>
  ) : (
    <Timestamp value={value} />
  );
}

const useCardStyles = makeStyles({
  card: {
    display: "flex",
    flexDirection: "column",
    rowGap: tokens.spacingVerticalXS,
    minWidth: 0,
    boxSizing: "border-box",
    padding: tokens.spacingHorizontalM,
    backgroundColor: tokens.colorNeutralBackground1,
    color: tokens.colorNeutralForeground1,
    border: `${tokens.strokeWidthThin} solid ${tokens.colorNeutralStroke2}`,
    borderRadius: tokens.borderRadiusMedium,
  },
  raised: { boxShadow: tokens.shadow4 },
  lifted: { backgroundColor: tokens.colorNeutralBackground2 },
  list: { display: "flex", flexDirection: "column", rowGap: tokens.spacingVerticalXXS, margin: 0 },
  pair: { display: "flex", flexWrap: "wrap", columnGap: tokens.spacingHorizontalS },
  term: { color: tokens.colorNeutralForeground2, fontSize: tokens.fontSizeBase200 },
  def: { margin: 0, fontSize: tokens.fontSizeBase300 },
  cardTitle: { fontSize: tokens.fontSizeBase200, color: tokens.colorNeutralForeground2 },
});

function useCardClass(): string {
  const styles = useCardStyles();
  const { treatment } = useUiStyle();
  return mergeClasses(
    styles.card,
    treatment.surface === "raised" && styles.raised,
    treatment.panelSurface === "lifted" && styles.lifted,
  );
}

export function LagIndicator({ freshness }: { readonly freshness: Freshness }): ReactElement {
  const styles = useCardStyles();
  const card = useCardClass();
  return (
    <div className={card}>
      <span className={styles.cardTitle}>{STRINGS.freshnessTitle}</span>
      <dl className={styles.list} data-testid="lag-indicator" aria-label="Data freshness">
        <div className={styles.pair}>
          <dt className={styles.term}>{STRINGS.watermarkLabel}</dt>
          <dd className={styles.def} data-testid="watermark">
            {freshness.watermark === null ? (
              STRINGS.unknown
            ) : (
              <FreshTime value={freshness.watermark} />
            )}
          </dd>
        </div>
        <div className={styles.pair}>
          <dt className={styles.term}>{STRINGS.lagLabel}</dt>
          <dd className={styles.def} data-testid="lag">
            {freshness.lag_seconds === null ? STRINGS.unknown : lagText(freshness.lag_seconds)}
          </dd>
        </div>
        {freshness.billing_source_freshness !== null ? (
          <div className={styles.pair}>
            <dt className={styles.term}>{STRINGS.billingFreshnessLabel}</dt>
            <dd className={styles.def} data-testid="billing-freshness">
              <FreshTime value={freshness.billing_source_freshness} />
            </dd>
          </div>
        ) : null}
      </dl>
    </div>
  );
}

const ANALYTICS_HEALTH: Record<AnalyticsState, HealthState> = {
  available: "ok",
  delayed: "degraded",
  disabled: "failing",
};

export function AnalyticsChip({
  analytics,
}: {
  readonly analytics: DashboardResponse["analytics"];
}): ReactElement {
  const styles = useCardStyles();
  const card = useCardClass();
  const reason =
    analytics.state === "disabled" ? (analytics.reason ?? STRINGS.noReason) : analytics.reason;
  return (
    <div className={card} data-testid="analytics-chip">
      <span className={styles.cardTitle}>{STRINGS.analyticsTitle}</span>
      <div>
        <HealthIndicator
          state={ANALYTICS_HEALTH[analytics.state]}
          label={STRINGS.analyticsState[analytics.state]}
        />
      </div>
      {reason !== null ? <span data-testid="analytics-reason"> {reason}</span> : null}
    </div>
  );
}

export function unitLabel(s: Series): string {
  return s.unit === "currency" ? (s.currency ?? "") : s.unit;
}

/** Dense table time cell: a UTC calendar day for day grain, an absolute UTC instant for hour grain. */
function PointTime({ t, grain }: { readonly t: string; readonly grain: Grain }): ReactElement {
  if (grain === "day") return <Timestamp value={t} grain="day" />;
  const date = new Date(t);
  if (Number.isNaN(date.getTime())) return <span>{STRINGS.unknown}</span>;
  return <time dateTime={date.toISOString()}>{formatAbsoluteTime(date)}</time>;
}

const useBlockStyles = makeStyles({
  total: {
    display: "flex",
    flexWrap: "wrap",
    alignItems: "center",
    columnGap: tokens.spacingHorizontalS,
    rowGap: tokens.spacingVerticalXXS,
  },
  scroll: { maxHeight: "320px", overflow: "auto" },
});

/** One series: total, kind and price version, and the accessible data table of every point. */
export function SeriesBlock({
  series,
  showPrice,
  grain = "day",
}: {
  readonly series: Series;
  readonly showPrice: boolean;
  readonly grain?: Grain;
}): ReactElement {
  const styles = useBlockStyles();
  const unit = unitLabel(series);
  const columns: DataTableColumn<SeriesPoint>[] = [
    {
      key: "time",
      header: STRINGS.tableColumns.time,
      minWidth: "140px",
      render: (p) => <PointTime t={p.t} grain={grain} />,
    },
    {
      key: "value",
      header: STRINGS.tableColumns.value,
      minWidth: "150px",
      render: (p) => <MetricText metric={p.value} unit={unit} />,
    },
    ...(series.kind !== null
      ? [
          {
            key: "basis",
            header: STRINGS.tableColumns.basis,
            render: () => (series.kind === null ? null : <KindBadge kind={series.kind} />),
          },
        ]
      : []),
    ...(showPrice
      ? [
          {
            key: "price",
            header: STRINGS.tableColumns.price,
            minWidth: "260px",
            render: (p: SeriesPoint) => <PriceVersionBadge version={p.value.price_version} />,
          },
        ]
      : []),
  ];
  return (
    <Panel title={series.label} level={3} landmark="group" testId="series-block">
      <div className={styles.total}>
        <span>{STRINGS.totalLabel}:</span>
        <MetricText metric={series.total} unit={unit} />
        {series.kind !== null ? <KindBadge kind={series.kind} /> : null}
        {showPrice ? <PriceVersionBadge version={series.total.price_version} /> : null}
      </div>
      <div
        role="region"
        aria-label={`${series.label} data table`}
        tabIndex={0}
        className={styles.scroll}
      >
        {series.points.length === 0 ? (
          <EmptyState title={STRINGS.emptyTitle} description={STRINGS.emptyBody} />
        ) : (
          <DataTable
            label={series.label}
            columns={columns}
            rows={series.points}
            getRowId={(p) => p.t}
          />
        )}
      </div>
    </Panel>
  );
}
