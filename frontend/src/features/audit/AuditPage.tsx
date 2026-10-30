import { Button, Dropdown, Label, Option, makeStyles, tokens } from "@fluentui/react-components";
import { useId, useState, type ReactElement, type ReactNode } from "react";
import { useSearchParams } from "react-router";
import { ApiError, DependencyTransientError, ForbiddenError } from "../../api/index.js";
import {
  DataTable,
  EmptyState,
  ErrorState,
  LoadingState,
  PageTemplate,
  StatusPill,
  Timestamp,
  type DataTableColumn,
  type StatusTone,
} from "../../design-system";
import { ForbiddenState } from "../workspaces/ForbiddenState";
import { useAuditDomains, useAuditRecords, useVerifyChain } from "./data";
import { AUDIT_DOMAIN_PARAM } from "./paths";
import { RecordDrawer } from "./RecordDrawer";
import { STRINGS } from "./strings";
import type { AuditDomain, AuditRecord } from "./types";

const useStyles = makeStyles({
  row: {
    display: "flex",
    alignItems: "center",
    columnGap: tokens.spacingHorizontalS,
    flexWrap: "wrap",
  },
  dropdown: { minWidth: "280px" },
  stack: { display: "flex", flexDirection: "column", rowGap: tokens.spacingVerticalM },
  muted: { color: tokens.colorNeutralForeground2, fontSize: tokens.fontSizeBase200 },
});

const UNCONFIGURED_REASON = "audit_store_unconfigured";

/** One state for every failed audit call: 403, store unconfigured (503), or a plain failure. */
function ProblemState({
  error,
  failedTitle,
  onRetry,
}: {
  readonly error: ApiError;
  readonly failedTitle: string;
  readonly onRetry?: () => void;
}): ReactElement {
  if (error instanceof ForbiddenError) {
    return (
      <ForbiddenState workspace={STRINGS.forbiddenWorkspace} correlationId={error.correlationId} />
    );
  }
  if (error instanceof DependencyTransientError && error.problem?.reason === UNCONFIGURED_REASON) {
    return (
      <ErrorState
        tone="warning"
        title={STRINGS.storeUnconfiguredTitle}
        message={STRINGS.storeUnconfiguredBody}
        testId="audit-unconfigured"
      />
    );
  }
  return (
    <ErrorState
      title={failedTitle}
      message={error.correlationId === "" ? undefined : `Reference: ${error.correlationId}.`}
      testId="audit-error"
      {...(onRetry === undefined ? {} : { onRetry })}
    />
  );
}

function outcomeLabel(r: AuditRecord): { label: string; tone: StatusTone } {
  if (r.outcome !== null) {
    return {
      label: r.outcome.result,
      tone: r.outcome.result === "succeeded" ? "success" : "warning",
    };
  }
  if (r.denial !== null) return { label: `denied: ${r.denial.code}`, tone: "danger" };
  return { label: STRINGS.notRecorded, tone: "neutral" };
}

function columns(onOpen: (r: AuditRecord) => void): readonly DataTableColumn<AuditRecord>[] {
  const c = STRINGS.columns;
  return [
    { key: "sequence", header: c.sequence, render: (r) => r.sequence },
    { key: "time", header: c.time, render: (r) => <Timestamp value={r.recorded_at} /> },
    { key: "kind", header: c.kind, render: (r) => r.kind },
    { key: "operation", header: c.operation, render: (r) => r.operation },
    {
      key: "outcome",
      header: c.outcome,
      render: (r) => {
        const o = outcomeLabel(r);
        return <StatusPill label={o.label} tone={o.tone} />;
      },
    },
    { key: "channel", header: c.channel, render: (r) => r.channel ?? STRINGS.notRecorded },
    { key: "actor", header: c.actor, render: (r) => r.actor.principal_pseudonym },
    {
      key: "subject",
      header: c.subject,
      render: (r) =>
        r.subject === null
          ? STRINGS.notRecorded
          : `${r.subject.target.canonical_id} (version ${r.subject.target_version ?? STRINGS.notRecorded})`,
    },
    {
      key: "actions",
      header: c.actions,
      render: (r) => (
        <Button
          size="small"
          onClick={() => onOpen(r)}
          aria-label={STRINGS.detailsFor(r.sequence)}
          data-testid="audit-open"
        >
          {STRINGS.details}
        </Button>
      ),
    },
  ];
}

function VerifyControl({ domain }: { readonly domain: string }): ReactElement {
  const styles = useStyles();
  const verify = useVerifyChain();
  const result = verify.data;
  let outcome: ReactNode = null;
  if (verify.isError) {
    outcome = <ProblemState error={verify.error} failedTitle={STRINGS.verifyFailed} />;
  } else if (result !== undefined) {
    outcome = result.ok ? (
      <StatusPill
        tone="success"
        label={STRINGS.verifyValid(result.records_checked)}
        testId="audit-verify-result"
      />
    ) : (
      <StatusPill
        tone="danger"
        label={`${STRINGS.verifyBreak(result.first_invalid_sequence)}${
          result.reason === null ? "" : ` Reason: ${result.reason}.`
        }`}
        testId="audit-verify-result"
      />
    );
  }
  return (
    <div className={styles.stack}>
      <div className={styles.row}>
        <Button
          appearance="primary"
          disabled={verify.isPending}
          onClick={() => verify.mutate({ domain })}
          data-testid="audit-verify"
        >
          {verify.isPending ? STRINGS.verifying : STRINGS.verify}
        </Button>
        <span role="status">{verify.isPending ? null : outcome}</span>
      </div>
    </div>
  );
}

function Records({ domain }: { readonly domain: string }): ReactElement {
  const styles = useStyles();
  const q = useAuditRecords(domain);
  const [open, setOpen] = useState<AuditRecord | null>(null);

  if (q.isPending) return <LoadingState label={STRINGS.recordsLoading} rows={5} />;
  if (q.isError) {
    return (
      <ProblemState
        error={q.error}
        failedTitle={STRINGS.recordsFailed}
        onRetry={() => void q.refetch()}
      />
    );
  }
  const rows = q.data.flatMap((p) => p.items);
  if (rows.length === 0) {
    return (
      <EmptyState title={STRINGS.emptyTitle} description={STRINGS.emptyBody} testId="audit-empty" />
    );
  }
  return (
    <div className={styles.stack}>
      <DataTable
        label={STRINGS.recordsTableLabel}
        columns={columns(setOpen)}
        rows={rows}
        getRowId={(r) => r.audit_id}
        getRowProps={(r) => ({ "data-testid": "audit-row", "data-sequence": String(r.sequence) })}
      />
      {q.hasNextPage ? (
        <div>
          <Button
            disabled={q.isFetchingNextPage}
            onClick={() => void q.fetchNextPage()}
            data-testid="audit-more"
          >
            {q.isFetchingNextPage ? STRINGS.loadingMore : STRINGS.loadMore}
          </Button>
        </div>
      ) : (
        <span className={styles.muted} data-testid="audit-end">
          {STRINGS.endOfChain}
        </span>
      )}
      <RecordDrawer record={open} onClose={() => setOpen(null)} />
    </div>
  );
}

function DomainPicker({
  domains,
  selected,
  onSelect,
}: {
  readonly domains: readonly AuditDomain[];
  readonly selected: AuditDomain | undefined;
  readonly onSelect: (domainId: string) => void;
}): ReactElement {
  const styles = useStyles();
  const id = useId();
  return (
    <div className={styles.row}>
      <Label htmlFor={id}>{STRINGS.domainLabel}</Label>
      <Dropdown
        id={id}
        className={styles.dropdown}
        placeholder={STRINGS.domainPlaceholder}
        value={selected === undefined ? "" : selected.display_name}
        selectedOptions={selected === undefined ? [] : [selected.domain_id]}
        onOptionSelect={(_e, option) => {
          if (option.optionValue !== undefined) onSelect(option.optionValue);
        }}
      >
        {domains.map((d) => (
          <Option key={d.domain_id} value={d.domain_id} text={d.display_name}>
            {d.display_name}
          </Option>
        ))}
      </Dropdown>
    </div>
  );
}

/**
 * Read-only audit log. The domain list is the audit adapter's own (an auditor holds no data.read,
 * so /me/domains is 403 for them); the selection lives in `?audit_domain=`, never `domain_id`.
 * Nothing is enriched, joined or exported here: rows are the API's fields as returned.
 */
export function AuditPage(): ReactElement {
  const [params, setParams] = useSearchParams();
  const domains = useAuditDomains({});
  const items = domains.data?.items ?? [];
  const requested = params.get(AUDIT_DOMAIN_PARAM);
  const selected =
    requested === null || requested === ""
      ? items[0]
      : items.find((d) => d.domain_id === requested);

  const select = (domainId: string): void => {
    const next = new URLSearchParams(params);
    next.set(AUDIT_DOMAIN_PARAM, domainId);
    setParams(next);
  };

  let body: ReactNode;
  if (domains.isPending) {
    body = <LoadingState label={STRINGS.domainsLoading} rows={2} />;
  } else if (domains.isError) {
    body = (
      <ProblemState
        error={domains.error}
        failedTitle={STRINGS.domainsFailed}
        onRetry={() => void domains.refetch()}
      />
    );
  } else if (selected === undefined) {
    body = <EmptyState title={STRINGS.domainUnavailable} testId="audit-domain-unavailable" />;
  } else {
    body = (
      <>
        <VerifyControl key={`verify-${selected.domain_id}`} domain={selected.domain_id} />
        <Records key={`records-${selected.domain_id}`} domain={selected.domain_id} />
      </>
    );
  }

  return (
    <PageTemplate
      title={STRINGS.pageTitle}
      description={STRINGS.pageDescription}
      data-testid="audit-page"
      busy={domains.isPending}
      {...(items.length > 0
        ? {
            toolbar: <DomainPicker domains={items} selected={selected} onSelect={select} />,
          }
        : {})}
    >
      {body}
    </PageTemplate>
  );
}
