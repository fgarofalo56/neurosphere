import { Button, makeStyles, tokens } from "@fluentui/react-components";
import { useState, type ReactElement } from "react";
import { Link } from "react-router";
import {
  DataTable,
  EmptyState,
  LoadingState,
  PageTemplate,
  StatusPill,
  Timestamp,
} from "../../design-system";
import { QueryErrorState, RegisterServerDialog } from "./components";
import { useMcpServers } from "./hooks";
import { mcpServerHref } from "./paths";
import { STRINGS } from "./strings";

const PAGE_SIZE = 25;

const useStyles = makeStyles({
  pager: {
    display: "flex",
    columnGap: tokens.spacingHorizontalS,
    marginTop: tokens.spacingVerticalS,
  },
});

function ListBody(): ReactElement {
  // Cursor history: the last entry is the current page; "" is the first page.
  const [cursors, setCursors] = useState<readonly string[]>([""]);
  const styles = useStyles();
  const cursor = cursors[cursors.length - 1] ?? "";
  const query = useMcpServers({ cursor, limit: PAGE_SIZE });

  if (query.isError)
    return <QueryErrorState error={query.error} onRetry={() => void query.refetch()} />;
  if (query.isPending) {
    return (
      <div aria-busy="true" data-testid="loading-state">
        <LoadingState label={STRINGS.loading} rows={5} />
      </div>
    );
  }
  const { items, next_cursor: next } = query.data;

  return (
    <>
      {items.length === 0 ? (
        <div data-testid="empty-state">
          <EmptyState title={STRINGS.empty} />
        </div>
      ) : (
        <DataTable
          label={STRINGS.listTitle}
          rows={items}
          getRowId={(server) => server.id}
          getRowProps={() => ({ "data-testid": "server-row" })}
          columns={[
            {
              key: "name",
              header: STRINGS.headers.name,
              render: (server) => <Link to={mcpServerHref(server.id)}>{server.display_name}</Link>,
            },
            { key: "url", header: STRINGS.headers.url, render: (server) => server.url },
            {
              key: "status",
              header: STRINGS.headers.status,
              render: (server) => (
                <StatusPill
                  label={STRINGS.status[server.status]}
                  tone={server.status === "active" ? "success" : "neutral"}
                />
              ),
            },
            {
              key: "tools",
              header: STRINGS.headers.tools,
              render: (server) =>
                STRINGS.toolsSummary(
                  server.pending_count,
                  server.approved_count,
                  server.revoked_count,
                ),
            },
            {
              key: "synced",
              header: STRINGS.headers.lastSynced,
              render: (server) =>
                server.last_synced_at === null ? (
                  STRINGS.neverSynced
                ) : (
                  <Timestamp value={server.last_synced_at} />
                ),
            },
          ]}
        />
      )}
      <div className={styles.pager}>
        {cursors.length > 1 ? (
          <Button onClick={() => setCursors([""])}>{STRINGS.firstPage}</Button>
        ) : null}
        {next !== null ? (
          <Button onClick={() => setCursors([...cursors, next])}>{STRINGS.nextPage}</Button>
        ) : null}
      </div>
    </>
  );
}

export function McpServersPage(): ReactElement {
  return (
    <PageTemplate
      title={STRINGS.listTitle}
      description={STRINGS.listDescription}
      actions={<RegisterServerDialog />}
    >
      <ListBody />
    </PageTemplate>
  );
}
