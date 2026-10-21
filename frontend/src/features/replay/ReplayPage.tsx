import { MessageBar, MessageBarBody, MessageBarTitle } from "@fluentui/react-components";
import type { ReactElement } from "react";
import { Link, useSearchParams } from "react-router";
import { ForbiddenError, type ApiError } from "../../api/index.js";
import { ForbiddenState } from "../workspaces/ForbiddenState";
import { useTrace, useTraceList } from "./hooks";
import { STRINGS, traceSamplingText } from "./strings";
import { TraceTree } from "./TraceTree";
import type { TraceDetail } from "./types";

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
  return (
    <MessageBar intent="error" role="alert" data-testid="error-state">
      <MessageBarBody>
        <MessageBarTitle>Could not load {what}</MessageBarTitle>
        The request failed
        {error.correlationId !== "" ? ` (reference ${error.correlationId})` : ""}. This is not an
        empty result.
      </MessageBarBody>
    </MessageBar>
  );
}

export function TraceView({ trace }: { readonly trace: TraceDetail }): ReactElement {
  const c = trace.completeness;
  return (
    <section aria-label={`Trace ${trace.trace_id}`} data-testid="trace-view">
      <h2>Trace {trace.trace_id}</h2>
      <p data-testid="completeness">
        {c.state === "complete" ? STRINGS.complete : STRINGS.partial}: {c.span_count} spans,{" "}
        {c.gap_count} gaps, {c.late_count} late
      </p>
      <p data-testid="trace-sampling">{traceSamplingText(trace.sampling)}</p>
      {c.truncated ? <p data-testid="truncated">{STRINGS.truncated}</p> : null}
      <h3>{STRINGS.gapsHeading}</h3>
      {trace.gaps.length === 0 ? (
        <p data-testid="no-gaps">{STRINGS.noGaps}</p>
      ) : (
        <ul data-testid="gap-list" aria-label={STRINGS.gapsHeading}>
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
  if (query.isPending) return <p aria-busy="true">{STRINGS.loading}</p>;
  return <TraceView trace={query.data} />;
}

function TraceList({ domainId }: { readonly domainId: string }): ReactElement {
  const query = useTraceList(domainId);
  const [params] = useSearchParams();
  if (query.isError) return <ErrorState error={query.error} what="traces" />;
  if (query.isPending) return <p aria-busy="true">{STRINGS.loading}</p>;
  const items = query.data.pages.flatMap((p) => p.items);
  if (items.length === 0) return <p data-testid="empty-state">{STRINGS.noTraces}</p>;
  return (
    <section aria-label={STRINGS.traceList}>
      <h2>{STRINGS.traceList}</h2>
      <ul>
        {items.map((t) => {
          const next = new URLSearchParams(params);
          next.set("trace_id", t.trace_id);
          return (
            <li key={t.trace_id}>
              <Link to={`?${next.toString()}`}>
                {STRINGS.openTrace} {t.trace_id}
              </Link>{" "}
              {t.root_name ?? "unnamed root"}, {t.span_count} spans, {t.error_count} errors,{" "}
              {t.started_at}
            </li>
          );
        })}
      </ul>
      {query.hasNextPage ? (
        <button type="button" onClick={() => void query.fetchNextPage()}>
          {STRINGS.loadMore}
        </button>
      ) : null}
    </section>
  );
}

export function ReplayPage(): ReactElement {
  const [params] = useSearchParams();
  const domainId = params.get("domain_id") ?? "";
  const traceId = params.get("trace_id") ?? "";
  return (
    <section aria-label={STRINGS.title}>
      <h1>{STRINGS.title}</h1>
      <p>{STRINGS.readOnly}</p>
      {domainId === "" ? (
        <p data-testid="domain-required">{STRINGS.domainRequired}</p>
      ) : (
        <>
          <TraceList domainId={domainId} />
          {traceId !== "" ? <TraceDetailSection domainId={domainId} traceId={traceId} /> : null}
        </>
      )}
    </section>
  );
}
