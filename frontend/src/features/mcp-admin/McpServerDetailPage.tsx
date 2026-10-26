import { Button, makeStyles, tokens } from "@fluentui/react-components";
import { type ReactElement } from "react";
import { Link, useSearchParams } from "react-router";
import { EmptyState, LoadingState, PageTemplate, StatusPill, Timestamp } from "../../design-system";
import { Panel } from "../workspaces/Panel";
import { RowTable } from "../workspaces/RowTable";
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

const useStyles = makeStyles({
  stack: { display: "flex", flexDirection: "column", rowGap: tokens.spacingVerticalM },
  buttons: { display: "flex", flexWrap: "wrap", columnGap: tokens.spacingHorizontalS },
});

function ToolsTable({
  serverId,
  tools,
}: {
  readonly serverId: string;
  readonly tools: ToolList;
}): ReactElement {
  if (tools.items.length === 0) {
    return (
      <div data-testid="no-tools">
        <EmptyState title={STRINGS.noTools} />
      </div>
    );
  }
  return (
    <RowTable
      label={STRINGS.headers.tool}
      rows={tools.items}
      getRowId={(tool) => tool.name}
      rowTestId="tool-row"
      rowAttrs={(tool) => ({ "data-tool": tool.name })}
      columns={[
        { key: "tool", header: STRINGS.headers.tool, render: (tool) => tool.name },
        {
          key: "state",
          header: STRINGS.headers.state,
          render: (tool) => <ToolStateBadge state={tool.state} />,
        },
        {
          key: "enabled",
          header: STRINGS.headers.enabled,
          render: (tool) => (
            <span data-testid="tool-enabled">
              {tool.enabled ? STRINGS.enabledYes : STRINGS.enabledNo}
            </span>
          ),
        },
        {
          key: "hash",
          header: STRINGS.headers.hash,
          render: (tool) => <code>{tool.current_hash.slice(0, 19)}</code>,
        },
        {
          key: "actions",
          header: STRINGS.headers.actions,
          render: (tool) =>
            tool.state === "removed" ? null : tool.state !== "approved" ? (
              <ToolReviewDialog serverId={serverId} etag={tools.etag} tool={tool} />
            ) : (
              <RevokeToolDialog serverId={serverId} etag={tools.etag} tool={tool} />
            ),
        },
      ]}
    />
  );
}

function ServerActions({
  server,
  etag,
}: {
  readonly server: ServerView;
  readonly etag: string | null;
}): ReactElement {
  const styles = useStyles();
  const invalidate = useInvalidateMcpAdmin();
  const sync = useSyncServer();
  const update = useUpdateServer();
  const error = sync.error ?? update.error;
  return (
    <>
      <div className={styles.buttons}>
        <Button
          appearance="primary"
          data-testid="sync-server"
          disabled={sync.isPending}
          onClick={() =>
            sync.mutate({ serverId: server.id }, { onSuccess: () => void invalidate() })
          }
        >
          {STRINGS.sync.action}
        </Button>
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
      </div>
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
  const styles = useStyles();
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
  if (serverData === undefined || toolData === undefined) {
    return (
      <div aria-busy="true" data-testid="loading-state">
        <LoadingState label={STRINGS.loading} rows={5} />
      </div>
    );
  }
  return (
    <div className={styles.stack}>
      <Panel compact title={serverData.display_name}>
        <dl>
          <dt>{STRINGS.headers.url}</dt>
          <dd data-testid="server-url">{serverData.url}</dd>
          <dt>{STRINGS.headers.status}</dt>
          <dd data-testid="server-status">
            <StatusPill
              label={STRINGS.status[serverData.status]}
              tone={serverData.status === "active" ? "success" : "neutral"}
            />
          </dd>
          <dt>{STRINGS.headers.lastSynced}</dt>
          <dd>
            {serverData.last_synced_at === null ? (
              STRINGS.neverSynced
            ) : (
              <Timestamp value={serverData.last_synced_at} />
            )}
          </dd>
        </dl>
        <ServerActions server={serverData} etag={toolData.etag} />
      </Panel>
      <Panel title={STRINGS.toolsTitle}>
        <ToolsTable serverId={serverId} tools={toolData} />
      </Panel>
    </div>
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
        <div data-testid="server-required">
          <EmptyState title={STRINGS.serverIdRequired} />
        </div>
      ) : (
        <DetailBody key={serverId} serverId={serverId} />
      )}
    </PageTemplate>
  );
}
