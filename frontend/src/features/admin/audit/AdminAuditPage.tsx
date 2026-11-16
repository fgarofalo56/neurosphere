import {
  Button,
  Field,
  Input,
  Select,
  Tab,
  TabList,
  makeStyles,
  tokens,
} from "@fluentui/react-components";
import { useState, type ReactElement } from "react";
import { ForbiddenError, type ApiError } from "../../../api/index.js";
import {
  DataTable,
  EmptyState,
  LoadingState,
  PageTemplate,
  Panel,
  StatusPill,
  Timestamp,
} from "../../../design-system";
import { auditPaths } from "../shared/adminPaths";
import { AdminTabs } from "../shared/AdminTabs";
import { CursorPager, QueryErrorState, changeErrorText } from "../shared/AdminStates";
import { asList } from "../shared/systemHooks";
import { adminDownload, useAdminTransport } from "../shared/transport";
import {
  EXPORT_ROW_CAP,
  filterQuery,
  rangeProblem,
  useAuditDenials,
  useAuditSearch,
  useSiemStatus,
  type AuditFilters,
  type AuditHitView,
  type AuditRecordView,
} from "./hooks";
import { AUDIT_STRINGS as S } from "./strings";

const useStyles = makeStyles({
  form: {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
    columnGap: tokens.spacingHorizontalM,
    rowGap: tokens.spacingVerticalS,
  },
  row: { display: "flex", columnGap: tokens.spacingHorizontalS, flexWrap: "wrap" },
});

const KINDS = ["before", "after", "denied"] as const;
const OUTCOMES = ["succeeded", "failed", "rolled_back"] as const;

function pad(n: number): string {
  return String(n).padStart(2, "0");
}

/** `datetime-local` text for a Date, in local time. */
function toLocalInput(date: Date): string {
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

interface FormState {
  readonly sinceLocal: string;
  readonly untilLocal: string;
  readonly domain: string;
  readonly operation: string;
  readonly kind: string;
  readonly outcome: string;
  readonly actor: string;
  readonly correlationId: string;
}

function defaultForm(now: Date = new Date()): FormState {
  return {
    sinceLocal: toLocalInput(new Date(now.getTime() - 24 * 3_600_000)),
    untilLocal: toLocalInput(now),
    domain: "",
    operation: "",
    kind: "",
    outcome: "",
    actor: "",
    correlationId: "",
  };
}

function toFilters(form: FormState): AuditFilters {
  return {
    since: new Date(form.sinceLocal).toISOString(),
    until: new Date(form.untilLocal).toISOString(),
    domain: form.domain,
    operation: form.operation,
    kind: form.kind,
    outcome: form.outcome,
    actor: form.actor,
    correlationId: form.correlationId,
  };
}

function resultOf(record: AuditRecordView): string {
  if (record.denial !== null) return `${record.denial.code}: ${record.denial.reason}`;
  if (record.outcome !== null) return record.outcome.result;
  return S.noOutcome;
}

function RecordsTable({
  rows,
  label,
}: {
  readonly rows: readonly { readonly domain: string | null; readonly record: AuditRecordView }[];
  readonly label: string;
}): ReactElement {
  return (
    <DataTable
      label={label}
      rows={rows}
      getRowId={(row) => row.record.audit_id}
      getRowProps={() => ({ "data-testid": "audit-row" })}
      columns={[
        {
          key: "time",
          header: S.headers.time,
          render: (row) => <Timestamp value={row.record.recorded_at} />,
        },
        { key: "domain", header: S.headers.domain, render: (row) => row.domain ?? "-" },
        { key: "operation", header: S.headers.operation, render: (row) => row.record.operation },
        {
          key: "kind",
          header: S.headers.kind,
          render: (row) => (
            <StatusPill
              label={row.record.kind}
              tone={row.record.kind === "denied" ? "danger" : "neutral"}
            />
          ),
        },
        { key: "result", header: S.headers.result, render: (row) => resultOf(row.record) },
        {
          key: "actor",
          header: S.headers.actor,
          render: (row) => <code>{row.record.actor.principal_pseudonym}</code>,
        },
        {
          key: "corr",
          header: S.headers.correlation,
          render: (row) => <code>{row.record.correlation_id}</code>,
        },
      ]}
    />
  );
}

function hitRows(items: readonly AuditHitView[]) {
  return items.map((hit) => ({ domain: hit.domain_id, record: hit.record }));
}

function Loading(): ReactElement {
  return (
    <div aria-busy="true" data-testid="loading-state">
      <LoadingState label={S.loading} rows={5} />
    </div>
  );
}

function SearchResults({ filters }: { readonly filters: AuditFilters }): ReactElement {
  const [cursors, setCursors] = useState<readonly string[]>([""]);
  const cursor = cursors[cursors.length - 1] ?? "";
  const query = useAuditSearch({ filters, cursor });
  if (query.isError) {
    return <QueryErrorState error={query.error} onRetry={() => void query.refetch()} />;
  }
  if (query.isPending) return <Loading />;
  const items = asList(query.data.items);
  return (
    <>
      {items.length === 0 ? (
        <div data-testid="empty-state">
          <EmptyState title={S.empty} />
        </div>
      ) : (
        <RecordsTable rows={hitRows(items)} label={S.tabs.search} />
      )}
      <CursorPager
        canGoFirst={cursors.length > 1}
        next={query.data.next_cursor}
        onFirst={() => setCursors([""])}
        onNext={(c) => setCursors([...cursors, c])}
      />
    </>
  );
}

function DenialsResults(): ReactElement {
  const [cursors, setCursors] = useState<readonly string[]>([""]);
  const cursor = cursors[cursors.length - 1] ?? "";
  const query = useAuditDenials({ cursor });
  if (query.isError) {
    return <QueryErrorState error={query.error} onRetry={() => void query.refetch()} />;
  }
  if (query.isPending) return <Loading />;
  const items = asList(query.data.items);
  return (
    <>
      {items.length === 0 ? (
        <div data-testid="empty-state">
          <EmptyState title={S.emptyDenials} />
        </div>
      ) : (
        <RecordsTable
          rows={items.map((record) => ({ domain: null, record }))}
          label={S.tabs.denials}
        />
      )}
      <CursorPager
        canGoFirst={cursors.length > 1}
        next={query.data.next_cursor}
        onFirst={() => setCursors([""])}
        onNext={(c) => setCursors([...cursors, c])}
      />
    </>
  );
}

function SiemPanel(): ReactElement {
  const query = useSiemStatus({});
  let body: ReactElement;
  if (query.isError) {
    body = <QueryErrorState error={query.error} onRetry={() => void query.refetch()} />;
  } else if (query.isPending) {
    body = (
      <div aria-busy="true" data-testid="siem-loading">
        <LoadingState label={S.siem.loading} rows={2} />
      </div>
    );
  } else {
    const s = query.data;
    const tone = s.state === "ok" ? "success" : s.state === "failed" ? "danger" : "neutral";
    body = (
      <dl data-testid="siem-status">
        <dt>{S.siem.sink}</dt>
        <dd>{s.sink}</dd>
        <dt>{S.siem.state}</dt>
        <dd>
          <StatusPill label={S.siem.state_[s.state]} tone={tone} />
        </dd>
        <dt>{S.siem.lastSuccess}</dt>
        <dd>
          {s.last_success_at === null || s.last_success_at === undefined ? (
            S.siem.never
          ) : (
            <Timestamp value={s.last_success_at} />
          )}
        </dd>
        <dt>{S.siem.failures}</dt>
        <dd data-testid="siem-failures">{s.consecutive_failures ?? "unknown"}</dd>
        <dt>{S.siem.lastReason}</dt>
        <dd>{s.last_failure_reason ?? s.reason ?? S.siem.none}</dd>
      </dl>
    );
  }
  return <Panel title={S.siem.title}>{body}</Panel>;
}

function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

function ExportPanel({ filters }: { readonly filters: AuditFilters }): ReactElement {
  const transport = useAdminTransport();
  const [busy, setBusy] = useState(false);
  const [forbidden, setForbidden] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [truncated, setTruncated] = useState(false);

  const run = async (format: "ndjson" | "csv"): Promise<void> => {
    setBusy(true);
    setMessage(null);
    setProblem(null);
    setTruncated(false);
    try {
      const file = await adminDownload(
        transport,
        { path: auditPaths.export(), query: { ...filterQuery(filters), format } },
        `audit-export.${format}`,
      );
      saveBlob(file.blob, file.filename);
      setMessage(S.export.done(file.rows, file.filename));
      setTruncated(file.truncated);
    } catch (caught) {
      if (caught instanceof ForbiddenError) setForbidden(true);
      else setProblem(changeErrorText(caught as ApiError));
    } finally {
      setBusy(false);
    }
  };

  const disabled = busy || forbidden;
  return (
    <Panel title={S.export.title}>
      <p data-testid="export-cap">{S.export.cap}</p>
      <p data-testid="export-notice">{S.export.notice}</p>
      {forbidden ? (
        <p role="alert" data-testid="export-forbidden">
          {S.export.forbidden}
        </p>
      ) : null}
      <div style={{ display: "flex", columnGap: tokens.spacingHorizontalS }}>
        <Button disabled={disabled} onClick={() => void run("ndjson")}>
          {S.export.ndjson}
        </Button>
        <Button disabled={disabled} onClick={() => void run("csv")}>
          {S.export.csv}
        </Button>
      </div>
      {message === null ? null : (
        <p role="status" data-testid="export-done">
          {message}
        </p>
      )}
      {truncated ? (
        <p data-testid="export-truncated">{S.export.truncated(EXPORT_ROW_CAP)}</p>
      ) : null}
      {problem === null ? null : (
        <p role="alert" data-testid="export-error">
          {problem}
        </p>
      )}
    </Panel>
  );
}

function FilterForm({
  form,
  onChange,
  onApply,
  rangeError,
}: {
  readonly form: FormState;
  readonly onChange: (next: FormState) => void;
  readonly onApply: () => void;
  readonly rangeError: string | undefined;
}): ReactElement {
  const styles = useStyles();
  const set = (patch: Partial<FormState>): void => onChange({ ...form, ...patch });
  return (
    <form
      aria-label={S.filtersLabel}
      onSubmit={(event) => {
        event.preventDefault();
        onApply();
      }}
    >
      <div className={styles.form}>
        <Field
          label={S.fields.since}
          required
          validationState={rangeError === undefined ? "none" : "error"}
          validationMessage={rangeError}
          hint={S.rangeHint}
        >
          <Input
            type="datetime-local"
            value={form.sinceLocal}
            onChange={(_e, d) => set({ sinceLocal: d.value })}
          />
        </Field>
        <Field label={S.fields.until} required>
          <Input
            type="datetime-local"
            value={form.untilLocal}
            onChange={(_e, d) => set({ untilLocal: d.value })}
          />
        </Field>
        <Field label={S.fields.domain}>
          <Input value={form.domain} onChange={(_e, d) => set({ domain: d.value })} />
        </Field>
        <Field label={S.fields.operation}>
          <Input value={form.operation} onChange={(_e, d) => set({ operation: d.value })} />
        </Field>
        <Field label={S.fields.kind}>
          <Select value={form.kind} onChange={(_e, d) => set({ kind: d.value })}>
            <option value="">{S.any}</option>
            {KINDS.map((k) => (
              <option key={k} value={k}>
                {k}
              </option>
            ))}
          </Select>
        </Field>
        <Field label={S.fields.outcome}>
          <Select value={form.outcome} onChange={(_e, d) => set({ outcome: d.value })}>
            <option value="">{S.any}</option>
            {OUTCOMES.map((o) => (
              <option key={o} value={o}>
                {o}
              </option>
            ))}
          </Select>
        </Field>
        <Field label={S.fields.actor}>
          <Input value={form.actor} onChange={(_e, d) => set({ actor: d.value })} />
        </Field>
        <Field label={S.fields.correlationId}>
          <Input value={form.correlationId} onChange={(_e, d) => set({ correlationId: d.value })} />
        </Field>
      </div>
      <div className={styles.row}>
        <Button type="submit" appearance="primary" disabled={rangeError !== undefined}>
          {S.apply}
        </Button>
      </div>
    </form>
  );
}

export function AdminAuditPage(): ReactElement {
  const [form, setForm] = useState<FormState>(() => defaultForm());
  const [applied, setApplied] = useState<AuditFilters>(() => toFilters(defaultForm()));
  const [tab, setTab] = useState<"search" | "denials">("search");
  const rangeError = rangeProblem(form.sinceLocal, form.untilLocal);
  // The export follows the applied filters, so what is downloaded is what the table shows.
  return (
    <PageTemplate title={S.title} description={S.description}>
      <AdminTabs />
      <SiemPanel />
      <Panel title={S.filtersLabel}>
        <FilterForm
          form={form}
          onChange={setForm}
          rangeError={rangeError}
          onApply={() => {
            if (rangeError === undefined) setApplied(toFilters(form));
          }}
        />
      </Panel>
      <TabList
        selectedValue={tab}
        onTabSelect={(_e, data) => setTab(data.value as "search" | "denials")}
      >
        <Tab value="search">{S.tabs.search}</Tab>
        <Tab value="denials">{S.tabs.denials}</Tab>
      </TabList>
      {tab === "search" ? (
        // Re-keyed on the filters so paging starts again on the first page.
        <SearchResults key={JSON.stringify(applied)} filters={applied} />
      ) : (
        <DenialsResults />
      )}
      <ExportPanel filters={applied} />
    </PageTemplate>
  );
}
