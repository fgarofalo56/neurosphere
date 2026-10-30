import { Field, Select, makeStyles, tokens } from "@fluentui/react-components";
import type { ReactElement } from "react";
import { useSearchParams } from "react-router";
import { ForbiddenError } from "../../api/index.js";
import { useSelectedDomain } from "../../app/domain";
import {
  DataTable,
  EmptyState,
  ErrorState,
  KpiCard,
  LoadingState,
  PageTemplate,
  Panel,
  StatusPill,
  TimeSeriesChart,
  Timestamp,
  checkSeries,
  formatCurrency,
  type ChartSeries,
  type DataTableColumn,
} from "../../design-system";
import { ForbiddenState } from "../workspaces";
import {
  pickOption,
  toNumber,
  useForecast,
  type Amount,
  type CostSeries,
  type ForecastResponse,
  type ForecastValue,
  type SeriesPoint,
} from "./data";
import {
  CURRENCY_OPTIONS,
  DEFAULT_CURRENCY,
  DEFAULT_HISTORY,
  DEFAULT_HORIZON,
  HISTORY_OPTIONS,
  HORIZON_OPTIONS,
  STRINGS,
} from "./strings";

const useStyles = makeStyles({
  stack: { display: "flex", flexDirection: "column", rowGap: tokens.spacingVerticalL },
  strip: {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))",
    gap: tokens.spacingHorizontalM,
  },
  row: { display: "flex", flexWrap: "wrap", gap: tokens.spacingHorizontalS, alignItems: "center" },
  muted: { color: tokens.colorNeutralForeground2, fontSize: tokens.fontSizeBase200, margin: 0 },
  dl: {
    display: "grid",
    gridTemplateColumns: "max-content 1fr",
    columnGap: tokens.spacingHorizontalL,
    rowGap: tokens.spacingVerticalXS,
    margin: 0,
  },
  dd: { margin: 0 },
});

/** Money text: unknown is the word "unknown", never 0; a partial figure carries a visible flag. */
export function amountText(amount: Amount, currency: string): string {
  const n = amount.status === "known" ? toNumber(amount.value) : null;
  if (n === null) return STRINGS.unknown;
  const text = formatCurrency(n, currency);
  return amount.complete ? text : `${text} (${STRINGS.incomplete})`;
}

function valueText(value: string | undefined, currency: string): string {
  const n = toNumber(value);
  return n === null ? STRINGS.unknown : formatCurrency(n, currency);
}

function forecastTotalText(f: ForecastValue | null | undefined, currency: string): string {
  if (f === null || f === undefined) return STRINGS.unknown;
  return valueText(f.value, currency);
}

function dayStamp(day: string): string {
  return `${day}T00:00:00Z`;
}

/** Chart series for one basis. Bounds are two extra series; they are NOT a fill. */
export function chartSeries(series: CostSeries): ChartSeries[] {
  const base = { unit: "currency" as const, currency: series.currency };
  const word = series.kind === "estimated" ? STRINGS.estimated : STRINGS.invoiced;
  const out: ChartSeries[] = [
    {
      ...base,
      key: `${series.kind}-actual`,
      label: `${word} actual`,
      kind: series.kind,
      points: series.points.map((p) => ({
        t: dayStamp(p.day),
        // Unknown stays null so the line breaks; it is never plotted as 0.
        value: p.actual.status === "known" ? toNumber(p.actual.value) : null,
        complete: p.actual.complete,
      })),
    },
  ];
  if (series.forecast_available) {
    // Bounds reuse the estimated style (dashed) on the estimated chart; on the invoiced chart the
    // basis is carried by the label, since a series of kind "estimated" would mislabel it.
    const kind = series.kind === "estimated" ? ("estimated" as const) : null;
    const horizon = series.points.filter((p) => p.forecast !== null && p.forecast !== undefined);
    const pick = (key: "value" | "lower" | "upper") =>
      horizon.map((p) => ({ t: dayStamp(p.day), value: toNumber(p.forecast?.[key]) }));
    out.push(
      {
        ...base,
        key: `${series.kind}-forecast`,
        label: `${word} forecast`,
        kind,
        points: pick("value"),
      },
      {
        ...base,
        key: `${series.kind}-lower`,
        label: `${word} forecast lower bound (dashed)`,
        kind,
        points: pick("lower"),
      },
      {
        ...base,
        key: `${series.kind}-upper`,
        label: `${word} forecast upper bound (dashed)`,
        kind,
        points: pick("upper"),
      },
    );
  }
  return out;
}

function SeriesChart({ series }: { readonly series: CostSeries }): ReactElement {
  const drawn = chartSeries(series);
  const mixed = checkSeries(drawn);
  // The chart itself renders an error for mixed series; this page names it in its own words.
  if (mixed !== null) {
    return (
      <div data-testid={`chart-mixed-${series.kind}`}>
        <ErrorState title="Chart cannot be drawn" message={mixed.message} />
      </div>
    );
  }
  const word = series.kind === "estimated" ? STRINGS.estimated : STRINGS.invoiced;
  return (
    <div data-testid={`chart-${series.kind}`}>
      <TimeSeriesChart
        series={drawn}
        grain="day"
        ariaLabel={`${word} cost in ${series.currency}, history and forecast with dashed lower and upper bound lines`}
      />
    </div>
  );
}

const TABLE_COLUMNS = (currency: string): DataTableColumn<SeriesPoint>[] => [
  {
    key: "day",
    header: STRINGS.columns.day,
    render: (p) => <Timestamp value={dayStamp(p.day)} grain="day" />,
  },
  { key: "phase", header: STRINGS.columns.phase, render: (p) => p.phase },
  {
    key: "actual",
    header: STRINGS.columns.actual,
    render: (p) => amountText(p.actual, currency),
  },
  {
    key: "forecast",
    header: STRINGS.columns.forecast,
    render: (p) => (p.forecast ? valueText(p.forecast.value, currency) : STRINGS.none),
  },
  {
    key: "lower",
    header: STRINGS.columns.lower,
    render: (p) => (p.forecast ? valueText(p.forecast.lower, currency) : STRINGS.none),
  },
  {
    key: "upper",
    header: STRINGS.columns.upper,
    render: (p) => (p.forecast ? valueText(p.forecast.upper, currency) : STRINGS.none),
  },
  {
    key: "band",
    header: STRINGS.columns.inBand,
    render: (p) =>
      p.within_band === null || p.within_band === undefined
        ? STRINGS.none
        : p.within_band
          ? STRINGS.yes
          : STRINGS.no,
  },
];

function SeriesPanel({ series }: { readonly series: CostSeries }): ReactElement {
  const styles = useStyles();
  const word = series.kind === "estimated" ? STRINGS.estimated : STRINGS.invoiced;
  const { summary, currency } = series;
  const anyIncomplete =
    !summary.history_actual.complete ||
    !summary.horizon_actual.complete ||
    series.excluded_incomplete_days > 0;
  return (
    <Panel
      title={`${word} cost (${currency})`}
      landmark="region"
      testId={`series-${series.kind}`}
      note={
        anyIncomplete ? (
          <span data-testid={`incomplete-${series.kind}`}>
            <StatusPill tone="warning" label={STRINGS.incomplete} />
          </span>
        ) : undefined
      }
    >
      <div className={styles.stack}>
        <div className={styles.strip}>
          <KpiCard
            label={`${word} ${STRINGS.historyTotal.toLowerCase()}`}
            value={amountText(summary.history_actual, currency)}
            accent={summary.history_actual.status === "known" ? "ok" : "unknown"}
          />
          <KpiCard
            label={`${word} ${STRINGS.horizonActual.toLowerCase()}`}
            value={amountText(summary.horizon_actual, currency)}
            accent={summary.horizon_actual.status === "known" ? "ok" : "unknown"}
          />
          <KpiCard
            label={`${word} ${STRINGS.horizonForecast.toLowerCase()}`}
            value={forecastTotalText(summary.horizon_forecast, currency)}
            accent={series.forecast_available ? "ok" : "unknown"}
          />
        </div>
        {series.forecast_available ? (
          <>
            <SeriesChart series={series} />
            {summary.horizon_forecast ? (
              <p className={styles.muted} data-testid={`band-${series.kind}`}>
                {`Band for the horizon: ${valueText(summary.horizon_forecast.lower, currency)} (lower) to ${valueText(summary.horizon_forecast.upper, currency)} (upper). ${STRINGS.bandNote}`}
              </p>
            ) : null}
          </>
        ) : (
          <div data-testid={`forecast-unavailable-${series.kind}`}>
            <StatusPill
              tone="warning"
              label={`${STRINGS.unavailablePrefix}: ${series.forecast_unavailable_reason ?? STRINGS.unknown}`}
            />
            <SeriesChart series={series} />
          </div>
        )}
        <details data-testid={`table-${series.kind}`} open>
          <summary>{`${STRINGS.tableTitle}: ${word}`}</summary>
          <DataTable
            label={`${word} cost table`}
            columns={TABLE_COLUMNS(currency)}
            rows={series.points}
            getRowId={(p) => `${p.phase}-${p.day}`}
          />
        </details>
      </div>
    </Panel>
  );
}

function confidenceText(level: string): string {
  const n = Number(level);
  return Number.isFinite(n) ? `${Math.round(n * 100)}%` : level;
}

function MethodCard({ data }: { readonly data: ForecastResponse }): ReactElement {
  const styles = useStyles();
  const { method } = data;
  return (
    <Panel title={STRINGS.methodTitle} landmark="region" testId="method-card">
      <dl className={styles.dl}>
        <dt>{STRINGS.method}</dt>
        <dd className={styles.dd} data-testid="method-name">
          {method.name}
        </dd>
        <dt>{STRINGS.confidence}</dt>
        <dd className={styles.dd} data-testid="method-confidence">
          {confidenceText(method.confidence_level)}
        </dd>
        <dt>{STRINGS.fitPoints}</dt>
        <dd className={styles.dd}>
          {`${STRINGS.estimated} ${data.estimated.fit_points}, ${STRINGS.invoiced} ${data.invoiced.fit_points}`}
        </dd>
        <dt>{STRINGS.excludedDays}</dt>
        <dd className={styles.dd} data-testid="method-excluded">
          {`${STRINGS.estimated} ${data.estimated.excluded_incomplete_days}, ${STRINGS.invoiced} ${data.invoiced.excluded_incomplete_days}`}
        </dd>
        <dt>{STRINGS.asOf}</dt>
        <dd className={styles.dd}>
          <Timestamp value={dayStamp(data.as_of)} grain="day" />
        </dd>
        <dt>{STRINGS.priceVersions}</dt>
        <dd className={styles.dd}>
          <span className={styles.row} data-testid="price-versions">
            {data.price_version_ids.map((id) => (
              <StatusPill
                key={id}
                tone={id === data.price_version_id ? "info" : "neutral"}
                label={id}
              />
            ))}
          </span>
        </dd>
      </dl>
      <p className={styles.muted}>{method.description}</p>
      {method.savings_claim === false ? (
        <p className={styles.muted} data-testid="no-claim">
          {STRINGS.noClaim}
        </p>
      ) : null}
    </Panel>
  );
}

function ForecastBody({
  domainId,
  historyDays,
  horizonDays,
  currency,
}: {
  readonly domainId: string;
  readonly historyDays: number;
  readonly horizonDays: number;
  readonly currency: string;
}): ReactElement {
  const styles = useStyles();
  const query = useForecast({ domainId, historyDays, horizonDays, currency });
  if (query.isError) {
    const error = query.error;
    if (error instanceof ForbiddenError) {
      return <ForbiddenState workspace={STRINGS.workspace} correlationId={error.correlationId} />;
    }
    return (
      <div data-testid="error-state">
        <ErrorState
          title={STRINGS.failedTitle}
          message={`${STRINGS.failedBody}${error.correlationId !== "" ? ` (reference ${error.correlationId})` : ""}`}
          onRetry={() => void query.refetch()}
        />
      </div>
    );
  }
  if (query.isPending) {
    return (
      <div aria-busy="true">
        <LoadingState label={STRINGS.loading} rows={4} />
      </div>
    );
  }
  const data = query.data;
  return (
    <div className={styles.stack} data-testid="forecast-body">
      <p className={styles.muted}>{STRINGS.neverSummed}</p>
      <SeriesPanel series={data.estimated} />
      <SeriesPanel series={data.invoiced} />
      <MethodCard data={data} />
    </div>
  );
}

export function ForecastPage(): ReactElement {
  const { domainId } = useSelectedDomain();
  const [params, setParams] = useSearchParams();
  const historyDays = pickOption(params.get("history_days"), HISTORY_OPTIONS, DEFAULT_HISTORY);
  const horizonDays = pickOption(params.get("horizon_days"), HORIZON_OPTIONS, DEFAULT_HORIZON);
  const rawCurrency = params.get("currency") ?? DEFAULT_CURRENCY;
  const currency = CURRENCY_OPTIONS.find((c) => c === rawCurrency) ?? DEFAULT_CURRENCY;

  const update = (key: string, value: string): void => {
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        next.set(key, value);
        return next;
      },
      { replace: true },
    );
  };

  return (
    <PageTemplate
      title={STRINGS.pageTitle}
      description={STRINGS.pageDescription}
      toolbarLabel={STRINGS.toolbarLabel}
      toolbar={
        <>
          <Field label={STRINGS.history}>
            <Select
              value={String(historyDays)}
              onChange={(_e, d) => update("history_days", d.value)}
            >
              {HISTORY_OPTIONS.map((o) => (
                <option key={o} value={o}>
                  {o}
                </option>
              ))}
            </Select>
          </Field>
          <Field label={STRINGS.horizon}>
            <Select
              value={String(horizonDays)}
              onChange={(_e, d) => update("horizon_days", d.value)}
            >
              {HORIZON_OPTIONS.map((o) => (
                <option key={o} value={o}>
                  {o}
                </option>
              ))}
            </Select>
          </Field>
          <Field label={STRINGS.currency}>
            <Select value={currency} onChange={(_e, d) => update("currency", d.value)}>
              {CURRENCY_OPTIONS.map((o) => (
                <option key={o} value={o}>
                  {o}
                </option>
              ))}
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
        <ForecastBody
          domainId={domainId}
          historyDays={historyDays}
          horizonDays={horizonDays}
          currency={currency}
        />
      )}
    </PageTemplate>
  );
}
