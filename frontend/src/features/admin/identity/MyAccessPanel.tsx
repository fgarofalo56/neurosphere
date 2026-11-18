import type { ReactElement } from "react";
import {
  DataTable,
  EmptyState,
  LoadingState,
  Panel,
  StatusPill,
  Timestamp,
  type StatusTone,
} from "../../../design-system";
import { QueryErrorState } from "../shared/AdminStates";
import { ADMIN_STRINGS } from "../shared/strings";
import { useMyAccess } from "./hooks";
import { IDENTITY_STRINGS } from "./strings";
import type { AccessSource } from "./types";

const S = IDENTITY_STRINGS.myAccess;

/** Stable element id of the panel, so a forbidden state can link to it. */
export const MY_ACCESS_ID = "my-access";

const SOURCE_TONE: Record<AccessSource, StatusTone> = {
  entra_app_role: "info",
  entra_group: "info",
  policy_store: "neutral",
};

function Body(): ReactElement {
  const query = useMyAccess(null);
  if (query.isError) {
    return (
      <QueryErrorState
        error={query.error}
        onRetry={() => void query.refetch()}
        testIdPrefix="my-access-"
      />
    );
  }
  if (query.isPending) {
    return (
      <div aria-busy="true" data-testid="my-access-loading">
        <LoadingState label={S.loading} rows={2} />
      </div>
    );
  }
  const { roles, groups_overage: overage, mapping_configured: configured } = query.data;
  return (
    <>
      <p data-testid="my-access-mapping">
        {configured ? S.mappingConfigured : S.mappingNotConfigured}
      </p>
      {overage ? (
        <p role="note" data-testid="my-access-overage">
          {ADMIN_STRINGS.access.overage}
        </p>
      ) : null}
      {roles.length === 0 ? (
        <div data-testid="my-access-empty">
          <EmptyState title={S.empty} />
        </div>
      ) : (
        <DataTable
          label={S.tableLabel}
          rows={roles}
          getRowId={(row) =>
            `${row.role}|${row.source}|${row.mapping_entry_id ?? ""}|${row.expires_at ?? ""}`
          }
          getRowProps={() => ({ "data-testid": "my-access-row" })}
          columns={[
            { key: "role", header: S.headers.role, render: (row) => row.role },
            {
              key: "source",
              header: S.headers.source,
              render: (row) => (
                <StatusPill
                  label={ADMIN_STRINGS.access.sources[row.source]}
                  tone={SOURCE_TONE[row.source]}
                  testId="my-access-source"
                />
              ),
            },
            {
              key: "entry",
              header: S.headers.entry,
              render: (row) =>
                row.mapping_entry_id === null ? S.noEntry : <code>{row.mapping_entry_id}</code>,
            },
            { key: "domains", header: S.headers.domains, render: (row) => row.domain_count },
            {
              key: "scope",
              header: S.headers.scope,
              render: (row) =>
                row.customer_control ? (
                  <StatusPill label={S.wholeDeployment} tone="warning" testId="my-access-whole" />
                ) : (
                  S.domainsOnly
                ),
            },
            {
              key: "expires",
              header: S.headers.expires,
              render: (row) =>
                row.expires_at === null ? S.noExpiry : <Timestamp value={row.expires_at} />,
            },
          ]}
        />
      )}
    </>
  );
}

/** PRP-138: the caller's own roles, tagged Entra app role, Entra group or policy store. */
export function MyAccessPanel(): ReactElement {
  return (
    <div id={MY_ACCESS_ID}>
      <Panel title={S.title} landmark="region" testId="my-access-panel">
        <p>{S.description}</p>
        <Body />
      </Panel>
    </div>
  );
}
