import { Button, makeStyles, tokens } from "@fluentui/react-components";
import type { ReactElement } from "react";
import { Link, useSearchParams } from "react-router";
import { useSelectedDomain } from "../../app/domain";
import {
  DataTable,
  EmptyState,
  ErrorState as StyledErrorState,
  LoadingState,
  PageTemplate,
  StatusPill,
  Timestamp,
  type DataTableColumn,
} from "../../design-system";
import { ForbiddenError, type ApiError } from "../../api/index.js";
import { ForbiddenState } from "../workspaces/ForbiddenState";
import { useTrace, useTraceList } from "./hooks";
import { STRINGS, traceSamplingText } from "./strings";
import { TraceTree } from "./TraceTree";
import type { TraceDetail, TraceSummary } from "./types";

const useStyles = makeStyles({
  section: { display: "flex", flexDirection: "column", rowGap: tokens.spacingVerticalM },
  heading: { margin: 0, fontSize: tokens.fontSizeBase400, fontWeight: tokens.fontWeightSemibold },
  subheading: {
    margin: 0,
    fontSize: tokens.fontSizeBase300,
    fontWeight: tokens.fontWeightSemibold,
  },
  muted: { margin: 0, color: tokens.colorNeutralForeground2 },
  pills: {
    display: "flex",
    flexWrap: "wrap",
    gap: tokens.spacingHorizontalS,
    alignItems: "center",
  },
  gaps: { margin: 0, paddingInlineStart: tokens.spacingHorizontalXL },
  link: {
    color: tokens.colorBrandForegroundLink,
    textDecorationLine: "none",
    fontWeight: tokens.fontWeightSemibold,
    ":hover": { textDecorationLine: "underline" },
  },
});

function ErrorState({
  error,
  what,
}: {
  readonly error: ApiError;
  readonly what: string;
}): ReactElement {
  if (error instanceof ForbiddenError) {
    return <ForbiddenState workspace="Trace replay" correlationId={error.correlationId} />;
  }
  const reference = error.correlationId !== "" ? ` (reference ${error.correlationId})` : "";
  return (
    <div data-testid="error-state">
      <StyledErrorState
        title={`Could not load ${what}`}
        message={`The request failed${reference}. This is not an empty result.`}
      />
    </div>
  );
}

export function TraceView({ trace }: { readonly trace: TraceDetail }): ReactElement {
  const styles = useStyles();
  const c = trace.completeness;
  return (
    <section
      className={styles.section}
      aria-label={`Trace ${trace.trace_id}`}
      data-testid="trace-view"
    >
      <h2 className={styles.heading}>Trace {trace.trace_id}</h2>
      <div className={styles.pills}>
        <span data-testid="completeness">
          <StatusPill
            label={`${c.state === "complete" ? STRINGS.complete : STRINGS.partial}: ${c.span_count} spans, ${c.gap_count} gaps, ${c.late_count} late`}
            tone={c.state === "complete" ? "success" : "warning"}
          />
        </span>
        <span data-testid="trace-sampling">
          <StatusPill label={traceSamplingText(trace.sampling)} tone="neutral" />
        </span>
        {c.truncated ? (
          <span data-testid="truncated">
            <StatusPill label={STRINGS.truncated} tone="warning" />
          </span>
        ) : null}
      </div>
      <h3 className={styles.subheading}>{STRINGS.gapsHeading}</h3>
      {trace.gaps.length === 0 ? (
        <p className={styles.muted} data-testid="no-gaps">
          {STRINGS.noGaps}
        </p>
      ) : (
        <ul className={styles.gaps} data-testid="gap-list" aria-label={STRINGS.gapsHeading}>
          {trace.gaps.map((g, i) => (
            <li key={`${g.reason}-${g.span_id ?? "none"}-${i}`}>
              {STRINGS.gapReason[g.reason]}
              {g.count > 1 ? ` (${g.count})` : ""}: {g.detail}
            </li>
          ))}
        </ul>
      )}
      <TraceTree spans={trace.spans} gaps={trace.gaps} />
    </section>
  );
}

function TraceDetailSection({
  domainId,
  traceId,
}: {
  readonly domainId: string;
  readonly traceId: string;
}): ReactElement {
  const query = useTrace({ domainId, traceId });
  if (query.isError) return <ErrorState error={query.error} what="the trace" />;
  if (query.isPending) {
    return (
      <div aria-busy="true" data-testid="trace-loading">
        <LoadingState label={STRINGS.loading} rows={5} />
      </div>
    );
  }
  return <TraceView trace={query.data} />;
}

function TraceList({ domainId }: { readonly domainId: string }): ReactElement {
  const styles = useStyles();
  const query = useTraceList(domainId);
  const [params] = useSearchParams();
  if (query.isError) return <ErrorState error={query.error} what="traces" />;
  if (query.isPending) {
    return (
      <div aria-busy="true" data-testid="trace-list-loading">
        <LoadingState label={STRINGS.loading} rows={5} />
      </div>
    );
  }
  const items = query.data.pages.flatMap((p) => p.items);
  if (items.length === 0) {
    return (
      <div data-testid="empty-state">
        <EmptyState title={STRINGS.noTraces} />
      </div>
    );
  }
  const columns: readonly DataTableColumn<TraceSummary>[] = [
    {
      key: "trace",
      header: STRINGS.columns.trace,
      minWidth: "200px",
      render: (t) => {
        const next = new URLSearchParams(params);
        next.set("trace_id", t.trace_id);
        return (
          <Link to={`?${next.toString()}`} className={styles.link}>
            {STRINGS.openTrace} {t.trace_id}
          </Link>
        );
      },
    },
    { key: "root", header: STRINGS.columns.root, render: (t) => t.root_name ?? "unnamed root" },
    { key: "spans", header: STRINGS.columns.spans, render: (t) => `${t.span_count} spans` },
    {
      key: "errors",
      header: STRINGS.columns.errors,
      render: (t) =>
        t.error_count > 0 ? (
          <StatusPill label={`${t.error_count} errors`} tone="danger" />
        ) : (
          `${t.error_count} errors`
        ),
    },
    {
      key: "started",
      header: STRINGS.columns.started,
      render: (t) => <Timestamp value={t.started_at} />,
    },
  ];
  return (
    <section className={styles.section} aria-label={STRINGS.traceList}>
      <h2 className={styles.heading}>{STRINGS.traceList}</h2>
      <DataTable
        label={STRINGS.traceList}
        columns={columns}
        rows={items}
        getRowId={(t) => t.trace_id}
      />
      {query.hasNextPage ? (
        <div>
          <Button onClick={() => void query.fetchNextPage()}>{STRINGS.loadMore}</Button>
        </div>
      ) : null}
    </section>
  );
}

export function ReplayPage(): ReactElement {
  const [params] = useSearchParams();
  const { domainId } = useSelectedDomain();
  const traceId = params.get("trace_id") ?? "";
  return (
    <PageTemplate title={STRINGS.title} description={STRINGS.readOnly}>
      {domainId === "" ? (
        <div data-testid="domain-required">
          <EmptyState title={STRINGS.domainRequired} />
        </div>
      ) : (
        <>
          <TraceList domainId={domainId} />
          {traceId !== "" ? <TraceDetailSection domainId={domainId} traceId={traceId} /> : null}
        </>
      )}
    </PageTemplate>
  );
}
