import {
  Badge,
  Button,
  Dialog,
  DialogActions,
  DialogBody,
  DialogContent,
  DialogSurface,
  DialogTitle,
  MessageBar,
  MessageBarBody,
  MessageBarTitle,
} from "@fluentui/react-components";
import { useEffect, useState, type ReactElement } from "react";
import {
  CapabilityUnavailableError,
  DependencyTransientError,
  ForbiddenError,
  InvalidSchemaError,
  StaleVersionError,
  type ApiError,
} from "../../api/index.js";
import { useEmergencyDisable } from "./hooks";
import { STRINGS, orUnknown } from "./strings";
import type { ActionIntent, ActionState, ExecutionView, ProposedDiff } from "./types";

function referenceOf(error: ApiError): string {
  return error.correlationId !== "" ? ` (${STRINGS.errors.reference} ${error.correlationId})` : "";
}

/** Page-level read failure: 403 is an access message, anything else a retryable outage. */
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

/** Maps a failed action mutation to a precise message; nothing is ever assumed to have worked. */
export function actionErrorText(error: ApiError): string {
  const reason = error.problem?.reason;
  if (error instanceof StaleVersionError) {
    if (reason === "confirmation_expired") return STRINGS.errors.staleExpired;
    if (reason === "target_version_changed") return STRINGS.errors.staleVersion;
    return STRINGS.errors.staleOther;
  }
  if (error instanceof ForbiddenError) return STRINGS.errors.forbidden;
  if (error instanceof CapabilityUnavailableError) {
    if (reason === "advisory_connector") return STRINGS.errors.advisory;
    if (reason === "emergency_disabled") return STRINGS.errors.emergency;
    return STRINGS.errors.generic;
  }
  if (error instanceof InvalidSchemaError) {
    return reason === "confirmation_hash_mismatch"
      ? STRINGS.errors.hashMismatch
      : STRINGS.errors.invalid;
  }
  if (error instanceof DependencyTransientError) return STRINGS.errors.unavailable;
  return STRINGS.errors.generic;
}

export function ActionError({ error }: { readonly error: ApiError }): ReactElement {
  return (
    <MessageBar intent="error" role="alert" data-testid="action-error">
      <MessageBarBody>
        {actionErrorText(error)}
        {referenceOf(error)}
      </MessageBarBody>
    </MessageBar>
  );
}

export function EmergencyBanner(): ReactElement | null {
  const query = useEmergencyDisable({});
  if (!query.isSuccess || !query.data.disabled) return null;
  const d = query.data;
  return (
    <MessageBar intent="warning" role="status" data-testid="emergency-banner">
      <MessageBarBody>
        <MessageBarTitle>{STRINGS.emergency.title}</MessageBarTitle>
        {STRINGS.emergency.detail} {STRINGS.emergency.reason}: {orUnknown(d.reason)}.{" "}
        {STRINGS.emergency.changedBy}: {orUnknown(d.changed_by)}.
      </MessageBarBody>
    </MessageBar>
  );
}

export function StateBadge({ state }: { readonly state: ActionState }): ReactElement {
  const color =
    state === "succeeded"
      ? "success"
      : state === "failed" || state === "rolled_back" || state === "expired"
        ? "danger"
        : state === "executing" || state === "awaiting_approval"
          ? "warning"
          : "informative";
  return (
    <Badge appearance="tint" color={color} data-testid="state-badge">
      {state}
    </Badge>
  );
}

export function DiffView({ diff }: { readonly diff: ProposedDiff }): ReactElement {
  return (
    <ol aria-label={STRINGS.detail.diff} data-testid="diff">
      {diff.operations.map((op, index) => (
        // Patch order is significant, so the index is part of the identity.
        <li key={`${index}|${op.op}|${op.path}`} data-testid="diff-op">
          <code>{op.op}</code> <code>{op.path}</code>
          {op.from !== undefined ? (
            <>
              {" from "}
              <code>{op.from}</code>
            </>
          ) : null}
          {"value" in op ? (
            <>
              {" "}
              <code data-testid="diff-value">{JSON.stringify(op.value)}</code>
            </>
          ) : null}
        </li>
      ))}
    </ol>
  );
}

export function ExecutionPanel({
  execution,
}: {
  readonly execution: ExecutionView | null;
}): ReactElement {
  if (execution === null) return <p data-testid="execution-none">{STRINGS.detail.noExecution}</p>;
  const verify =
    execution.verify_matched === null
      ? STRINGS.unknown
      : execution.verify_matched
        ? STRINGS.detail.verifyMatched
        : STRINGS.detail.verifyMismatch;
  return (
    <dl data-testid="execution">
      <dt>{STRINGS.detail.phase}</dt>
      <dd data-testid="execution-phase">{execution.phase}</dd>
      <dt>{STRINGS.detail.canary}</dt>
      <dd data-testid="execution-canary">{orUnknown(execution.canary)}</dd>
      <dt>{STRINGS.detail.verify}</dt>
      <dd data-testid="execution-verify">{verify}</dd>
      <dt>{STRINGS.detail.rollback}</dt>
      <dd data-testid="execution-rollback">
        {execution.rolled_back ? STRINGS.detail.rolledBack : STRINGS.detail.notRolledBack}
      </dd>
    </dl>
  );
}

export function Prerequisites({ intent }: { readonly intent: ActionIntent }): ReactElement {
  if (intent.prerequisite_results.length === 0) {
    return <p data-testid="prerequisites-empty">{STRINGS.detail.noPrerequisites}</p>;
  }
  return (
    <ul aria-label={STRINGS.detail.prerequisites} data-testid="prerequisites">
      {intent.prerequisite_results.map((p) => (
        <li key={p.check_id} data-testid="prerequisite">
          <code>{p.check_id}</code>: {p.status}
          {p.detail !== null ? ` - ${p.detail}` : ""}
        </li>
      ))}
    </ul>
  );
}

export interface Countdown {
  /** Milliseconds left; null when no expiry is known. */
  readonly remainingMs: number | null;
  readonly expired: boolean;
}

/** Ticks once a second. An unparseable expiry counts as expired (fail closed). */
export function useCountdown(expiresAt: string | null): Countdown {
  const [now, setNow] = useState<number>(() => Date.now());
  useEffect(() => {
    setNow(Date.now());
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [expiresAt]);
  if (expiresAt === null) return { remainingMs: null, expired: true };
  const at = Date.parse(expiresAt);
  if (Number.isNaN(at)) return { remainingMs: null, expired: true };
  const remaining = at - now;
  return { remainingMs: Math.max(0, remaining), expired: remaining <= 0 };
}

export function formatRemaining(ms: number): string {
  const total = Math.ceil(ms / 1000);
  const minutes = Math.floor(total / 60);
  const seconds = total % 60;
  return `${String(minutes)}:${String(seconds).padStart(2, "0")}`;
}

export interface ConfirmationDialogProps {
  readonly intent: ActionIntent;
  readonly requiresApproval: boolean;
  readonly submitting: boolean;
  readonly error: ApiError | null;
  /** Receives the server-issued hash exactly as the intent carried it. */
  readonly onSubmit: (confirmationHash: string) => void;
  readonly onClose: () => void;
}

/**
 * Shows exactly what will run: the target canonical id, target_version, every patch operation
 * and the confirmation expiry with a live countdown. The submit control is disabled once the
 * confirmation expires. The countdown ticks silently (role=timer); only the expired/valid state
 * change is announced, through a polite live region.
 */
export function ConfirmationDialog(props: ConfirmationDialogProps): ReactElement {
  const { intent, requiresApproval, submitting, error, onSubmit, onClose } = props;
  const countdown = useCountdown(intent.confirmation_expires_at);
  const hash = intent.confirmation_hash;
  const canSubmit = !countdown.expired && hash !== null && !submitting;
  const C = STRINGS.confirm;
  return (
    <Dialog
      open
      modalType="alert"
      onOpenChange={(_event, data) => {
        if (!data.open) onClose();
      }}
    >
      <DialogSurface aria-describedby="confirm-body" data-testid="confirmation-dialog">
        <DialogBody>
          <DialogTitle>{C.title}</DialogTitle>
          <DialogContent id="confirm-body">
            <dl>
              <dt>{C.target}</dt>
              <dd data-testid="confirm-target">{intent.target.canonical_id}</dd>
              <dt>{C.version}</dt>
              <dd data-testid="confirm-version">{intent.target_version}</dd>
              <dt>{C.diff}</dt>
              <dd>
                <DiffView diff={intent.proposed_diff} />
              </dd>
              <dt>{C.expires}</dt>
              <dd data-testid="confirm-expiry">{orUnknown(intent.confirmation_expires_at)}</dd>
              <dt>{C.remaining}</dt>
              <dd>
                <span role="timer" data-testid="confirm-countdown">
                  {countdown.remainingMs === null ? "0:00" : formatRemaining(countdown.remainingMs)}
                </span>
              </dd>
            </dl>
            <div role="status" aria-live="polite" data-testid="confirm-status">
              {hash === null ? C.missingHash : countdown.expired ? C.expired : C.valid}
            </div>
            {error !== null ? <ActionError error={error} /> : null}
          </DialogContent>
          <DialogActions>
            <Button
              appearance="primary"
              disabled={!canSubmit}
              onClick={() => {
                if (hash !== null) onSubmit(hash);
              }}
            >
              {requiresApproval ? C.submitApproval : C.submit}
            </Button>
            <Button appearance="secondary" onClick={onClose}>
              {C.cancel}
            </Button>
          </DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
}
