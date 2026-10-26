import {
  Badge,
  Field,
  Select,
  Table,
  TableBody,
  TableCell,
  TableHeader,
  TableHeaderCell,
  TableRow,
  makeStyles,
  tokens,
} from "@fluentui/react-components";
import type { ReactElement } from "react";
import { useSearchParams } from "react-router";
import { ForbiddenError } from "../../api/index.js";
import { useSelectedDomain } from "../../app/domain";
import {
  BarChart,
  EmptyState,
  ErrorState,
  KpiCard,
  LoadingState,
  PageTemplate,
  StatusPill,
  useUiStyle,
  type ChartSeries,
} from "../../design-system";
import { FreshTime } from "../dashboards/components";
import { Panel } from "../dashboards/Panel";
import { ForbiddenState } from "../workspaces/ForbiddenState";
import { useReconciliation } from "./hooks";
import { STRINGS, lagText } from "./strings";
import type {
  Freshness,
  MetricValue,
  ReconciliationResponse,
  ReferenceLine,
  SourceLine,
} from "./types";

const DAY_OPTIONS = [1, 7, 14, 30, 60, 90] as const;
const amountFormat = new Intl.NumberFormat("en-US", { maximumFractionDigits: 4 });

const useStyles = makeStyles({
  view: { display: "flex", flexDirection: "column", rowGap: tokens.spacingVerticalM },
  note: {
    margin: 0,
    padding: tokens.spacingHorizontalM,
    backgroundColor: tokens.colorNeutralBackground3,
    border: `${tokens.strokeWidthThin} solid ${tokens.colorNeutralStroke2}`,
    borderRadius: tokens.borderRadiusMedium,
    color: tokens.colorNeutralForeground1,
  },
  muted: { margin: 0, color: tokens.colorNeutralForeground2, fontSize: tokens.fontSizeBase200 },
  fresh: {
    display: "flex",
    flexWrap: "wrap",
    columnGap: tokens.spacingHorizontalXL,
    rowGap: tokens.spacingVerticalXS,
    margin: 0,
  },
  pair: { display: "flex", columnGap: tokens.spacingHorizontalS },
  term: { color: tokens.colorNeutralForeground2 },
  def: { margin: 0 },
  cards: {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 520px), 1fr))",
    columnGap: tokens.spacingHorizontalM,
    rowGap: tokens.spacingVerticalM,
    alignItems: "start",
  },
  pills: { display: "flex", flexWrap: "wrap", gap: tokens.spacingHorizontalS },
});

function isKnown(m: MetricValue): m is MetricValue & { readonly value: number } {
  return m.status === "known" && m.value !== null;
}

/** Exactly "unknown" for unknown or null; never 0 for a missing value. */
export function valueText(m: MetricValue, format: (n: number) => string): string {
  return isKnown(m) ? format(m.value) : STRINGS.unknown;
}

export const amountText = (m: MetricValue, currency: string | null): string =>
  valueText(m, (n) =>
    currency === null ? amountFormat.format(n) : `${amountFormat.format(n)} ${currency}`,
  );

export const coverageText = (m: MetricValue): string =>
  valueText(m, (n) => `${amountFormat.format(n * 100)}%`);

function Value({
  text,
  metric,
  testId,
}: {
  readonly text: string;
  readonly metric: MetricValue;
  readonly testId: string;
}): ReactElement {
  return (
    <>
      <span data-testid={testId}>{text}</span>
      {isKnown(metric) && !metric.complete ? (
        <>
          {" "}
          <Badge appearance="outline" color="warning" data-testid="incomplete-marker">
            {STRINGS.incompleteMarker}
          </Badge>
        </>
      ) : null}
    </>
  );
}

function SourceRow({ line }: { readonly line: SourceLine }): ReactElement {
  return (
    <TableRow data-testid={`source-${line.source}`}>
      <TableCell>{STRINGS.sources[line.source]}</TableCell>
      <TableCell>
        <span data-testid="granularity">{STRINGS.granularity[line.granularity]}</span>
      </TableCell>
      <TableCell>
        <Value text={amountText(line.amount, line.currency)} metric={line.amount} testId="amount" />
      </TableCell>
      <TableCell>
        <Value text={coverageText(line.coverage)} metric={line.coverage} testId="coverage" />
      </TableCell>
      <TableCell>
        <Value
          text={amountText(line.variance, line.currency)}
          metric={line.variance}
          testId="variance"
        />
      </TableCell>
    </TableRow>
  );
}

/** Coverage per source for one currency: unknown coverage is a gap, never a zero-height bar. */
export function coverageSeries(
  sources: readonly SourceLine[],
  windowEnd: string,
): readonly ChartSeries[] {
  return sources.map((line) => ({
    key: line.source,
    label: STRINGS.sources[line.source],
    kind: null,
    unit: "ratio",
    currency: null,
    points: [
      {
        t: windowEnd,
        value: isKnown(line.coverage) ? line.coverage.value : null,
        complete: line.coverage.complete,
      },
    ],
  }));
}

function CoverageChart({
  sources,
  windowEnd,
  currencyName,
}: {
  readonly sources: readonly SourceLine[];
  readonly windowEnd: string;
  readonly currencyName: string;
}): ReactElement {
  const series = coverageSeries(sources, windowEnd);
  const anyKnown = series.some((s) => s.points.some((p) => p.value !== null));
  if (Number.isNaN(Date.parse(windowEnd)) || !anyKnown) {
    return (
      <div data-testid="coverage-empty">
        <EmptyState
          title={STRINGS.coverageUnknownTitle}
          description={STRINGS.coverageUnknownBody}
        />
      </div>
    );
  }
  return (
    <BarChart
      series={series}
      height={200}
      ariaLabel={`${STRINGS.coverageChartLabel} in ${currencyName}`}
    />
  );
}

function CurrencyCard({
  reference,
  sources,
  windowEnd,
}: {
  readonly reference: ReferenceLine;
  readonly sources: readonly SourceLine[];
  readonly windowEnd: string;
}): ReactElement {
  const styles = useStyles();
  const { density } = useUiStyle();
  const currencyName = reference.currency ?? STRINGS.undeterminedCurrency;
  return (
    <div
      role="group"
      aria-label={`Reconciliation in ${currencyName}`}
      data-testid="currency-section"
    >
      <Panel title={currencyName} level={2}>
        <CoverageChart sources={sources} windowEnd={windowEnd} currencyName={currencyName} />
        <Table
          aria-label={`Reconciliation table, ${currencyName}`}
          size={density === "compact" ? "small" : "medium"}
        >
          <TableHeader>
            <TableRow>
              <TableHeaderCell>{STRINGS.columns.source}</TableHeaderCell>
              <TableHeaderCell>{STRINGS.columns.granularity}</TableHeaderCell>
              <TableHeaderCell>{STRINGS.columns.amount}</TableHeaderCell>
              <TableHeaderCell>{STRINGS.columns.coverage}</TableHeaderCell>
              <TableHeaderCell>{STRINGS.columns.variance}</TableHeaderCell>
            </TableRow>
          </TableHeader>
          <TableBody>
            <TableRow data-testid="reference-row">
              <TableCell>{STRINGS.referenceLabel}</TableCell>
              <TableCell>{STRINGS.granularity.request}</TableCell>
              <TableCell>
                <Value
                  text={amountText(reference.amount, reference.currency)}
                  metric={reference.amount}
                  testId="reference-amount"
                />
              </TableCell>
              <TableCell>{STRINGS.notApplicable}</TableCell>
              <TableCell>{STRINGS.notApplicable}</TableCell>
            </TableRow>
            {sources.map((line) => (
              <SourceRow key={line.source} line={line} />
            ))}
          </TableBody>
        </Table>
        <p className={styles.muted} data-testid="unknown-entries">
          {STRINGS.unknownRemainderLabel}: {reference.unknown_entry_count}
        </p>
      </Panel>
    </div>
  );
}

function FreshnessList({ freshness }: { readonly freshness: Freshness }): ReactElement {
  const styles = useStyles();
  return (
    <Panel title={STRINGS.freshnessTitle} level={2}>
      <dl className={styles.fresh} data-testid="freshness" aria-label="Data freshness">
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
        <div className={styles.pair}>
          <dt className={styles.term}>{STRINGS.billingFreshnessLabel}</dt>
          <dd className={styles.def} data-testid="billing-freshness">
            {freshness.billing_source_freshness === null ? (
              STRINGS.unknown
            ) : (
              <FreshTime value={freshness.billing_source_freshness} />
            )}
          </dd>
        </div>
      </dl>
    </Panel>
  );
}

export function ReconciliationView({
  data,
}: {
  readonly data: ReconciliationResponse;
}): ReactElement {
  const styles = useStyles();
  return (
    <div className={styles.view} data-testid="reconciliation-view">
      <p className={styles.note} role="note" data-testid="disclaimer">
        {STRINGS.disclaimer}
      </p>
      <FreshnessList freshness={data.freshness} />
      <div className={styles.pills}>
        {!data.complete ? (
          <span data-testid="incomplete-data">
            <StatusPill tone="warning" label={STRINGS.incompleteData} />
          </span>
        ) : null}
        {data.truncated ? (
          <span data-testid="truncated">
            <StatusPill tone="warning" label={STRINGS.truncated} />
          </span>
        ) : null}
      </div>
      {data.references.length === 0 ? (
        <div data-testid="no-data">
          <EmptyState title={STRINGS.noData} />
        </div>
      ) : null}
      <div className={styles.cards}>
        {data.references.map((reference) => (
          <CurrencyCard
            key={reference.currency ?? "undetermined"}
            reference={reference}
            sources={data.sources.filter((s) => s.currency === reference.currency)}
            windowEnd={data.window.end}
          />
        ))}
      </div>
      <p className={styles.muted} data-testid="unknown-remainder">
        {STRINGS.unknownRemainderLabel}: {valueText(data.unknown_remainder, (n) => String(n))}.{" "}
        {STRINGS.unknownRemainderNote}
      </p>
    </div>
  );
}

function referenceKpis(data: ReconciliationResponse): ReactElement[] {
  const cards = data.references.map((r) => (
    <KpiCard
      key={r.currency ?? "undetermined"}
      label={`${STRINGS.kpiReference}, ${r.currency ?? STRINGS.undeterminedCurrency}`}
      value={amountText(r.amount, r.currency)}
      accent={!isKnown(r.amount) ? "unknown" : r.amount.complete ? "ok" : "degraded"}
    />
  ));
  cards.push(
    <KpiCard
      key="unknown-remainder"
      label={STRINGS.unknownRemainderLabel}
      value={valueText(data.unknown_remainder, (n) => String(n))}
      accent={
        isKnown(data.unknown_remainder) && data.unknown_remainder.value === 0 ? "ok" : "degraded"
      }
    />,
  );
  return cards;
}

export function ReconciliationPage(): ReactElement {
  const [params, setParams] = useSearchParams();
  const { domainId } = useSelectedDomain();
  const rawDays = Number(params.get("days") ?? 30);
  const days = Number.isInteger(rawDays) && rawDays >= 1 && rawDays <= 90 ? rawDays : 30;
  const query = useReconciliation({ domainId, days }, domainId !== "");

  const update = (key: string, value: string): void => {
    const next = new URLSearchParams(params);
    next.set(key, value);
    setParams(next);
  };

  let body: ReactElement;
  if (domainId === "") {
    body = (
      <div data-testid="domain-required">
        <EmptyState title={STRINGS.domainRequiredTitle} description={STRINGS.domainRequired} />
      </div>
    );
  } else if (query.isError) {
    const error = query.error;
    body =
      error instanceof ForbiddenError ? (
        <ForbiddenState workspace={STRINGS.title} correlationId={error.correlationId} />
      ) : (
        <div data-testid="error-state">
          <ErrorState
            title={STRINGS.errorTitle}
            message={`${STRINGS.errorBody}${
              error.correlationId !== "" ? ` (reference ${error.correlationId})` : ""
            }`}
            onRetry={() => void query.refetch()}
          />
        </div>
      );
  } else if (query.isPending) {
    body = (
      <div aria-busy="true">
        <LoadingState label={STRINGS.loading} rows={4} />
      </div>
    );
  } else {
    body = <ReconciliationView data={query.data} />;
  }

  return (
    <PageTemplate
      title={STRINGS.title}
      toolbarLabel={STRINGS.filtersLabel}
      {...(query.data !== undefined && !query.isError ? { kpis: referenceKpis(query.data) } : {})}
      toolbar={
        <Field label={STRINGS.daysLabel}>
          <Select value={String(days)} onChange={(_e, data) => update("days", data.value)}>
            {DAY_OPTIONS.map((d) => (
              <option key={d} value={d}>
                {d}
              </option>
            ))}
          </Select>
        </Field>
      }
    >
      {body}
    </PageTemplate>
  );
}
