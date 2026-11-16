import { Button, Dropdown, Label, Option, makeStyles, tokens } from "@fluentui/react-components";
import { useId, type ReactElement, type ReactNode } from "react";
import { Link, useSearchParams } from "react-router";
import {
  DataTable,
  EmptyState,
  LoadingState,
  PageTemplate,
  Panel,
  Timestamp,
  type DataTableColumn,
} from "../../design-system";
import { useAuditDomains } from "../audit/data";
import { downloadBundle, useBundle, useFrameworks, type ControlSummary } from "./data";
import { ObservationsTable, ProblemState, SummaryPill, SupportPill, DomainPicker } from "./parts";
import { COMPLIANCE_DOMAIN_PARAM, COMPLIANCE_FRAMEWORK_PARAM, controlLink } from "./paths";
import { STRINGS } from "./strings";

const useStyles = makeStyles({
  stack: { display: "flex", flexDirection: "column", rowGap: tokens.spacingVerticalL },
  row: {
    display: "flex",
    alignItems: "center",
    columnGap: tokens.spacingHorizontalS,
    flexWrap: "wrap",
  },
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

function columns(domain: string): readonly DataTableColumn<ControlSummary>[] {
  return [
    {
      key: "control",
      header: STRINGS.columns.control,
      render: (c) => (
        <Link to={controlLink(domain, c.control.framework_id, c.control.control_id)}>
          {c.control.control_id}
        </Link>
      ),
    },
    { key: "title", header: STRINGS.columns.title, render: (c) => c.control.title },
    {
      key: "support",
      header: STRINGS.columns.support,
      render: (c) => <SupportPill status={c.support_status} />,
    },
    {
      key: "evidence",
      header: STRINGS.columns.evidence,
      render: (c) => <SummaryPill word={c.summary} />,
    },
  ];
}

function BundleBody({
  domainId,
  frameworkId,
}: {
  readonly domainId: string;
  readonly frameworkId: string;
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
        <LoadingState label={STRINGS.loading} rows={4} />
      </div>
    );
  }
  const bundle = query.data;
  if (bundle.controls.length === 0) {
    return (
      <EmptyState testId="empty-state" title={STRINGS.emptyTitle} description={STRINGS.emptyBody} />
    );
  }
  return (
    <div className={styles.stack} data-testid="bundle-body">
      <Panel
        title={STRINGS.tableTitle}
        landmark="region"
        actions={
          <Button appearance="primary" onClick={() => downloadBundle(bundle)}>
            {STRINGS.download}
          </Button>
        }
      >
        <p className={styles.muted}>{STRINGS.downloadHint}</p>
        <DataTable
          label={STRINGS.tableLabel}
          columns={columns(domainId)}
          rows={bundle.controls}
          getRowId={(c) => c.control.control_id}
          getRowProps={(c) => ({ "data-testid": `control-${c.control.control_id}` })}
        />
      </Panel>
      <Panel title={STRINGS.observationsTitle} landmark="region">
        <ObservationsTable observations={bundle.observations} />
      </Panel>
      <Panel title={STRINGS.windowLabel} landmark="region">
        <dl className={styles.dl}>
          <dt>{STRINGS.windowLabel}</dt>
          <dd className={styles.dd}>
            <Timestamp value={bundle.window_start} grain="day" />
            {" to "}
            <Timestamp value={bundle.window_end} grain="day" />
          </dd>
          <dt>{STRINGS.frameworkVersionLabel}</dt>
          <dd className={styles.dd}>{bundle.framework_version}</dd>
          <dt>{STRINGS.libraryLabel}</dt>
          <dd className={styles.dd}>{bundle.library_version}</dd>
          <dt>{STRINGS.digestLabel}</dt>
          <dd className={styles.dd} data-testid="bundle-digest">
            {bundle.digest}
          </dd>
        </dl>
        <p className={styles.muted} data-testid="disclaimer">
          {STRINGS.disclaimer}
        </p>
      </Panel>
    </div>
  );
}

function FrameworkPicker({
  frameworks,
  selected,
  onSelect,
}: {
  readonly frameworks: readonly { framework_id: string; title: string }[];
  readonly selected: string;
  readonly onSelect: (id: string) => void;
}): ReactElement {
  const styles = useStyles();
  const id = useId();
  const current = frameworks.find((f) => f.framework_id === selected);
  return (
    <div className={styles.row}>
      <Label htmlFor={id}>{STRINGS.frameworkLabel}</Label>
      <Dropdown
        id={id}
        value={current?.title ?? ""}
        selectedOptions={current === undefined ? [] : [current.framework_id]}
        onOptionSelect={(_e, option) => {
          if (option.optionValue !== undefined) onSelect(option.optionValue);
        }}
      >
        {frameworks.map((f) => (
          <Option key={f.framework_id} value={f.framework_id} text={f.title}>
            {f.title}
          </Option>
        ))}
      </Dropdown>
    </div>
  );
}

/**
 * Compliance evidence: pick a readable domain and a framework, see which controls have catalog,
 * audit, HITL, evaluation and cost evidence and which are the customer's, and download the
 * bundle. The domain list is the audit adapter's own (an auditor holds no data.read).
 */
export function CompliancePage(): ReactElement {
  const [params, setParams] = useSearchParams();
  const domains = useAuditDomains({});
  const frameworks = useFrameworks({});
  const items = domains.data?.items ?? [];
  const list = frameworks.data?.frameworks ?? [];
  const requestedDomain = params.get(COMPLIANCE_DOMAIN_PARAM);
  const selectedDomain =
    requestedDomain === null || requestedDomain === ""
      ? items[0]
      : items.find((d) => d.domain_id === requestedDomain);
  const requestedFramework = params.get(COMPLIANCE_FRAMEWORK_PARAM);
  const frameworkId =
    list.find((f) => f.framework_id === requestedFramework)?.framework_id ??
    list[0]?.framework_id ??
    "";

  const set = (key: string, value: string): void => {
    const next = new URLSearchParams(params);
    next.set(key, value);
    setParams(next);
  };

  let body: ReactNode;
  if (domains.isPending || frameworks.isPending) {
    body = <LoadingState label={STRINGS.domainsLoading} rows={2} />;
  } else if (domains.isError) {
    body = (
      <ProblemState
        error={domains.error}
        title={STRINGS.domainsFailed}
        onRetry={() => void domains.refetch()}
      />
    );
  } else if (frameworks.isError) {
    body = (
      <ProblemState
        error={frameworks.error}
        title={STRINGS.frameworksFailed}
        onRetry={() => void frameworks.refetch()}
      />
    );
  } else if (selectedDomain === undefined) {
    body = (
      <EmptyState
        testId="compliance-domain-unavailable"
        title={STRINGS.domainUnavailable}
        description={STRINGS.domainUnavailableBody}
      />
    );
  } else if (frameworkId === "") {
    body = <EmptyState title={STRINGS.frameworksEmpty} />;
  } else {
    body = (
      <BundleBody
        key={`${selectedDomain.domain_id}-${frameworkId}`}
        domainId={selectedDomain.domain_id}
        frameworkId={frameworkId}
      />
    );
  }

  return (
    <PageTemplate
      title={STRINGS.pageTitle}
      description={STRINGS.pageDescription}
      data-testid="compliance-page"
      busy={domains.isPending || frameworks.isPending}
      toolbarLabel={STRINGS.toolbarLabel}
      {...(items.length > 0 && list.length > 0
        ? {
            toolbar: (
              <>
                <DomainPicker
                  domains={items}
                  selected={selectedDomain}
                  onSelect={(id) => set(COMPLIANCE_DOMAIN_PARAM, id)}
                />
                <FrameworkPicker
                  frameworks={list}
                  selected={frameworkId}
                  onSelect={(id) => set(COMPLIANCE_FRAMEWORK_PARAM, id)}
                />
              </>
            ),
          }
        : {})}
    >
      {body}
    </PageTemplate>
  );
}
