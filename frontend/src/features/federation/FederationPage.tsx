import { Field, Select, makeStyles, tokens } from "@fluentui/react-components";
import type { ReactElement } from "react";
import { useEffect, useState } from "react";
import { useSearchParams } from "react-router";
import { ForbiddenError } from "../../api/index.js";
import {
  DataTable,
  EmptyState,
  ErrorState,
  LoadingState,
  PageTemplate,
  Panel,
  StatusPill,
  Timestamp,
  formatCurrency,
  formatNumber,
  type DataTableColumn,
} from "../../design-system";
import { ForbiddenState } from "../workspaces";
import {
  groupByCurrency,
  useFederation,
  type CellOutcome,
  type CostTotal,
  type DomainSummary,
  type MergedSummary,
} from "./data";
import { DAY_OPTIONS, DEFAULT_DAYS, STRINGS } from "./strings";

const useStyles = makeStyles({
  stack: { display: "flex", flexDirection: "column", rowGap: tokens.spacingVerticalL },
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

/** Money text: null is the word "unknown", never 0; a partial figure carries a visible flag. */
export function totalText(total: CostTotal): string {
  const n = total.amount === null ? null : Number(total.amount);
  if (n === null || !Number.isFinite(n)) return STRINGS.unknown;
  const text = formatCurrency(n, total.currency);
  return total.complete ? text : `${text} (${STRINGS.incomplete})`;
}

function countText(n: number | null | undefined): string {
  return n === null || n === undefined ? STRINGS.unknown : formatNumber(n);
}

function CompletenessPill({ complete }: { readonly complete: boolean }): ReactElement {
  return (
    <StatusPill
      tone={complete ? "success" : "warning"}
      label={complete ? STRINGS.complete : STRINGS.incomplete}
    />
  );
}

const CELL_NOTE: Record<CellOutcome["state"], string> = {
  ok: STRINGS.cellOkNote,
  denied: STRINGS.cellDeniedNote,
  unavailable: STRINGS.cellUnavailableNote,
};

const CELL_COLUMNS: DataTableColumn<CellOutcome>[] = [
  { key: "cell", header: STRINGS.columns.cell, render: (c) => c.cell_id },
  {
    key: "state",
    header: STRINGS.columns.state,
    render: (c) => <StatusPill tone={c.state === "ok" ? "success" : "warning"} label={c.state} />,
  },
  { key: "note", header: STRINGS.columns.note, render: (c) => CELL_NOTE[c.state] },
];

const DOMAIN_COLUMNS: DataTableColumn<DomainSummary>[] = [
  { key: "domain", header: STRINGS.columns.domain, render: (d) => d.domain_id },
  { key: "req", header: STRINGS.columns.requests, render: (d) => countText(d.request_count) },
  { key: "err", header: STRINGS.columns.errors, render: (d) => countText(d.error_count) },
  {
    key: "unk",
    header: STRINGS.columns.unknownOutcomes,
    render: (d) => countText(d.unknown_outcome_count),
  },
  {
    key: "costs",
    header: STRINGS.columns.costs,
    render: (d) =>
      d.costs.length === 0
        ? STRINGS.unknown
        : d.costs.map((c) => `${c.kind} ${c.currency} ${totalText(c)}`).join("; "),
  },
  {
    key: "status",
    header: STRINGS.columns.status,
    render: (d) => <CompletenessPill complete={d.complete} />,
  },
];

const TOTAL_COLUMNS: DataTableColumn<CostTotal>[] = [
  { key: "basis", header: STRINGS.columns.basis, render: (t) => t.kind },
  { key: "amount", header: STRINGS.columns.amount, render: (t) => totalText(t) },
  {
    key: "status",
    header: STRINGS.columns.status,
    render: (t) => <CompletenessPill complete={t.complete} />,
  },
];

function Summary({ data }: { readonly data: MergedSummary }): ReactElement {
  const styles = useStyles();
  const groups = groupByCurrency(data.totals);
  return (
    <div className={styles.stack} data-testid="federation-body">
      <div className={styles.row}>
        <span data-testid="badge-complete">
          <CompletenessPill complete={data.complete} />
        </span>
        <span data-testid="badge-truncated">
          <StatusPill
            tone={data.truncated ? "warning" : "neutral"}
            label={data.truncated ? STRINGS.truncated : STRINGS.notTruncated}
          />
        </span>
      </div>
      {!data.complete ? (
        <p className={styles.muted} data-testid="incomplete-notice">
          {STRINGS.incompleteNotice}
        </p>
      ) : null}
      {data.truncated ? (
        <p className={styles.muted} data-testid="truncated-notice">
          {STRINGS.truncatedNotice}
        </p>
      ) : null}
      <p className={styles.muted}>{STRINGS.boundaryNotice}</p>
      <dl className={styles.dl}>
        <dt>{STRINGS.cloud}</dt>
        <dd className={styles.dd}>{data.cloud}</dd>
        <dt>{STRINGS.boundary}</dt>
        <dd className={styles.dd}>{data.boundary_id}</dd>
        <dt>{STRINGS.window}</dt>
        <dd className={styles.dd}>
          <Timestamp value={data.window_start} grain="day" /> to{" "}
          <Timestamp value={data.window_end} grain="day" />
        </dd>
      </dl>
      <Panel title={STRINGS.cellsTitle} landmark="region" testId="cells-panel">
        {data.cells.length === 0 ? (
          <EmptyState title={STRINGS.noCells} />
        ) : (
          <DataTable
            label={STRINGS.cellsTitle}
            columns={CELL_COLUMNS}
            rows={data.cells}
            getRowId={(c) => c.cell_id}
            getRowProps={(c) => ({ "data-testid": `cell-${c.cell_id}`, "data-state": c.state })}
          />
        )}
      </Panel>
      <Panel title={STRINGS.totalsTitle} landmark="region" testId="totals-panel">
        {groups.length === 0 ? (
          <EmptyState title={STRINGS.noTotals} />
        ) : (
          <div className={styles.stack}>
            {groups.map(([currency, totals]) => (
              <div key={currency} data-testid={`totals-${currency}`}>
                <h3>{currency}</h3>
                <DataTable
                  label={`Totals in ${currency}`}
                  columns={TOTAL_COLUMNS}
                  rows={totals}
                  getRowId={(t) => `${t.currency}-${t.kind}`}
                />
              </div>
            ))}
          </div>
        )}
      </Panel>
      <Panel title={STRINGS.domainsTitle} landmark="region" testId="domains-panel">
        {data.domains.length === 0 ? (
          <EmptyState title={STRINGS.noDomains} />
        ) : (
          <DataTable
            label={STRINGS.domainsTitle}
            columns={DOMAIN_COLUMNS}
            rows={data.domains}
            getRowId={(d) => d.domain_id}
          />
        )}
      </Panel>
    </div>
  );
}

function FederationBody({
  days,
  cell,
  onCells,
}: {
  readonly days: number;
  readonly cell: string;
  readonly onCells: (ids: readonly string[]) => void;
}): ReactElement {
  const query = useFederation({ days, cell });
  const data = query.data;
  useEffect(() => {
    if (data !== undefined) onCells(data.cells.map((c) => c.cell_id));
  }, [data, onCells]);
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
  if (data === undefined) {
    return (
      <div aria-busy="true">
        <LoadingState label={STRINGS.loading} rows={4} />
      </div>
    );
  }
  return <Summary data={data} />;
}

export function FederationPage(): ReactElement {
  const [params, setParams] = useSearchParams();
  const rawDays = Number(params.get("days"));
  const days = DAY_OPTIONS.find((d) => d === rawDays) ?? DEFAULT_DAYS;
  const cell = params.get("cell") ?? "";
  const [known, setKnown] = useState<readonly string[]>([]);

  // Remember every cell id seen so the filter keeps its options after a single cell is chosen.
  const onCells = (ids: readonly string[]): void => {
    setKnown((prev) => {
      const merged = [...new Set([...prev, ...ids])];
      return merged.length === prev.length ? prev : merged;
    });
  };

  const update = (key: string, value: string): void => {
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        if (value === "") next.delete(key);
        else next.set(key, value);
        return next;
      },
      { replace: true },
    );
  };

  const options = cell !== "" && !known.includes(cell) ? [...known, cell] : known;

  return (
    <PageTemplate
      title={STRINGS.pageTitle}
      description={STRINGS.pageDescription}
      toolbarLabel={STRINGS.toolbarLabel}
      toolbar={
        <>
          <Field label={STRINGS.days}>
            <Select value={String(days)} onChange={(_e, d) => update("days", d.value)}>
              {DAY_OPTIONS.map((o) => (
                <option key={o} value={o}>
                  {o}
                </option>
              ))}
            </Select>
          </Field>
          <Field label={STRINGS.cell}>
            <Select value={cell} onChange={(_e, d) => update("cell", d.value)}>
              <option value="">{STRINGS.allCells}</option>
              {options.map((id) => (
                <option key={id} value={id}>
                  {id}
                </option>
              ))}
            </Select>
          </Field>
        </>
      }
    >
      <FederationBody days={days} cell={cell} onCells={onCells} />
    </PageTemplate>
  );
}
