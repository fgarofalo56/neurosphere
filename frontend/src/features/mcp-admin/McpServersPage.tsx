import { Button } from "@fluentui/react-components";
import { useState, type ReactElement } from "react";
import { Link } from "react-router";
import { PageTemplate } from "../../design-system";
import { QueryErrorState, RegisterServerDialog } from "./components";
import { useMcpServers } from "./hooks";
import { mcpServerHref } from "./paths";
import { STRINGS } from "./strings";

const PAGE_SIZE = 25;

function ListBody(): ReactElement {
  // Cursor history: the last entry is the current page; "" is the first page.
  const [cursors, setCursors] = useState<readonly string[]>([""]);
  const cursor = cursors[cursors.length - 1] ?? "";
  const query = useMcpServers({ cursor, limit: PAGE_SIZE });

  if (query.isError)
    return <QueryErrorState error={query.error} onRetry={() => void query.refetch()} />;
  if (query.isPending) return <p aria-busy="true">{STRINGS.loading}</p>;
  const { items, next_cursor: next } = query.data;

  return (
    <>
      {items.length === 0 ? (
        <p data-testid="empty-state">{STRINGS.empty}</p>
      ) : (
        <table aria-label={STRINGS.listTitle}>
          <thead>
            <tr>
              <th scope="col">{STRINGS.headers.name}</th>
              <th scope="col">{STRINGS.headers.url}</th>
              <th scope="col">{STRINGS.headers.status}</th>
              <th scope="col">{STRINGS.headers.tools}</th>
              <th scope="col">{STRINGS.headers.lastSynced}</th>
            </tr>
          </thead>
          <tbody>
            {items.map((server) => (
              <tr key={server.id} data-testid="server-row">
                <td>
                  <Link to={mcpServerHref(server.id)}>{server.display_name}</Link>
                </td>
                <td>{server.url}</td>
                <td>{STRINGS.status[server.status]}</td>
                <td>
                  {STRINGS.toolsSummary(
                    server.pending_count,
                    server.approved_count,
                    server.revoked_count,
                  )}
                </td>
                <td>{server.last_synced_at ?? STRINGS.neverSynced}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <p>
        {cursors.length > 1 ? (
          <Button onClick={() => setCursors([""])}>{STRINGS.firstPage}</Button>
        ) : null}{" "}
        {next !== null ? (
          <Button onClick={() => setCursors([...cursors, next])}>{STRINGS.nextPage}</Button>
        ) : null}
      </p>
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
