import {
  Badge,
  Button,
  Checkbox,
  Dialog,
  DialogActions,
  DialogBody,
  DialogContent,
  DialogSurface,
  DialogTitle,
  DialogTrigger,
  Field,
  Input,
  MessageBar,
  MessageBarBody,
  MessageBarTitle,
  makeStyles,
  tokens,
} from "@fluentui/react-components";
import { useState, type ReactElement } from "react";
import {
  DependencyTransientError,
  ForbiddenError,
  InvalidSchemaError,
  StaleVersionError,
  type ApiError,
} from "../../api/index.js";
import { useApproveTool, useInvalidateMcpAdmin, useRegisterServer, useRevokeTool } from "./hooks";
import { STRINGS } from "./strings";
import type { ToolChangeView, ToolEntryView, ToolState, ToolView } from "./types";

function referenceOf(error: ApiError): string {
  return error.correlationId !== "" ? ` (${STRINGS.errors.reference} ${error.correlationId})` : "";
}

/**
 * Page-level read failure. 403 is an access-denied state (the API decided, not the nav), anything
 * else a retryable outage. Never rendered as an empty list.
 */
export function QueryErrorState({
  error,
  onRetry,
}: {
  readonly error: ApiError;
  readonly onRetry?: (() => void) | undefined;
}): ReactElement {
  const ref = referenceOf(error);
  if (error instanceof ForbiddenError) {
    return (
      <MessageBar intent="warning" role="alert" data-testid="forbidden-state">
        <MessageBarBody>
          <MessageBarTitle>{STRINGS.forbidden}</MessageBarTitle>
          {STRINGS.forbiddenDetail}
          {ref}.
        </MessageBarBody>
      </MessageBar>
    );
  }
  return (
    <MessageBar intent="error" role="alert" data-testid="unavailable-state">
      <MessageBarBody>
        <MessageBarTitle>{STRINGS.unavailable}</MessageBarTitle>
        {STRINGS.unavailableDetail}
        {ref}
        {onRetry !== undefined ? (
          <>
            {" "}
            <Button size="small" onClick={onRetry}>
              {STRINGS.retry}
            </Button>
          </>
        ) : null}
      </MessageBarBody>
    </MessageBar>
  );
}

/** Maps a failed mutation to a precise message; nothing is ever assumed to have worked. */
export function mutationErrorText(error: ApiError): string {
  if (error instanceof ForbiddenError) return STRINGS.errors.forbidden;
  if (error instanceof StaleVersionError) return STRINGS.errors.stale;
  if (error instanceof InvalidSchemaError) return STRINGS.errors.invalid;
  if (error instanceof DependencyTransientError) return STRINGS.errors.unavailable;
  return STRINGS.errors.generic;
}

export function MutationError({ error }: { readonly error: ApiError }): ReactElement {
  return (
    <MessageBar intent="error" role="alert" data-testid="mutation-error">
      <MessageBarBody>
        {mutationErrorText(error)}
        {referenceOf(error)}
      </MessageBarBody>
    </MessageBar>
  );
}

export function ToolStateBadge({ state }: { readonly state: ToolState }): ReactElement {
  const color =
    state === "approved"
      ? "success"
      : state === "revoked"
        ? "danger"
        : state === "pending"
          ? "warning"
          : "informative";
  return (
    <Badge appearance="tint" color={color} data-testid="tool-state">
      {STRINGS.toolState[state]}
    </Badge>
  );
}

const useStyles = makeStyles({
  pre: {
    margin: 0,
    padding: tokens.spacingVerticalS,
    overflow: "auto",
    maxHeight: "16rem",
    backgroundColor: tokens.colorNeutralBackground3,
    whiteSpace: "pre-wrap",
    overflowWrap: "anywhere",
  },
  columns: {
    display: "grid",
    gridTemplateColumns: "1fr 1fr",
    columnGap: tokens.spacingHorizontalM,
  },
  section: { marginBottom: tokens.spacingVerticalM },
});

function schemaText(schema: Readonly<Record<string, unknown>> | null): string {
  return schema === null ? STRINGS.review.noOutput : JSON.stringify(schema, null, 2);
}

function DiffRow({
  label,
  changed,
  before,
  after,
  testId,
}: {
  readonly label: string;
  readonly changed: boolean;
  readonly before: string;
  readonly after: string;
  readonly testId: string;
}): ReactElement {
  const styles = useStyles();
  return (
    <section
      aria-label={label}
      className={styles.section}
      data-testid={testId}
      data-changed={String(changed)}
    >
      <h4>
        {label}{" "}
        <Badge color={changed ? "danger" : "informative"} appearance="outline">
          {changed ? STRINGS.review.changed : STRINGS.review.unchanged}
        </Badge>
      </h4>
      <div className={styles.columns}>
        <div>
          <strong>{STRINGS.review.before}</strong>
          <pre className={styles.pre} data-testid={`${testId}-before`}>
            {before}
          </pre>
        </div>
        <div>
          <strong>{STRINGS.review.after}</strong>
          <pre className={styles.pre} data-testid={`${testId}-after`}>
            {after}
          </pre>
        </div>
      </div>
    </section>
  );
}

/** Before/after of everything a person or a model reads, shown before re-approval. */
export function ChangeDiff({ change }: { readonly change: ToolChangeView }): ReactElement {
  return (
    <section aria-label={STRINGS.review.changeTitle} data-testid="tool-diff">
      <h3>{STRINGS.review.changeTitle}</h3>
      <p>{STRINGS.review.changeHelp}</p>
      <DiffRow
        label={STRINGS.review.descriptionLabel}
        changed={change.description_changed}
        before={change.before.description}
        after={change.after.description}
        testId="diff-description"
      />
      <DiffRow
        label={STRINGS.review.inputLabel}
        changed={change.input_schema_changed}
        before={schemaText(change.before.input_schema)}
        after={schemaText(change.after.input_schema)}
        testId="diff-input"
      />
      <DiffRow
        label={STRINGS.review.outputLabel}
        changed={change.output_schema_changed}
        before={schemaText(change.before.output_schema)}
        after={schemaText(change.after.output_schema)}
        testId="diff-output"
      />
    </section>
  );
}

function EntryDetails({ entry }: { readonly entry: ToolEntryView }): ReactElement {
  const styles = useStyles();
  return (
    <section aria-label={STRINGS.review.title(entry.name)} data-testid="tool-entry">
      <h4>{STRINGS.review.descriptionLabel}</h4>
      <p data-testid="entry-description">{entry.description}</p>
      <h4>{STRINGS.review.inputLabel}</h4>
      <pre className={styles.pre}>{schemaText(entry.input_schema)}</pre>
      <h4>{STRINGS.review.outputLabel}</h4>
      <pre className={styles.pre}>{schemaText(entry.output_schema)}</pre>
    </section>
  );
}

// ----------------------------------------------------------------------------- approve

/**
 * Review and approve one tool. The approval request carries the hash shown here
 * (`expected_hash`), so the administrator approves exactly what they saw. For a tool revoked
 * because its content changed, the diff is shown and the approve button stays disabled until the
 * reviewer acknowledges it.
 */
export function ToolReviewDialog({
  serverId,
  etag,
  tool,
}: {
  readonly serverId: string;
  readonly etag: string | null;
  readonly tool: ToolView;
}): ReactElement {
  const [open, setOpen] = useState(false);
  const [acknowledged, setAcknowledged] = useState(false);
  const invalidate = useInvalidateMcpAdmin();
  const approve = useApproveTool();
  const needsAcknowledgement = tool.change !== null;
  const canApprove = etag !== null && (!needsAcknowledgement || acknowledged) && !approve.isPending;

  return (
    <Dialog
      open={open}
      onOpenChange={(_e, data) => {
        setOpen(data.open);
        if (!data.open) {
          setAcknowledged(false);
          approve.reset();
        }
      }}
    >
      <DialogTrigger disableButtonEnhancement>
        <Button size="small" data-testid="review-open" aria-label={STRINGS.review.open(tool.name)}>
          {STRINGS.review.open(tool.name)}
        </Button>
      </DialogTrigger>
      <DialogSurface>
        <DialogBody>
          <DialogTitle>{STRINGS.review.title(tool.name)}</DialogTitle>
          <DialogContent>
            {tool.change !== null ? <ChangeDiff change={tool.change} /> : null}
            {tool.change === null ? <EntryDetails entry={tool.entry} /> : null}
            <p>{STRINGS.review.approvingHelp}</p>
            <p>
              {STRINGS.review.hashLabel}: <code data-testid="review-hash">{tool.current_hash}</code>
            </p>
            {needsAcknowledgement ? (
              <Checkbox
                label={STRINGS.review.acknowledge}
                checked={acknowledged}
                onChange={(_e, data) => setAcknowledged(data.checked === true)}
                data-testid="ack-diff"
              />
            ) : null}
            {approve.isError ? <MutationError error={approve.error} /> : null}
          </DialogContent>
          <DialogActions>
            <Button
              appearance="primary"
              disabled={!canApprove}
              data-testid="approve-tool"
              onClick={() => {
                if (etag === null) return;
                approve.mutate(
                  { serverId, toolName: tool.name, expectedHash: tool.current_hash, etag },
                  {
                    onSuccess: () => {
                      void invalidate();
                      setOpen(false);
                      setAcknowledged(false);
                    },
                  },
                );
              }}
            >
              {STRINGS.review.approve}
            </Button>
            <DialogTrigger disableButtonEnhancement>
              <Button>{STRINGS.review.close}</Button>
            </DialogTrigger>
          </DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
}

// ----------------------------------------------------------------------------- revoke

export function RevokeToolDialog({
  serverId,
  etag,
  tool,
}: {
  readonly serverId: string;
  readonly etag: string | null;
  readonly tool: ToolView;
}): ReactElement {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState<string>(STRINGS.revoke.defaultReason);
  const invalidate = useInvalidateMcpAdmin();
  const revoke = useRevokeTool();
  const trimmed = reason.trim();
  const canSubmit = etag !== null && trimmed !== "" && trimmed.length <= 200 && !revoke.isPending;

  return (
    <Dialog open={open} onOpenChange={(_e, data) => setOpen(data.open)}>
      <DialogTrigger disableButtonEnhancement>
        <Button size="small" data-testid="revoke-open" aria-label={STRINGS.revoke.open(tool.name)}>
          {STRINGS.revoke.open(tool.name)}
        </Button>
      </DialogTrigger>
      <DialogSurface>
        <DialogBody>
          <DialogTitle>{STRINGS.revoke.title(tool.name)}</DialogTitle>
          <DialogContent>
            <form
              aria-label={STRINGS.revoke.title(tool.name)}
              onSubmit={(e) => {
                e.preventDefault();
                if (!canSubmit || etag === null) return;
                revoke.mutate(
                  { serverId, toolName: tool.name, etag, reason: trimmed },
                  {
                    onSuccess: () => {
                      void invalidate();
                      setOpen(false);
                    },
                  },
                );
              }}
            >
              <Field label={STRINGS.revoke.reasonLabel}>
                <Input value={reason} onChange={(_e, data) => setReason(data.value)} />
              </Field>
              {revoke.isError ? <MutationError error={revoke.error} /> : null}
              <DialogActions>
                <Button type="submit" appearance="primary" disabled={!canSubmit}>
                  {STRINGS.revoke.submit}
                </Button>
                <DialogTrigger disableButtonEnhancement>
                  <Button>{STRINGS.revoke.cancel}</Button>
                </DialogTrigger>
              </DialogActions>
            </form>
          </DialogContent>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
}

// ----------------------------------------------------------------------------- register

export function RegisterServerDialog(): ReactElement {
  const [open, setOpen] = useState(false);
  const [url, setUrl] = useState("");
  const [name, setName] = useState("");
  const invalidate = useInvalidateMcpAdmin();
  const register = useRegisterServer();
  const canSubmit = url.trim() !== "" && name.trim() !== "" && !register.isPending;

  return (
    <Dialog open={open} onOpenChange={(_e, data) => setOpen(data.open)}>
      <DialogTrigger disableButtonEnhancement>
        <Button appearance="primary" data-testid="register-open">
          {STRINGS.register.open}
        </Button>
      </DialogTrigger>
      <DialogSurface>
        <DialogBody>
          <DialogTitle>{STRINGS.register.title}</DialogTitle>
          <DialogContent>
            <p>{STRINGS.register.help}</p>
            <form
              aria-label={STRINGS.register.title}
              onSubmit={(e) => {
                e.preventDefault();
                if (!canSubmit) return;
                register.mutate(
                  { url: url.trim(), displayName: name.trim() },
                  {
                    onSuccess: () => {
                      void invalidate();
                      setUrl("");
                      setName("");
                      setOpen(false);
                    },
                  },
                );
              }}
            >
              <Field label={STRINGS.register.urlLabel} required>
                <Input
                  type="url"
                  value={url}
                  onChange={(_e, data) => setUrl(data.value)}
                  autoComplete="off"
                />
              </Field>
              <Field label={STRINGS.register.nameLabel} required>
                <Input value={name} onChange={(_e, data) => setName(data.value)} />
              </Field>
              {register.isError ? <MutationError error={register.error} /> : null}
              <DialogActions>
                <Button type="submit" appearance="primary" disabled={!canSubmit}>
                  {STRINGS.register.submit}
                </Button>
                <DialogTrigger disableButtonEnhancement>
                  <Button>{STRINGS.register.cancel}</Button>
                </DialogTrigger>
              </DialogActions>
            </form>
          </DialogContent>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
}
