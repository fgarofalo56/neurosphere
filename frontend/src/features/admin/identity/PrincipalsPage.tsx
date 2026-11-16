import { useState, type ReactElement } from "react";
import { Link } from "react-router";
import {
  DataTable,
  EmptyState,
  LoadingState,
  PageTemplate,
  StatusPill,
} from "../../../design-system";
import { principalHref } from "../shared/adminPaths";
import { AdminTabs } from "../shared/AdminTabs";
import { CopyableId, CursorPager, QueryErrorState } from "../shared/AdminStates";
import { usePrincipals } from "./hooks";
import { IDENTITY_STRINGS as S } from "./strings";

const PAGE_SIZE = 25;

function ListBody(): ReactElement {
  // Cursor history: the last entry is the current page; "" is the first page.
  const [cursors, setCursors] = useState<readonly string[]>([""]);
  const cursor = cursors[cursors.length - 1] ?? "";
  const query = usePrincipals({ cursor, limit: PAGE_SIZE });

  if (query.isError) {
    return <QueryErrorState error={query.error} onRetry={() => void query.refetch()} />;
  }
  if (query.isPending) {
    return (
      <div aria-busy="true" data-testid="loading-state">
        <LoadingState label={S.loading} rows={5} />
      </div>
    );
  }
  const { items, next_cursor: next, truncated } = query.data;
  return (
    <>
      {truncated ? <p data-testid="truncated-notice">{S.truncated}</p> : null}
      {items.length === 0 ? (
        <div data-testid="empty-state">
          <EmptyState title={S.empty} />
        </div>
      ) : (
        <DataTable
          label={S.listTitle}
          rows={items}
          getRowId={(row) => row.principal.principal_id}
          getRowProps={() => ({ "data-testid": "principal-row" })}
          columns={[
            {
              key: "principal",
              header: S.headers.principal,
              render: (row) => (
                <span>
                  <Link to={principalHref(row.principal.principal_id)}>
                    {row.principal.principal_id}
                  </Link>{" "}
                  <CopyableId value={row.principal.principal_id} label="principal id" />
                </span>
              ),
            },
            { key: "kind", header: S.headers.kind, render: (row) => row.principal.principal_kind },
            { key: "roles", header: S.headers.roles, render: (row) => row.assignments.length },
            {
              key: "memberships",
              header: S.headers.memberships,
              render: (row) => row.memberships.length,
            },
            { key: "grants", header: S.headers.grants, render: (row) => row.grants.length },
            {
              key: "state",
              header: S.headers.state,
              render: (row) =>
                row.revocation.revoked ? (
                  <StatusPill label={S.revoked} tone="danger" />
                ) : (
                  <StatusPill label={S.active} tone="success" />
                ),
            },
          ]}
        />
      )}
      <CursorPager
        canGoFirst={cursors.length > 1}
        next={next}
        onFirst={() => setCursors([""])}
        onNext={(c) => setCursors([...cursors, c])}
      />
    </>
  );
}

export function PrincipalsPage(): ReactElement {
  return (
    <PageTemplate title={S.listTitle} description={S.listDescription}>
      <AdminTabs />
      <ListBody />
    </PageTemplate>
  );
}
