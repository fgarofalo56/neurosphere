import { Button } from "@fluentui/react-components";
import type { ReactElement } from "react";
import { useNavigate, useSearchParams } from "react-router";
import { useSelectedDomain } from "../../app/domain";
import { EmptyState, LoadingState, PageTemplate, Timestamp } from "../../design-system";
import { ChartFrame } from "../charts";
import {
  Citations,
  DecisionControls,
  MutationError,
  PublicationBadge,
  QueryErrorState,
  RequestPublication,
  ShareDialog,
} from "./components";
import { useDeleteReport, useInvalidateReports, useReport, useReportRun } from "./hooks";
import { Panel } from "./Panel";
import { REPORTS_LIST_ROUTE } from "./paths";
import { STRINGS } from "./strings";
import type { ReportView } from "./types";

function RunSection({ report }: { readonly report: ReportView }): ReactElement {
  const run = useReportRun({ domainId: report.domain_id, reportId: report.id });

  if (run.isError) {
    return <QueryErrorState error={run.error} onRetry={() => void run.refetch()} />;
  }
  if (run.isPending) {
    return (
      <div aria-busy="true">
        <LoadingState label={STRINGS.loading} />
      </div>
    );
  }
  const result = run.data;
  return (
    <Panel label={report.title} testId="run-section">
      <p>{STRINGS.runDescription}</p>
      {result.status === "no_data" || result.chart_plan === null ? (
        <div role="status" data-testid="no-data-state">
          <EmptyState title={STRINGS.noData} description={STRINGS.noDataDetail} />
        </div>
      ) : (
        <ChartFrame plan={result.chart_plan} title={report.title} />
      )}
      {result.truncated ? (
        <p role="status" data-testid="truncated">
          {STRINGS.truncated}
        </p>
      ) : null}
      <Citations citations={result.citations} />
      <p>
        {STRINGS.ranAt} <Timestamp value={result.ran_at} />{" "}
        <Button size="small" disabled={run.isFetching} onClick={() => void run.refetch()}>
          {STRINGS.run}
        </Button>
      </p>
    </Panel>
  );
}

function DeleteButton({ report }: { readonly report: ReportView }): ReactElement {
  const navigate = useNavigate();
  const invalidate = useInvalidateReports();
  const del = useDeleteReport();
  return (
    <span>
      <Button
        data-testid="delete-report"
        disabled={del.isPending}
        onClick={() => {
          if (!window.confirm(STRINGS.delete.confirm)) return;
          del.mutate(
            { domainId: report.domain_id, reportId: report.id, etag: report.etag },
            {
              onSuccess: () => {
                void invalidate();
                void navigate(
                  `/${REPORTS_LIST_ROUTE}?domain_id=${encodeURIComponent(report.domain_id)}`,
                );
              },
            },
          );
        }}
      >
        {STRINGS.delete.action}
      </Button>
      {del.error !== null ? <MutationError error={del.error} /> : null}
    </span>
  );
}

export function ReportViewPage(): ReactElement {
  const [params] = useSearchParams();
  const { domainId } = useSelectedDomain();
  const reportId = params.get("report_id") ?? "";
  const enabled = domainId !== "" && reportId !== "";
  const query = useReport({ domainId, reportId }, enabled);

  if (!enabled) {
    return (
      <PageTemplate title={STRINGS.viewTitle}>
        <div data-testid="report-required">
          <EmptyState title={STRINGS.domainRequired} />
        </div>
      </PageTemplate>
    );
  }
  if (query.isError) {
    return (
      <PageTemplate title={STRINGS.viewTitle}>
        <QueryErrorState error={query.error} onRetry={() => void query.refetch()} />
      </PageTemplate>
    );
  }
  if (query.isPending) {
    return (
      <PageTemplate title={STRINGS.viewTitle} busy>
        <div aria-busy="true">
          <LoadingState label={STRINGS.loading} />
        </div>
      </PageTemplate>
    );
  }
  const report = query.data;
  // A reviewer reads the definition of a pending request but cannot run it (the API says 404).
  const canRun = !report.can_decide_publication;

  return (
    <PageTemplate title={report.title}>
      <Panel label="Report details">
        <p>
          <PublicationBadge state={report.publication.state} />{" "}
          {report.is_owner ? STRINGS.youAreOwner : `${STRINGS.owner}: ${report.owner}`}
        </p>
        <p>
          {STRINGS.headers.updated}: <Timestamp value={report.updated_at} />
        </p>
        {report.is_owner ? (
          <p>
            <ShareDialog report={report} /> <RequestPublication report={report} />{" "}
            <DeleteButton report={report} />
          </p>
        ) : null}
      </Panel>
      <DecisionControls report={report} />
      {canRun ? <RunSection report={report} /> : null}
    </PageTemplate>
  );
}
