import {
  Badge,
  MessageBar,
  MessageBarBody,
  MessageBarTitle,
  Table,
  TableBody,
  TableCell,
  TableHeader,
  TableHeaderCell,
  TableRow,
} from "@fluentui/react-components";
import { useId, type ReactElement } from "react";
import { useSearchParams } from "react-router";
import { ForbiddenError } from "../../api/index.js";
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

function CurrencyTable({
  reference,
  sources,
}: {
  readonly reference: ReferenceLine;
  readonly sources: readonly SourceLine[];
}): ReactElement {
  const currencyName = reference.currency ?? STRINGS.undeterminedCurrency;
  return (
    <section aria-label={`Reconciliation in ${currencyName}`} data-testid="currency-section">
      <h2>{currencyName}</h2>
      <Table aria-label={`Reconciliation table, ${currencyName}`}>
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
      <p data-testid="unknown-entries">
        {STRINGS.unknownRemainderLabel}: {reference.unknown_entry_count}
      </p>
    </section>
  );
}

function FreshnessList({ freshness }: { readonly freshness: Freshness }): ReactElement {
  return (
    <dl data-testid="freshness" aria-label="Data freshness">
      <dt>{STRINGS.watermarkLabel}</dt>
      <dd data-testid="watermark">{freshness.watermark ?? STRINGS.unknown}</dd>
      <dt>{STRINGS.lagLabel}</dt>
      <dd data-testid="lag">
        {freshness.lag_seconds === null ? STRINGS.unknown : lagText(freshness.lag_seconds)}
      </dd>
      <dt>{STRINGS.billingFreshnessLabel}</dt>
      <dd data-testid="billing-freshness">
        {freshness.billing_source_freshness ?? STRINGS.unknown}
      </dd>
    </dl>
  );
}

export function ReconciliationView({
  data,
}: {
  readonly data: ReconciliationResponse;
}): ReactElement {
  return (
    <div data-testid="reconciliation-view">
      <p role="note" data-testid="disclaimer">
        {STRINGS.disclaimer}
      </p>
      <FreshnessList freshness={data.freshness} />
      {!data.complete ? <p data-testid="incomplete-data">{STRINGS.incompleteData}</p> : null}
      {data.truncated ? <p data-testid="truncated">{STRINGS.truncated}</p> : null}
      {data.references.length === 0 ? <p data-testid="no-data">{STRINGS.noData}</p> : null}
      {data.references.map((reference) => (
        <CurrencyTable
          key={reference.currency ?? "undetermined"}
          reference={reference}
          sources={data.sources.filter((s) => s.currency === reference.currency)}
        />
      ))}
      <p data-testid="unknown-remainder">
        {STRINGS.unknownRemainderLabel}: {valueText(data.unknown_remainder, (n) => String(n))}.{" "}
        {STRINGS.unknownRemainderNote}
      </p>
    </div>
  );
}

export function ReconciliationPage(): ReactElement {
  const [params, setParams] = useSearchParams();
  const domainId = params.get("domain_id") ?? "";
  const rawDays = Number(params.get("days") ?? 30);
  const days = Number.isInteger(rawDays) && rawDays >= 1 && rawDays <= 90 ? rawDays : 30;
  const ids = { domain: useId(), days: useId() };
  const query = useReconciliation({ domainId, days }, domainId !== "");

  const update = (key: string, value: string): void => {
    const next = new URLSearchParams(params);
    next.set(key, value);
    setParams(next);
  };

  let body: ReactElement;
  if (domainId === "") {
    body = <p data-testid="domain-required">{STRINGS.domainRequired}</p>;
  } else if (query.isError) {
    const error = query.error;
    body =
      error instanceof ForbiddenError ? (
        <ForbiddenState workspace={STRINGS.title} correlationId={error.correlationId} />
      ) : (
        <MessageBar intent="error" role="alert" data-testid="error-state">
          <MessageBarBody>
            <MessageBarTitle>{STRINGS.errorTitle}</MessageBarTitle>
            {STRINGS.errorBody}
            {error.correlationId !== "" ? ` (reference ${error.correlationId})` : ""}
          </MessageBarBody>
        </MessageBar>
      );
  } else if (query.isPending) {
    body = <p aria-busy="true">{STRINGS.loading}</p>;
  } else {
    body = <ReconciliationView data={query.data} />;
  }

  return (
    <section aria-label={STRINGS.title}>
      <h1>{STRINGS.title}</h1>
      <form
        aria-label={STRINGS.filtersLabel}
        onSubmit={(e) => {
          e.preventDefault();
          const value = new FormData(e.currentTarget).get("domain_id");
          update("domain_id", typeof value === "string" ? value.trim() : "");
        }}
      >
        <label htmlFor={ids.domain}>{STRINGS.domainLabel}</label>{" "}
        <input id={ids.domain} name="domain_id" defaultValue={domainId} />{" "}
        <button type="submit">{STRINGS.apply}</button>{" "}
        <label htmlFor={ids.days}>{STRINGS.daysLabel}</label>{" "}
        <select id={ids.days} value={days} onChange={(e) => update("days", e.target.value)}>
          {DAY_OPTIONS.map((d) => (
            <option key={d} value={d}>
              {d}
            </option>
          ))}
        </select>
      </form>
      {body}
    </section>
  );
}
