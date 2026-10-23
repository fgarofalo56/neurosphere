import { Button } from "@fluentui/react-components";
import { type ReactElement } from "react";
import { Link, useSearchParams } from "react-router";
import { PageTemplate } from "../../design-system";
import {
  MutationError,
  QueryErrorState,
  RevokeToolDialog,
  ToolReviewDialog,
  ToolStateBadge,
} from "./components";
import {
  useInvalidateMcpAdmin,
  useMcpServer,
  useMcpTools,
  useSyncServer,
  useUpdateServer,
} from "./hooks";
import { MCP_ADMIN_LIST_ROUTE } from "./paths";
import { STRINGS } from "./strings";
import type { ServerView, ToolList } from "./types";

function ToolsTable({
  serverId,
  tools,
}: {
  readonly serverId: string;
  readonly tools: ToolList;
}): ReactElement {
  if (tools.items.length === 0) return <p data-testid="no-tools">{STRINGS.noTools}</p>;
  return (
    <table aria-label={STRINGS.headers.tool}>
      <thead>
        <tr>
          <th scope="col">{STRINGS.headers.tool}</th>
          <th scope="col">{STRINGS.headers.state}</th>
          <th scope="col">{STRINGS.headers.enabled}</th>
          <th scope="col">{STRINGS.headers.hash}</th>
          <th scope="col">{STRINGS.headers.actions}</th>
        </tr>
      </thead>
      <tbody>
        {tools.items.map((tool) => (
          <tr key={tool.name} data-testid="tool-row" data-tool={tool.name}>
            <td>{tool.name}</td>
            <td>
              <ToolStateBadge state={tool.state} />
            </td>
            <td data-testid="tool-enabled">
              {tool.enabled ? STRINGS.enabledYes : STRINGS.enabledNo}
            </td>
            <td>
              <code>{tool.current_hash.slice(0, 19)}</code>
            </td>
            <td>
              {tool.state === "removed" ? null : (
                <>
                  {tool.state !== "approved" ? (
                    <ToolReviewDialog serverId={serverId} etag={tools.etag} tool={tool} />
                  ) : (
                    <RevokeToolDialog serverId={serverId} etag={tools.etag} tool={tool} />
                  )}
                </>
              )}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function ServerActions({
  server,
  etag,
}: {
  readonly server: ServerView;
  readonly etag: string | null;
}): ReactElement {
  const invalidate = useInvalidateMcpAdmin();
  const sync = useSyncServer();
  const update = useUpdateServer();
  const error = sync.error ?? update.error;
  return (
    <>
      <p>
        <Button
          appearance="primary"
          data-testid="sync-server"
          disabled={sync.isPending}
          onClick={() =>
            sync.mutate({ serverId: server.id }, { onSuccess: () => void invalidate() })
          }
        >
          {STRINGS.sync.action}
        </Button>{" "}
        <Button
          data-testid="toggle-server"
          disabled={etag === null || update.isPending}
          onClick={() => {
            if (etag === null) return;
            update.mutate(
              {
                serverId: server.id,
                etag,
                status: server.status === "active" ? "disabled" : "active",
              },
              { onSuccess: () => void invalidate() },
            );
          }}
        >
          {server.status === "active" ? STRINGS.toggle.disable : STRINGS.toggle.enable}
        </Button>
      </p>
      {sync.isSuccess ? (
        <p role="status" data-testid="sync-result">
          {STRINGS.sync.done(
            sync.data.added.length,
            sync.data.revoked.length,
            sync.data.removed.length,
          )}
        </p>
      ) : null}
      {error !== null ? <MutationError error={error} /> : null}
    </>
  );
}

function DetailBody({ serverId }: { readonly serverId: string }): ReactElement {
  const server = useMcpServer({ serverId });
  const tools = useMcpTools({ serverId });
  const failure = server.error ?? tools.error;
  if (failure !== null)
    return (
      <QueryErrorState
        error={failure}
        onRetry={() => {
          void server.refetch();
          void tools.refetch();
        }}
      />
    );
  const serverData = server.data;
  const toolData = tools.data;
  if (serverData === undefined || toolData === undefined)
    return <p aria-busy="true">{STRINGS.loading}</p>;
  return (
    <>
      <dl>
        <dt>{STRINGS.headers.url}</dt>
        <dd data-testid="server-url">{serverData.url}</dd>
        <dt>{STRINGS.headers.status}</dt>
        <dd data-testid="server-status">{STRINGS.status[serverData.status]}</dd>
        <dt>{STRINGS.headers.lastSynced}</dt>
        <dd>{serverData.last_synced_at ?? STRINGS.neverSynced}</dd>
      </dl>
      <ServerActions server={serverData} etag={toolData.etag} />
      <ToolsTable serverId={serverId} tools={toolData} />
    </>
  );
}

export function McpServerDetailPage(): ReactElement {
  const [params] = useSearchParams();
  const serverId = params.get("server_id") ?? "";
  return (
    <PageTemplate
      title={STRINGS.detailTitle}
      actions={<Link to={`/${MCP_ADMIN_LIST_ROUTE}`}>{STRINGS.backToList}</Link>}
    >
      {serverId === "" ? (
        <p data-testid="server-required">{STRINGS.serverIdRequired}</p>
      ) : (
        <DetailBody key={serverId} serverId={serverId} />
      )}
    </PageTemplate>
  );
}
