import {
  Button,
  MessageBar,
  MessageBarActions,
  MessageBarBody,
  makeStyles,
  tokens,
} from "@fluentui/react-components";
import { useState, type ReactElement } from "react";
import { Link, useSearchParams } from "react-router";
import { StaleVersionError } from "../../../api/index.js";
import {
  DataTable,
  EmptyState,
  LoadingState,
  PageTemplate,
  Panel,
  StatusPill,
  Timestamp,
} from "../../../design-system";
import { ChangeConfirmDialog } from "../../governed-change";
import { ADMIN_IDENTITY_ROUTE } from "../shared/adminPaths";
import { AdminTabs } from "../shared/AdminTabs";
import { CopyableId, QueryErrorState, changeErrorText } from "../shared/AdminStates";
import { ChangeControls } from "./ChangeControls";
import {
  EMPTY_FORM,
  buildRequest,
  diffOf,
  expiryRequired,
  formValid,
  isExpired,
  needsReason,
  showsExpiry,
  titleOf,
  versionOf,
  type ChangeForm,
  type Draft,
  type DraftKind,
} from "./changes";
import { useIdentityChange, useInvalidateIdentity, usePrincipal } from "./hooks";
import { IDENTITY_STRINGS as S } from "./strings";
import type { PrincipalSummary } from "./types";

const useStyles = makeStyles({
  stack: { display: "flex", flexDirection: "column", rowGap: tokens.spacingVerticalM },
  row: { display: "flex", columnGap: tokens.spacingHorizontalS, flexWrap: "wrap" },
});

function newId(prefix: string): string {
  return `${prefix}-${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`;
}

function Expiry({ value }: { readonly value: string | null }): ReactElement {
  if (value === null) return <span>{S.noExpiry}</span>;
  return (
    <span>
      <Timestamp value={value} />
      {isExpired(value) ? <StatusPill label={S.expired} tone="warning" /> : null}
    </span>
  );
}

function Detail({ principalId }: { readonly principalId: string }): ReactElement {
  const styles = useStyles();
  const query = usePrincipal(principalId);
  const change = useIdentityChange();
  const invalidate = useInvalidateIdentity();
  const [draft, setDraft] = useState<Draft | null>(null);
  const [form, setForm] = useState<ChangeForm>(EMPTY_FORM);
  const [done, setDone] = useState<string | null>(null);

  if (query.isError) {
    return <QueryErrorState error={query.error} onRetry={() => void query.refetch()} />;
  }
  if (query.isPending) {
    return (
      <div aria-busy="true" data-testid="loading-state">
        <LoadingState label={S.loadingDetail} rows={5} />
      </div>
    );
  }
  const summary: PrincipalSummary = query.data.data;
  const etag = query.data.etag;
  const revocation = summary.revocation;

  const open = (kind: DraftKind, extra: Partial<Draft> = {}): void => {
    change.reset();
    setDone(null);
    setForm(EMPTY_FORM);
    const recordId =
      extra.recordId ??
      (kind === "assign-role" ? newId("role") : kind === "put-grant" ? newId("grant") : undefined);
    setDraft({ kind, ...extra, ...(recordId === undefined ? {} : { recordId }) });
  };
  const close = (): void => {
    setDraft(null);
    change.reset();
  };
  const submit = (expiry: string | null): void => {
    if (draft === null) return;
    const request = buildRequest(draft, form, { principalId, etag, expiry });
    change.mutate(request, {
      onSuccess: () => {
        setDone(S.done(titleOf(draft.kind)));
        setDraft(null);
        void invalidate();
      },
      onError: (error) => {
        // A stale write is never retried: re-read so the next confirm shows the current version.
        if (error instanceof StaleVersionError) void query.refetch();
      },
    });
  };

  return (
    <div className={styles.stack}>
      {revocation.revoked ? (
        <MessageBar intent="error" role="alert" data-testid="revoked-banner">
          <MessageBarBody>
            {S.revokedBanner(revocation.mode ?? "unknown", revocation.reason ?? "unknown")}
          </MessageBarBody>
          <MessageBarActions>
            <Button onClick={() => open("lift")}>{S.actions.lift}</Button>
          </MessageBarActions>
        </MessageBar>
      ) : null}
      {done === null ? null : (
        <div role="status" data-testid="change-done">
          {done}
        </div>
      )}
      <Panel title={S.detailTitle}>
        <dl>
          <dt>{S.headers.principal}</dt>
          <dd>
            <CopyableId value={summary.principal.principal_id} label="principal id" />
          </dd>
          <dt>{S.headers.kind}</dt>
          <dd>{summary.principal.principal_kind}</dd>
          <dt>ETag</dt>
          <dd data-testid="principal-etag">{etag ?? "unknown"}</dd>
        </dl>
      </Panel>

      <Panel title={S.sections.memberships}>
        {summary.memberships.length === 0 ? (
          <EmptyState title={S.emptySection.memberships} />
        ) : (
          <DataTable
            label={S.sections.memberships}
            rows={summary.memberships.map((domainId) => ({ domainId }))}
            getRowId={(row) => row.domainId}
            getRowProps={() => ({ "data-testid": "membership-row" })}
            columns={[
              { key: "domain", header: S.headers.domains, render: (row) => row.domainId },
              {
                key: "actions",
                header: S.headers.actions,
                render: (row) => (
                  <Button
                    size="small"
                    onClick={() => open("remove-membership", { domainId: row.domainId })}
                  >
                    {S.actions.remove}
                  </Button>
                ),
              },
            ]}
          />
        )}
        <div className={styles.row}>
          <Button onClick={() => open("add-membership")}>{S.actions.addMembership}</Button>
        </div>
      </Panel>

      <Panel title={S.sections.assignments}>
        {summary.assignments.length === 0 ? (
          <EmptyState title={S.emptySection.assignments} />
        ) : (
          <DataTable
            label={S.sections.assignments}
            rows={summary.assignments}
            getRowId={(row) => row.assignment_id}
            getRowProps={() => ({ "data-testid": "assignment-row" })}
            columns={[
              { key: "role", header: S.headers.role, render: (row) => row.role },
              {
                key: "domains",
                header: S.headers.domains,
                render: (row) => (row.domain_ids.length === 0 ? "-" : row.domain_ids.join(", ")),
              },
              {
                key: "expires",
                header: S.headers.expires,
                render: (row) => <Expiry value={row.expires_at} />,
              },
              { key: "reason", header: S.headers.reason, render: (row) => row.reason ?? "-" },
              {
                key: "actions",
                header: S.headers.actions,
                render: (row) => (
                  <Button
                    size="small"
                    onClick={() => open("remove-role", { recordId: row.assignment_id })}
                  >
                    {S.actions.remove}
                  </Button>
                ),
              },
            ]}
          />
        )}
        <div className={styles.row}>
          <Button onClick={() => open("assign-role")}>{S.actions.assign}</Button>
        </div>
      </Panel>

      <Panel title={S.sections.grants}>
        {summary.grants.length === 0 ? (
          <EmptyState title={S.emptySection.grants} />
        ) : (
          <DataTable
            label={S.sections.grants}
            rows={summary.grants}
            getRowId={(row) => row.grant_id}
            getRowProps={() => ({ "data-testid": "grant-row" })}
            columns={[
              { key: "resource", header: S.headers.resource, render: (row) => row.resource_id },
              {
                key: "permissions",
                header: S.headers.permissions,
                render: (row) => row.permissions.join(", "),
              },
              {
                key: "expires",
                header: S.headers.expires,
                render: (row) => <Expiry value={row.expires_at} />,
              },
              { key: "reason", header: S.headers.reason, render: (row) => row.reason },
              {
                key: "actions",
                header: S.headers.actions,
                render: (row) => (
                  <Button
                    size="small"
                    onClick={() => open("remove-grant", { recordId: row.grant_id })}
                  >
                    {S.actions.remove}
                  </Button>
                ),
              },
            ]}
          />
        )}
        <div className={styles.row}>
          <Button onClick={() => open("put-grant")}>{S.actions.putGrant}</Button>
        </div>
      </Panel>

      <Panel title={S.sections.revocation}>
        <p data-testid="revocation-state">{revocation.revoked ? S.revoked : S.active}</p>
        {revocation.revoked ? null : (
          <Button onClick={() => open("revoke")}>{S.actions.revoke}</Button>
        )}
      </Panel>

      {draft === null ? null : (
        <ChangeConfirmDialog
          open
          title={titleOf(draft.kind)}
          target={principalId}
          version={versionOf(draft.kind, etag)}
          diff={diffOf(draft, form, summary)}
          reasonMode="code"
          controlsValid={formValid(draft, form)}
          showExpiry={showsExpiry(draft.kind)}
          expiryRequired={expiryRequired(draft.kind)}
          submitting={change.isPending}
          reasonNote={needsReason(draft.kind) ? undefined : S.dialog.noReasonOnGrantRemoval}
          error={change.isError ? changeErrorText(change.error) : undefined}
          controls={
            <ChangeControls
              draft={draft}
              form={form}
              disabled={change.isPending}
              onChange={setForm}
            />
          }
          onSubmit={({ expiry }) => submit(expiry)}
          onClose={close}
        />
      )}
    </div>
  );
}

export function PrincipalDetailPage(): ReactElement {
  const [params] = useSearchParams();
  const principalId = params.get("principal_id") ?? "";
  return (
    <PageTemplate title={S.detailTitle} description={S.listDescription}>
      <AdminTabs />
      <Link to={`/${ADMIN_IDENTITY_ROUTE}`}>{S.backToList}</Link>
      {principalId === "" ? (
        <EmptyState title={S.noPrincipal} testId="empty-state" />
      ) : (
        <Detail principalId={principalId} />
      )}
    </PageTemplate>
  );
}
