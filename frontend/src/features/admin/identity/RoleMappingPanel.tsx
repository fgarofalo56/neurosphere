import type { ReactElement } from "react";
import { DataTable, EmptyState, LoadingState, Panel, StatusPill } from "../../../design-system";
import { QueryErrorState } from "../shared/AdminStates";
import { useRoleMapping } from "./hooks";
import { MY_ACCESS_ID } from "./MyAccessPanel";
import { IDENTITY_STRINGS } from "./strings";
import type { RoleMappingEntryView, RoleMappingView } from "./types";

const S = IDENTITY_STRINGS.mapping;

function domainsText(entry: RoleMappingEntryView): string {
  return entry.domain_mode === "all" ? S.allDomains : S.explicitDomains(entry.domain_ids.length);
}

function Binding({ view }: { readonly view: RoleMappingView }): ReactElement {
  return (
    <dl data-testid="role-mapping-binding">
      <dt>{S.status}</dt>
      <dd>
        {view.active ? (
          <StatusPill label={S.active} tone="success" testId="role-mapping-active" />
        ) : (
          <StatusPill label={S.inactive} tone="neutral" testId="role-mapping-active" />
        )}
      </dd>
      <dt>{S.tenant}</dt>
      <dd>
        <code>{view.tenant_id ?? S.notSet}</code>
      </dd>
      <dt>{S.audience}</dt>
      <dd>
        <code>{view.audience ?? S.notSet}</code>
      </dd>
      <dt>{S.cloud}</dt>
      <dd>{view.cloud ?? S.notSet}</dd>
    </dl>
  );
}

function Body(): ReactElement {
  const query = useRoleMapping(null);
  if (query.isError) {
    return (
      <QueryErrorState
        error={query.error}
        onRetry={() => void query.refetch()}
        accessAnchor={MY_ACCESS_ID}
        testIdPrefix="role-mapping-"
      />
    );
  }
  if (query.isPending) {
    return (
      <div aria-busy="true" data-testid="role-mapping-loading">
        <LoadingState label={S.loading} rows={2} />
      </div>
    );
  }
  const view = query.data;
  if (!view.active && view.entries.length === 0) {
    return (
      <div data-testid="role-mapping-empty">
        <EmptyState title={S.empty} description={S.emptyDetail} />
      </div>
    );
  }
  return (
    <>
      <Binding view={view} />
      <DataTable
        label={S.tableLabel}
        rows={view.entries}
        getRowId={(row) => row.id}
        getRowProps={() => ({ "data-testid": "role-mapping-row" })}
        columns={[
          { key: "id", header: S.headers.id, render: (row) => <code>{row.id}</code> },
          { key: "claim", header: S.headers.claim, render: (row) => S.claims[row.claim] },
          { key: "value", header: S.headers.value, render: (row) => <code>{row.value}</code> },
          { key: "role", header: S.headers.role, render: (row) => row.role },
          { key: "domains", header: S.headers.domains, render: (row) => domainsText(row) },
          {
            key: "control",
            header: S.headers.control,
            render: (row) => (row.customer_control ? S.yes : S.no),
          },
        ]}
      />
    </>
  );
}

/**
 * PRP-138 read-only view of the effective Entra role mapping. It has no input and no button that
 * changes anything: the mapping is deployment configuration.
 */
export function RoleMappingPanel(): ReactElement {
  return (
    <Panel title={S.title} landmark="region" testId="role-mapping-panel">
      <p>{S.description}</p>
      <Body />
      <p data-testid="role-mapping-assignment-note">{S.assignmentNote}</p>
      <p data-testid="role-mapping-principals-note">{S.principalsNote}</p>
    </Panel>
  );
}
