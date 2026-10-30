import type { ReactElement } from "react";
import { useSelectedDomain } from "../../app/domain";
import { DataTable, EmptyState, LoadingState, PageTemplate, Panel } from "../../design-system";
import { EmergencyBanner, QueryErrorState } from "../actions/components";
import { GrantPublishActions, McpPublishActions } from "./components";
import { useGrants, useMcpServerEntities } from "./hooks";
import { STRINGS } from "./strings";
import type { GrantEntity } from "./types";

function GrantsPanel({ domainId }: { readonly domainId: string }): ReactElement {
  const query = useGrants({ entityType: "grant" });
  const G = STRINGS.grants;
  return (
    <Panel title={G.title} testId="grants-panel">
      {query.isError ? (
        <QueryErrorState
          error={query.error}
          onRetry={() => {
            void query.refetch();
          }}
        />
      ) : query.isPending ? (
        <div aria-busy="true" data-testid="loading-state">
          <LoadingState label={STRINGS.loading} rows={3} />
        </div>
      ) : (
        <GrantsTable items={query.data.items.filter((g) => g.domain_id === domainId)} />
      )}
    </Panel>
  );
}

function GrantsTable({ items }: { readonly items: readonly GrantEntity[] }): ReactElement {
  const G = STRINGS.grants;
  if (items.length === 0) {
    return (
      <div data-testid="grants-empty">
        <EmptyState title={G.empty} />
      </div>
    );
  }
  return (
    <DataTable
      label={G.title}
      rows={items}
      getRowId={(g) => g.id}
      getRowProps={() => ({ "data-testid": "grant-row" })}
      columns={[
        {
          key: "principal",
          header: G.principal,
          render: (g) => g.principal.display ?? g.principal.object_id,
        },
        { key: "target", header: G.target, render: (g) => <code>{g.target.ref}</code> },
        { key: "state", header: G.state, render: (g) => g.lifecycle_status },
        { key: "actions", header: G.actions, render: (g) => <GrantPublishActions grant={g} /> },
      ]}
    />
  );
}

function McpPanel({ domainId }: { readonly domainId: string }): ReactElement {
  const query = useMcpServerEntities({ entityType: "mcp_server" });
  const M = STRINGS.mcp;
  return (
    <Panel title={M.title} testId="mcp-panel">
      {query.isError ? (
        <QueryErrorState
          error={query.error}
          onRetry={() => {
            void query.refetch();
          }}
        />
      ) : query.isPending ? (
        <div aria-busy="true" data-testid="loading-state">
          <LoadingState label={STRINGS.loading} rows={3} />
        </div>
      ) : query.data.items.filter((s) => s.domain_id === domainId).length === 0 ? (
        <div data-testid="mcp-empty">
          <EmptyState title={M.empty} />
        </div>
      ) : (
        <DataTable
          label={M.title}
          rows={query.data.items.filter((s) => s.domain_id === domainId)}
          getRowId={(s) => s.id}
          getRowProps={() => ({ "data-testid": "mcp-row" })}
          columns={[
            { key: "name", header: M.name, render: (s) => s.display_name },
            { key: "url", header: M.url, render: (s) => <code>{s.url}</code> },
            {
              key: "actions",
              header: M.actions,
              render: (s) => <McpPublishActions server={s} />,
            },
          ]}
        />
      )}
    </Panel>
  );
}

/** Grants and MCP servers of the selected domain with Publish and Unpublish (draft only). */
export function CatalogPublicationPage(): ReactElement {
  const { domainId } = useSelectedDomain();
  return (
    <PageTemplate title={STRINGS.title} description={STRINGS.description}>
      <EmergencyBanner />
      {domainId === "" ? (
        <div data-testid="domain-required">
          <EmptyState title={STRINGS.domainRequired} />
        </div>
      ) : (
        <>
          <GrantsPanel key={`g|${domainId}`} domainId={domainId} />
          <McpPanel key={`m|${domainId}`} domainId={domainId} />
        </>
      )}
    </PageTemplate>
  );
}
