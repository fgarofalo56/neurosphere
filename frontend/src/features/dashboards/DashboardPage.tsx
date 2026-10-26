import { Field, Select, makeStyles, tokens } from "@fluentui/react-components";
import type { ReactElement } from "react";
import { useSearchParams } from "react-router";
import { ForbiddenError } from "../../api/index.js";
import { useSelectedDomain } from "../../app/domain";
import {
  EmptyState,
  ErrorState,
  formatCurrency,
  formatDuration,
  formatNumber,
  KpiCard,
  LoadingState,
  PageTemplate,
  Panel,
  StatusPill,
  TimeSeriesChart,
  useUiStyle,
} from "../../design-system";
import { ForbiddenState } from "../workspaces/ForbiddenState";
import { groupSeries, groupTitle, toChartSeries, type ChartGroup } from "./chartData";
import { AnalyticsChip, LagIndicator, SeriesBlock } from "./components";
import { useDashboard } from "./hooks";
import { STRINGS } from "./strings";
import type { DashboardMetric, Grain, Series } from "./types";

export interface DashboardPageProps {
  readonly title: string;
  readonly metrics: readonly DashboardMetric[];
}

const DAY_OPTIONS = [1, 7, 14, 30, 60, 90] as const;
const HOUR_MAX_DAYS = 14;

const useStyles = makeStyles({
  section: { display: "flex", flexDirection: "column", rowGap: tokens.spacingVerticalM },
  sectionCompact: { rowGap: tokens.spacingVerticalS },
  heading: {
    margin: 0,
    fontSize: tokens.fontSizeBase500,
    lineHeight: tokens.lineHeightBase500,
    fontWeight: tokens.fontWeightSemibold,
    textTransform: "capitalize",
  },
  strip: {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))",
    columnGap: tokens.spacingHorizontalM,
    rowGap: tokens.spacingVerticalM,
  },
  charts: {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 480px), 1fr))",
    columnGap: tokens.spacingHorizontalM,
    rowGap: tokens.spacingVerticalM,
  },
  blocks: {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 420px), 1fr))",
    columnGap: tokens.spacingHorizontalM,
    rowGap: tokens.spacingVerticalM,
    alignItems: "start",
  },
});

/** Display text of a series total in its own unit; unknown is never 0 and nothing is summed. */
export function totalText(s: Series): string {
  const { value, status } = s.total;
  if (status !== "known" || value === null) return STRINGS.unknown;
  switch (s.unit) {
    case "currency":
      return s.currency === null ? formatNumber(value) : formatCurrency(value, s.currency);
    case "ms":
      return formatDuration(value);
    case "ratio":
      return `${formatNumber(value * 100, { maximumFractionDigits: 1 })}%`;
    case "count":
      return formatNumber(value);
  }
}

function ChartPanel({
  group,
  metric,
  grain,
}: {
  readonly group: ChartGroup;
  readonly metric: DashboardMetric;
  readonly grain: Grain;
}): ReactElement {
  const chartSeries = group.series.map(toChartSeries);
  const hasPoints = chartSeries.some((s) => s.points.length > 0);
  return (
    <Panel title={groupTitle(group, metric)} level={3} testId="chart-panel">
      {hasPoints ? (
        <TimeSeriesChart series={chartSeries} grain={grain} variant="line" height={260} />
      ) : (
        <EmptyState title={STRINGS.chartEmpty} />
      )}
    </Panel>
  );
}

function MetricSection({
  metric,
  domainId,
  days,
  grain,
  title,
}: {
  readonly metric: DashboardMetric;
  readonly domainId: string;
  readonly days: number;
  readonly grain: Grain;
  readonly title: string;
}): ReactElement {
  const styles = useStyles();
  const { density } = useUiStyle();
  const query = useDashboard({ metric, domainId, days, grain });

  if (query.isError) {
    const error = query.error;
    if (error instanceof ForbiddenError) {
      return <ForbiddenState workspace={title} correlationId={error.correlationId} />;
    }
    return (
      <div data-testid="error-state">
        <ErrorState
          title={`Could not load ${metric}`}
          message={`${STRINGS.errorBody}${
            error.correlationId !== "" ? ` (reference ${error.correlationId})` : ""
          }`}
          onRetry={() => void query.refetch()}
        />
      </div>
    );
  }
  if (query.isPending) {
    return (
      <div aria-busy="true">
        <LoadingState label={`${STRINGS.loadingLabel} ${metric}`} rows={4} />
      </div>
    );
  }
  const data = query.data;
  const showPrice = metric === "cost";
  const groups = groupSeries(data.series);
  return (
    <section
      className={`${styles.section} ${density === "compact" ? styles.sectionCompact : ""}`}
      aria-label={`${title} ${metric}`}
      data-testid={`section-${metric}`}
    >
      <h2 className={styles.heading}>{metric}</h2>
      <div className={styles.strip} data-slot="dashboard-kpis">
        {data.series.map((s) => (
          <KpiCard
            key={s.key}
            label={s.label}
            value={totalText(s)}
            accent={s.total.status !== "known" ? "unknown" : s.total.complete ? "ok" : "degraded"}
            {...(s.total.status === "known" && !s.total.complete
              ? { delta: { text: STRINGS.incompleteDelta, direction: "flat" as const } }
              : {})}
          />
        ))}
        <LagIndicator freshness={data.freshness} />
        <AnalyticsChip analytics={data.analytics} />
      </div>
      {!data.complete ? (
        <div data-testid="incomplete-data">
          <StatusPill tone="warning" label={STRINGS.incompleteData} />
        </div>
      ) : null}
      {data.truncated ? (
        <div data-testid="truncated">
          <StatusPill tone="warning" label={STRINGS.truncated} />
        </div>
      ) : null}
      {data.series.length === 0 ? (
        <EmptyState title={STRINGS.emptyTitle} description={STRINGS.emptyBody} />
      ) : (
        <>
          <div className={styles.charts}>
            {groups.map((g) => (
              <ChartPanel key={g.key} group={g} metric={metric} grain={grain} />
            ))}
          </div>
          <div className={styles.blocks}>
            {data.series.map((s) => (
              <SeriesBlock key={s.key} series={s} showPrice={showPrice} grain={grain} />
            ))}
          </div>
        </>
      )}
    </section>
  );
}

export function DashboardPage({ title, metrics }: DashboardPageProps): ReactElement {
  const [params, setParams] = useSearchParams();
  const { domainId } = useSelectedDomain();
  const rawDays = Number(params.get("days") ?? 30);
  const grain: Grain = params.get("grain") === "hour" ? "hour" : "day";
  const days = Number.isInteger(rawDays) && rawDays >= 1 && rawDays <= 90 ? rawDays : 30;
  const effectiveDays = grain === "hour" ? Math.min(days, HOUR_MAX_DAYS) : days;

  const update = (key: string, value: string): void => {
    const next = new URLSearchParams(params);
    next.set(key, value);
    if (key === "grain" && value === "hour" && days > HOUR_MAX_DAYS) {
      next.set("days", String(HOUR_MAX_DAYS));
    }
    setParams(next);
  };

  return (
    <PageTemplate
      title={title}
      toolbarLabel="Dashboard filters"
      toolbar={
        <>
          <Field label="Days">
            <Select
              value={String(effectiveDays)}
              onChange={(_e, data) => update("days", data.value)}
            >
              {DAY_OPTIONS.filter((d) => grain === "day" || d <= HOUR_MAX_DAYS).map((d) => (
                <option key={d} value={d}>
                  {d}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Grain">
            <Select value={grain} onChange={(_e, data) => update("grain", data.value)}>
              <option value="day">day</option>
              <option value="hour">hour</option>
            </Select>
          </Field>
        </>
      }
    >
      {domainId === "" ? (
        <div data-testid="domain-required">
          <EmptyState title={STRINGS.domainRequiredTitle} description={STRINGS.domainRequired} />
        </div>
      ) : (
        metrics.map((m) => (
          <MetricSection
            key={m}
            metric={m}
            domainId={domainId}
            days={effectiveDays}
            grain={grain}
            title={title}
          />
        ))
      )}
    </PageTemplate>
  );
}
