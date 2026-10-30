import {
  Button,
  Dialog,
  DialogActions,
  DialogBody,
  DialogContent,
  DialogSurface,
  DialogTitle,
  Field,
  Input,
  MessageBar,
  MessageBarBody,
  MessageBarTitle,
  Select,
  makeStyles,
  tokens,
} from "@fluentui/react-components";
import { useMemo, useState, type ReactElement } from "react";
import { Link } from "react-router";
import type { ApiError } from "../../api/index.js";
import { useSelectedDomain } from "../../app/domain";
import { StatusPill } from "../../design-system";
import { actionDetailHref } from "../gateways/GatewayModePanel";
import { useGateways } from "../gateways/hooks";
import { canPropose } from "../gateways/permissions";
import { gatewayRefusalText } from "../gateways/refusals";
import {
  useMcpPublicationStatus,
  usePublishGrant,
  usePublishMcpServer,
  useUnpublishGrant,
  useUnpublishMcpServer,
} from "./hooks";
import { STRINGS } from "./strings";
import type {
  ActionView,
  GrantEntity,
  McpPublicationStatus,
  McpServerEntity,
  McpStage,
} from "./types";

const useStyles = makeStyles({
  actions: {
    display: "flex",
    flexWrap: "wrap",
    alignItems: "center",
    columnGap: tokens.spacingHorizontalS,
    rowGap: tokens.spacingVerticalXS,
  },
  form: { display: "flex", flexDirection: "column", rowGap: tokens.spacingVerticalM },
});

function newKey(prefix: string): string {
  return `${prefix}-${crypto.randomUUID()}`;
}

function RefusalBar({ error }: { readonly error: ApiError }): ReactElement {
  const reason = error.problem?.reason;
  return (
    <MessageBar intent="error" role="alert" data-testid="publish-refusal">
      <MessageBarBody>
        <MessageBarTitle>{STRINGS.errorTitle}</MessageBarTitle>
        {gatewayRefusalText(error)}
        {reason !== undefined ? (
          <>
            {" "}
            (<code data-testid="publish-refusal-reason">{reason}</code>)
          </>
        ) : null}
      </MessageBarBody>
    </MessageBar>
  );
}

function DraftedBar({
  domainId,
  action,
  stage,
}: {
  readonly domainId: string;
  readonly action: ActionView;
  readonly stage?: McpStage | undefined;
}): ReactElement {
  return (
    <MessageBar intent="success" role="status" data-testid="publish-drafted">
      <MessageBarBody>
        <MessageBarTitle>{STRINGS.drafted}</MessageBarTitle>
        {STRINGS.draftedDetail}
        {stage !== undefined ? (
          <>
            {" "}
            {STRINGS.draftedStage}: <code data-testid="drafted-stage">{stage}</code>.
          </>
        ) : null}{" "}
        <Link to={actionDetailHref(domainId, action.intent.intent_id)}>{STRINGS.openApproval}</Link>
      </MessageBarBody>
    </MessageBar>
  );
}

interface PublishDialogProps {
  readonly kind: "grant" | "mcp";
  readonly domainId: string;
  readonly submitting: boolean;
  readonly error: ApiError | null;
  readonly onClose: () => void;
  readonly onSubmit: (values: {
    readonly gatewayId: string;
    readonly apiId: string;
    readonly access: "subscription" | "entra";
    readonly apiPath: string;
  }) => void;
}

/** Collects what a first publication needs; the server derives identity, target and the diff. */
function PublishDialog(props: PublishDialogProps): ReactElement {
  const { kind, domainId, submitting, error, onClose, onSubmit } = props;
  const styles = useStyles();
  const gateways = useGateways({ domainId });
  const [gatewayId, setGatewayId] = useState("");
  const [apiId, setApiId] = useState("");
  const [access, setAccess] = useState<"subscription" | "entra">("subscription");
  const [apiPath, setApiPath] = useState("");
  const D = STRINGS.dialog;
  const items = gateways.data?.items ?? [];
  const ready = gatewayId !== "" && (kind === "mcp" ? apiPath.trim() !== "" : apiId.trim() !== "");
  return (
    <Dialog
      open
      modalType="alert"
      onOpenChange={(_e, data) => {
        if (!data.open) onClose();
      }}
    >
      <DialogSurface data-testid="publish-dialog" aria-describedby="publish-dialog-body">
        <DialogBody>
          <DialogTitle>{kind === "grant" ? D.publishGrantTitle : D.publishMcpTitle}</DialogTitle>
          <DialogContent id="publish-dialog-body">
            <p>{D.help}</p>
            <form
              id="publish-form"
              className={styles.form}
              onSubmit={(e) => {
                e.preventDefault();
                if (ready)
                  onSubmit({ gatewayId, apiId: apiId.trim(), access, apiPath: apiPath.trim() });
              }}
            >
              <Field label={D.gateway} required>
                <Select
                  value={gatewayId}
                  onChange={(_e, data) => setGatewayId(data.value)}
                  aria-label={D.gateway}
                >
                  <option value="">
                    {items.length === 0 ? D.noGateways : D.gatewayPlaceholder}
                  </option>
                  {items.map((g) => (
                    <option key={g.id} value={g.id}>
                      {g.name} ({g.mode})
                    </option>
                  ))}
                </Select>
              </Field>
              {kind === "grant" ? (
                <>
                  <Field label={D.apiId} required>
                    <Input value={apiId} onChange={(_e, data) => setApiId(data.value)} />
                  </Field>
                  <Field label={D.access}>
                    <Select
                      value={access}
                      onChange={(_e, data) =>
                        setAccess(data.value === "entra" ? "entra" : "subscription")
                      }
                    >
                      <option value="subscription">{D.accessSubscription}</option>
                      <option value="entra">{D.accessEntra}</option>
                    </Select>
                  </Field>
                </>
              ) : (
                <Field label={D.apiPath} required>
                  <Input value={apiPath} onChange={(_e, data) => setApiPath(data.value)} />
                </Field>
              )}
            </form>
            {error !== null ? <RefusalBar error={error} /> : null}
          </DialogContent>
          <DialogActions>
            <Button
              appearance="primary"
              type="submit"
              form="publish-form"
              disabled={!ready || submitting}
            >
              {submitting ? STRINGS.working : D.submit}
            </Button>
            <Button appearance="secondary" onClick={onClose}>
              {D.cancel}
            </Button>
          </DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
}

/** Publish and Unpublish for one Grant: both only draft an action intent. */
export function GrantPublishActions({ grant }: { readonly grant: GrantEntity }): ReactElement {
  const styles = useStyles();
  const { domains } = useSelectedDomain();
  const allowed = canPropose(domains, grant.domain_id);
  const publish = usePublishGrant();
  const unpublish = useUnpublishGrant();
  const [open, setOpen] = useState(false);
  const [drafted, setDrafted] = useState<ActionView | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const publishKey = useMemo(() => newKey("button-grant-publish"), []);
  const unpublishKey = useMemo(() => newKey("button-grant-unpublish"), []);
  const busy = publish.isPending || unpublish.isPending;
  return (
    <div data-testid="grant-actions">
      <div className={styles.actions}>
        <Button
          size="small"
          disabled={!allowed || busy}
          onClick={() => {
            setError(null);
            setOpen(true);
          }}
        >
          {STRINGS.publish}
        </Button>
        <Button
          size="small"
          disabled={!allowed || busy}
          onClick={() => {
            setError(null);
            unpublish.mutate(
              {
                entityId: grant.id,
                request: { idempotency_key: unpublishKey, channel: "button" },
              },
              { onSuccess: setDrafted, onError: setError },
            );
          }}
        >
          {unpublish.isPending ? STRINGS.working : STRINGS.unpublish}
        </Button>
      </div>
      {!allowed ? <p data-testid="no-permission">{STRINGS.noPermission}</p> : null}
      {error !== null && !open ? <RefusalBar error={error} /> : null}
      {drafted !== null ? <DraftedBar domainId={grant.domain_id} action={drafted} /> : null}
      {open ? (
        <PublishDialog
          kind="grant"
          domainId={grant.domain_id}
          submitting={publish.isPending}
          error={error}
          onClose={() => setOpen(false)}
          onSubmit={(v) => {
            setError(null);
            publish.mutate(
              {
                entityId: grant.id,
                request: {
                  gateway_id: v.gatewayId,
                  api_id: v.apiId,
                  access: v.access,
                  idempotency_key: publishKey,
                  channel: "button",
                },
              },
              {
                onSuccess: (view) => {
                  setOpen(false);
                  setDrafted(view);
                },
                onError: setError,
              },
            );
          }}
        />
      ) : null}
    </div>
  );
}

function unpublishLabel(stage: McpStage | null): string {
  if (stage === "deny") return STRINGS.unpublishDeny;
  if (stage === "remove") return STRINGS.unpublishRemove;
  return STRINGS.unpublish;
}

function nextStepCopy(stage: McpStage | null): string {
  if (stage === "deny") return STRINGS.mcp.nextDeny;
  if (stage === "remove") return STRINGS.mcp.nextRemove;
  if (stage === "change") return STRINGS.mcp.nextChange;
  return STRINGS.mcp.nothingToUnpublish;
}

function McpStatusView({ status }: { readonly status: McpPublicationStatus }): ReactElement {
  return (
    <div data-testid="mcp-status">
      <StatusPill
        label={STRINGS.mcp.state_[status.state]}
        tone={
          status.state === "published"
            ? "success"
            : status.state === "denied"
              ? "warning"
              : "neutral"
        }
      />
      <p data-testid="mcp-next-unpublish">{nextStepCopy(status.next_unpublish_stage)}</p>
      {status.state !== "unpublished" ? (
        <p data-testid="mcp-two-step">{STRINGS.mcp.twoStep}</p>
      ) : null}
    </div>
  );
}

/**
 * Publish and Unpublish for one MCP server. Unpublish is a two-step flow (deny, then remove), so
 * the button names the step the backend says is next; a first publish also needs a gateway and an
 * API path, later stages reuse what the catalog recorded.
 */
export function McpPublishActions({ server }: { readonly server: McpServerEntity }): ReactElement {
  const styles = useStyles();
  const { domains } = useSelectedDomain();
  const allowed = canPropose(domains, server.domain_id);
  const status = useMcpPublicationStatus({ entityId: server.id });
  const publish = usePublishMcpServer();
  const unpublish = useUnpublishMcpServer();
  const [open, setOpen] = useState(false);
  const [drafted, setDrafted] = useState<{ action: ActionView; stage: McpStage } | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const state = status.data?.state ?? "unknown";
  const publishKey = useMemo(() => newKey("button-mcp-publish"), [state]);
  const unpublishKey = useMemo(() => newKey("button-mcp-unpublish"), [state]);
  const data = status.data;
  const busy = publish.isPending || unpublish.isPending;
  const canPublish =
    allowed && server.publishable && data !== undefined && data.next_publish_stage !== null;
  const canUnpublish = allowed && data !== undefined && data.next_unpublish_stage !== null;
  const onDrafted = (draft: { action: ActionView; stage: McpStage }): void => {
    setOpen(false);
    setDrafted({ action: draft.action, stage: draft.stage });
  };
  return (
    <div data-testid="mcp-actions">
      {status.isError ? (
        <p data-testid="mcp-status-unavailable">{STRINGS.mcp.statusUnavailable}</p>
      ) : data !== undefined ? (
        <McpStatusView status={data} />
      ) : null}
      <div className={styles.actions}>
        <Button
          size="small"
          disabled={!canPublish || busy}
          onClick={() => {
            setError(null);
            if (data?.gateway_id === null || data?.gateway_id === undefined) {
              setOpen(true);
              return;
            }
            publish.mutate(
              { entityId: server.id, request: { idempotency_key: publishKey, channel: "button" } },
              { onSuccess: onDrafted, onError: setError },
            );
          }}
        >
          {publish.isPending ? STRINGS.working : STRINGS.publish}
        </Button>
        <Button
          size="small"
          disabled={!canUnpublish || busy}
          onClick={() => {
            setError(null);
            unpublish.mutate(
              {
                entityId: server.id,
                request: { idempotency_key: unpublishKey, channel: "button" },
              },
              { onSuccess: onDrafted, onError: setError },
            );
          }}
        >
          {unpublish.isPending
            ? STRINGS.working
            : unpublishLabel(data?.next_unpublish_stage ?? null)}
        </Button>
      </div>
      {!server.publishable ? (
        <p data-testid="not-publishable">{STRINGS.mcp.notPublishable}</p>
      ) : null}
      {!allowed ? <p data-testid="no-permission">{STRINGS.noPermission}</p> : null}
      {error !== null && !open ? <RefusalBar error={error} /> : null}
      {drafted !== null ? (
        <DraftedBar domainId={server.domain_id} action={drafted.action} stage={drafted.stage} />
      ) : null}
      {open ? (
        <PublishDialog
          kind="mcp"
          domainId={server.domain_id}
          submitting={publish.isPending}
          error={error}
          onClose={() => setOpen(false)}
          onSubmit={(v) => {
            setError(null);
            publish.mutate(
              {
                entityId: server.id,
                request: {
                  gateway_id: v.gatewayId,
                  api_path: v.apiPath,
                  idempotency_key: publishKey,
                  channel: "button",
                },
              },
              { onSuccess: onDrafted, onError: setError },
            );
          }}
        />
      ) : null}
    </div>
  );
}
