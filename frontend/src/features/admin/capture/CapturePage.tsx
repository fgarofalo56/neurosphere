import { Button } from "@fluentui/react-components";
import { useState, type ReactElement, type ReactNode } from "react";
import { ForbiddenError, type ApiError } from "../../../api/index.js";
import {
  DataTable,
  EmptyState,
  LoadingState,
  PageTemplate,
  Panel,
  StatusPill,
  type StatusTone,
} from "../../../design-system";
import { AdminTabs } from "../shared/AdminTabs";
import { QueryErrorState } from "../shared/AdminStates";
import { useCapturePolicies, useCapturePolicy, useCaptureStatus } from "./hooks";
import { CAPTURE_STRINGS as S, offReasonText } from "./strings";
import type { CaptureCounters, CapturePolicyState, CapturePolicyView } from "./types";

const STATE_TONE: Record<CapturePolicyState, StatusTone> = {
  active: "success",
  proposed: "info",
  suspended: "warning",
  retired: "neutral",
};

function Loading({ label }: { readonly label: string }): ReactElement {
  return (
    <div aria-busy="true" data-testid="loading-state">
      <LoadingState label={label} rows={3} />
    </div>
  );
}

/** A denied secondary panel shows one line, so the page has a single forbidden state. */
function SecondaryError({
  error,
  onRetry,
}: {
  readonly error: ApiError;
  readonly onRetry: () => void;
}): ReactElement {
  if (error instanceof ForbiddenError) return <p data-testid="panel-denied">{S.panelDenied}</p>;
  return <QueryErrorState error={error} onRetry={onRetry} />;
}

function list(values: readonly string[]): string {
  return values.length === 0 ? S.none : values.join(", ");
}

function PolicyState({ state }: { readonly state: CapturePolicyState }): ReactElement {
  return <StatusPill label={S.state[state]} tone={STATE_TONE[state]} />;
}

function ReasonCounts({
  label,
  counts,
  testId,
}: {
  readonly label: string;
  readonly counts: Readonly<Record<string, number>>;
  readonly testId: string;
}): ReactElement | null {
  const entries = Object.entries(counts).filter(([, n]) => n > 0);
  if (entries.length === 0) return null;
  return (
    <div>
      <dt>{label}</dt>
      <dd>
        <ul data-testid={testId}>
          {entries.map(([code, n]) => (
            <li key={code}>
              <code>{code}</code>: {n}
            </li>
          ))}
        </ul>
      </dd>
    </div>
  );
}

function Counters({ counters }: { readonly counters: CaptureCounters }): ReactElement {
  const C = S.counters;
  const rows: [string, number, string][] = [
    [C.captured, counters.captured, "counter-captured"],
    [C.skippedNoPolicy, counters.capture_skipped_no_policy, "counter-skipped"],
    [C.skippedItemCap, counters.capture_skipped_item_cap, "counter-item-cap"],
    [C.failed, counters.capture_failed_total, "counter-failed"],
    [C.shed, counters.capture_shed, "counter-shed"],
    [C.auditWriteFailed, counters.audit_write_failed, "counter-audit-failed"],
    [C.inFlight, counters.in_flight, "counter-in-flight"],
  ];
  return (
    <dl data-testid="capture-counters">
      {rows.map(([label, value, testId]) => (
        <div key={testId}>
          <dt>{label}</dt>
          <dd data-testid={testId}>{value}</dd>
        </div>
      ))}
      <ReasonCounts
        label={C.failedByReason}
        counts={counters.capture_failed}
        testId="failed-reasons"
      />
      <ReasonCounts
        label={C.skippedByReason}
        counts={counters.skipped_reasons}
        testId="skipped-reasons"
      />
      <ReasonCounts label={C.shedByReason} counts={counters.shed_reasons} testId="shed-reasons" />
    </dl>
  );
}

function StatusPanel(): ReactElement {
  const query = useCaptureStatus();
  if (query.isError) {
    return <QueryErrorState error={query.error} onRetry={() => void query.refetch()} />;
  }
  if (query.isPending) return <Loading label={S.loadingStatus} />;
  const status = query.data.data;
  const code = status.off_reason;
  return (
    <>
      <div data-testid="capture-state">
        <StatusPill
          label={status.state === "active" ? S.active : S.off}
          tone={status.state === "active" ? "success" : "neutral"}
        />
      </div>
      {status.state === "off" && code !== null ? (
        <p data-testid="capture-off-reason">
          {S.offReason}: {offReasonText(code)} <code>{code}</code>
        </p>
      ) : null}
      <p data-testid="capture-policy-counts">{S.policyCounts(status.policies)}</p>
      <h3>{S.countersTitle}</h3>
      {status.counters === null ? (
        <p data-testid="capture-no-counters">{S.noCounters}</p>
      ) : (
        <Counters counters={status.counters} />
      )}
    </>
  );
}

function PoliciesPanel({
  onSelect,
}: {
  readonly onSelect: (policyId: string) => void;
}): ReactElement {
  const query = useCapturePolicies();
  if (query.isError) {
    return <SecondaryError error={query.error} onRetry={() => void query.refetch()} />;
  }
  if (query.isPending) return <Loading label={S.loadingPolicies} />;
  const page = query.data.data;
  if (!page.configured) {
    return (
      <div data-testid="empty-state">
        <EmptyState title={S.notConfigured} />
      </div>
    );
  }
  if (page.items.length === 0) {
    return (
      <div data-testid="empty-state">
        <EmptyState title={S.noPolicies} description={S.noPoliciesHint} />
      </div>
    );
  }
  const H = S.headers;
  return (
    <>
      {page.truncated ? <p data-testid="capture-truncated">{S.truncated}</p> : null}
      <DataTable
        label={S.policiesTitle}
        rows={[...page.items]}
        getRowId={(row) => row.policy_id}
        getRowProps={() => ({ "data-testid": "capture-policy-row" })}
        columns={[
          {
            key: "name",
            header: H.name,
            render: (row) => (
              <>
                {row.display_name} <code>{row.policy_id}</code>
              </>
            ),
          },
          { key: "domain", header: H.domain, render: (row) => <code>{row.domain_id}</code> },
          { key: "sources", header: H.sources, render: (row) => list(row.source_ids) },
          { key: "parts", header: H.parts, render: (row) => list(row.parts) },
          { key: "redaction", header: H.redaction, render: (row) => row.redaction_mode },
          {
            key: "sampling",
            header: H.sampling,
            render: (row) => S.sampling(row.sampling.rate, row.sampling.max_per_minute),
          },
          { key: "state", header: H.state, render: (row) => <PolicyState state={row.state} /> },
          { key: "version", header: H.version, render: (row) => row.version },
          {
            key: "approval",
            header: H.approval,
            render: (row) =>
              row.approved_audit_id === null ? S.none : <code>{row.approved_audit_id}</code>,
          },
          {
            key: "actions",
            header: H.actions,
            render: (row) => (
              <Button
                size="small"
                aria-label={`${S.view} ${row.policy_id}`}
                onClick={() => onSelect(row.policy_id)}
              >
                {S.view}
              </Button>
            ),
          },
        ]}
      />
    </>
  );
}

function Field({ label, children }: { readonly label: string; readonly children: ReactNode }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}

function PolicyFields({ policy }: { readonly policy: CapturePolicyView }): ReactElement {
  const F = S.fields;
  return (
    <dl data-testid="capture-policy-detail">
      <Field label={F.policyId}>
        <code>{policy.policy_id}</code>
      </Field>
      <Field label={F.displayName}>{policy.display_name}</Field>
      <Field label={F.domain}>
        <code>{policy.domain_id}</code>
      </Field>
      <Field label={F.sources}>{list(policy.source_ids)}</Field>
      <Field label={F.parts}>{list(policy.parts)}</Field>
      <Field label={F.detectorSet}>{policy.detector_set_version}</Field>
      <Field label={F.dictionaries}>{list(policy.customer_dictionary_ids)}</Field>
      <Field label={F.redaction}>{policy.redaction_mode}</Field>
      <Field label={F.kept}>{list(policy.kept_categories)}</Field>
      <Field label={F.sampling}>
        {S.sampling(policy.sampling.rate, policy.sampling.max_per_minute)}
      </Field>
      <Field label={F.maxPartChars}>{policy.max_part_chars ?? S.none}</Field>
      <Field label={F.retention}>
        {S.retention(policy.retention_days, policy.retention_class)}
      </Field>
      <Field label={F.state}>
        <PolicyState state={policy.state} />
      </Field>
      <Field label={F.version}>{policy.version}</Field>
      <Field label={F.previousVersion}>{policy.previous_version ?? S.none}</Field>
      <Field label={F.approvedIntent}>{policy.approved_intent_id ?? S.none}</Field>
      <Field label={F.approvedAudit}>
        <span data-testid="capture-detail-approval">{policy.approved_audit_id ?? S.none}</span>
      </Field>
      <Field label={F.effectiveFrom}>{policy.effective_from ?? S.none}</Field>
    </dl>
  );
}

function DetailPanel({
  policyId,
  onClose,
}: {
  readonly policyId: string;
  readonly onClose: () => void;
}): ReactElement {
  const query = useCapturePolicy(policyId);
  let body: ReactElement;
  if (query.isError) {
    body = <SecondaryError error={query.error} onRetry={() => void query.refetch()} />;
  } else if (query.isPending) {
    body = <Loading label={S.loadingPolicy} />;
  } else {
    body = <PolicyFields policy={query.data.data} />;
  }
  return (
    <Panel
      title={S.detailTitle}
      landmark="region"
      actions={
        <Button size="small" onClick={onClose}>
          {S.closeDetail}
        </Button>
      }
    >
      {body}
    </Panel>
  );
}

/**
 * Interaction capture (PRP-103 item 5). Read-only: policies, their settings and the capture
 * status with the off reason and counters. Only the fields named in `types` are rendered; no
 * content, key or host is ever shown. Changes are `capture_policy_change` actions (PRP-108).
 */
export function CapturePage(): ReactElement {
  const [selected, setSelected] = useState<string | null>(null);
  return (
    <PageTemplate title={S.title} description={S.description} layout="stack">
      <AdminTabs />
      <p data-testid="capture-change-note">{S.changeNote}</p>
      <Panel title={S.statusTitle}>
        <StatusPanel />
      </Panel>
      <Panel title={S.policiesTitle}>
        <PoliciesPanel onSelect={setSelected} />
      </Panel>
      {selected === null ? null : (
        <DetailPanel policyId={selected} onClose={() => setSelected(null)} />
      )}
    </PageTemplate>
  );
}
