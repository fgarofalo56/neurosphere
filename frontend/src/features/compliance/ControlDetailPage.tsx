import { makeStyles, tokens } from "@fluentui/react-components";
import type { ReactElement } from "react";
import { Link, useSearchParams } from "react-router";
import { EmptyState, LoadingState, PageTemplate, Panel } from "../../design-system";
import { useBundle } from "./data";
import { ObservationsTable, ProblemState, SummaryPill, SupportPill } from "./parts";
import {
  COMPLIANCE_CONTROL_PARAM,
  COMPLIANCE_DOMAIN_PARAM,
  COMPLIANCE_FRAMEWORK_PARAM,
  COMPLIANCE_ROUTE,
} from "./paths";
import { STRINGS } from "./strings";

const useStyles = makeStyles({
  stack: { display: "flex", flexDirection: "column", rowGap: tokens.spacingVerticalL },
  muted: { color: tokens.colorNeutralForeground2, fontSize: tokens.fontSizeBase200, margin: 0 },
  dl: {
    display: "grid",
    gridTemplateColumns: "max-content 1fr",
    columnGap: tokens.spacingHorizontalL,
    rowGap: tokens.spacingVerticalXS,
    margin: 0,
  },
  dd: { margin: 0, overflowWrap: "anywhere" },
});

function Detail({
  domainId,
  frameworkId,
  controlId,
}: {
  readonly domainId: string;
  readonly frameworkId: string;
  readonly controlId: string;
}): ReactElement {
  const styles = useStyles();
  const query = useBundle({ domainId, frameworkId });
  if (query.isError) {
    return (
      <ProblemState
        error={query.error}
        title={STRINGS.failedTitle}
        onRetry={() => void query.refetch()}
      />
    );
  }
  if (query.isPending) {
    return (
      <div aria-busy="true">
        <LoadingState label={STRINGS.loading} rows={3} />
      </div>
    );
  }
  const entry = query.data.controls.find((c) => c.control.control_id === controlId);
  if (entry === undefined) {
    return (
      <EmptyState
        testId="control-missing"
        title={STRINGS.detailMissingTitle}
        description={STRINGS.detailMissingBody}
      />
    );
  }
  const observations = query.data.observations.filter((o) =>
    entry.evidence_sources.includes(o.source_id),
  );
  return (
    <div className={styles.stack} data-testid="control-detail">
      <Panel title={entry.control.control_id} landmark="region">
        <dl className={styles.dl}>
          <dt>{STRINGS.columns.title}</dt>
          <dd className={styles.dd}>{entry.control.title}</dd>
          <dt>{STRINGS.detailSupport}</dt>
          <dd className={styles.dd}>
            <SupportPill status={entry.support_status} />
          </dd>
          <dt>{STRINGS.detailEvidence}</dt>
          <dd className={styles.dd}>
            <SummaryPill word={entry.summary} />
          </dd>
          <dt>{STRINGS.detailSource}</dt>
          <dd className={styles.dd}>
            <a href={entry.control.source_url} target="_blank" rel="noopener noreferrer">
              {entry.control.source_url}
            </a>
          </dd>
          <dt>{STRINGS.detailRetrieved}</dt>
          <dd className={styles.dd}>{entry.control.source_retrieved}</dd>
          <dt>{STRINGS.frameworkVersionLabel}</dt>
          <dd className={styles.dd}>{entry.control.framework_version}</dd>
        </dl>
        {entry.summary === "customer_responsibility" ? (
          <p className={styles.muted} data-testid="customer-note">
            {STRINGS.customerNote}
          </p>
        ) : null}
      </Panel>
      <Panel title={STRINGS.detailSources} landmark="region">
        {observations.length === 0 ? (
          <p className={styles.muted} data-testid="no-sources">
            {STRINGS.detailNoSources}
          </p>
        ) : (
          <ObservationsTable observations={observations} />
        )}
      </Panel>
      <p className={styles.muted}>{STRINGS.disclaimer}</p>
    </div>
  );
}

/** One control: its official source link, support status and the observations behind it. */
export function ControlDetailPage(): ReactElement {
  const [params] = useSearchParams();
  const domainId = params.get(COMPLIANCE_DOMAIN_PARAM) ?? "";
  const frameworkId = params.get(COMPLIANCE_FRAMEWORK_PARAM) ?? "";
  const controlId = params.get(COMPLIANCE_CONTROL_PARAM) ?? "";
  const back = `/${COMPLIANCE_ROUTE}?${new URLSearchParams({
    [COMPLIANCE_DOMAIN_PARAM]: domainId,
    [COMPLIANCE_FRAMEWORK_PARAM]: frameworkId,
  }).toString()}`;
  return (
    <PageTemplate
      title={STRINGS.detailTitle}
      description={STRINGS.pageDescription}
      data-testid="compliance-control-page"
      toolbarLabel={STRINGS.toolbarLabel}
      toolbar={<Link to={back}>{STRINGS.detailBack}</Link>}
    >
      {domainId === "" || frameworkId === "" || controlId === "" ? (
        <EmptyState
          testId="control-missing"
          title={STRINGS.detailMissingTitle}
          description={STRINGS.detailMissingBody}
        />
      ) : (
        <Detail domainId={domainId} frameworkId={frameworkId} controlId={controlId} />
      )}
    </PageTemplate>
  );
}
