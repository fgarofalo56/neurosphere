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
  Textarea,
} from "@fluentui/react-components";
import { useEffect, useState, type ReactElement, type ReactNode, type RefObject } from "react";
import { STRINGS } from "./strings";

/** One changed field in the before/after diff. Values are shown exactly as supplied. */
export interface ChangeDiffRow {
  readonly field: string;
  readonly before: string;
  readonly after: string;
}

export interface ChangeConfirmSubmit {
  /** Trimmed, non-empty. */
  readonly reason: string;
  /** Value of the expiry control, or null when it is hidden or left empty. */
  readonly expiry: string | null;
}

export interface ChangeConfirmDialogProps {
  readonly open: boolean;
  /** Dialog heading, for example "Deprecate entity". */
  readonly title?: string;
  /** Exact target (canonical id or edge id). */
  readonly target: string;
  /** Version or ETag the change is bound to (If-Match / expected version). */
  readonly version: string;
  readonly diff: readonly ChangeDiffRow[];
  /** Show the expiry control (lock / override). */
  readonly showExpiry?: boolean;
  /** Make the expiry mandatory when it is shown. */
  readonly expiryRequired?: boolean;
  readonly submitting?: boolean;
  /** Static caveat shown under the reason field, e.g. when the endpoint does not store it. */
  readonly reasonNote?: ReactNode;
  /** Server error to show inside the dialog (409 stale, 403, 422). */
  readonly error?: ReactNode;
  /** Receives focus when the dialog closes. Fluent also restores focus to the opener. */
  readonly triggerRef?: RefObject<HTMLElement | null>;
  readonly onSubmit: (value: ChangeConfirmSubmit) => void;
  readonly onClose: () => void;
}

/**
 * Shared confirmation for governed changes: shows the exact target, the version it is bound to
 * and a before/after diff, and requires a reason before the submit control is enabled. It only
 * collects the confirmation; the caller sends the request and the server decides.
 */
export function ChangeConfirmDialog(props: ChangeConfirmDialogProps): ReactElement {
  const {
    open,
    title = STRINGS.title,
    target,
    version,
    diff,
    showExpiry = false,
    expiryRequired = false,
    submitting = false,
    reasonNote,
    error,
    triggerRef,
    onSubmit,
    onClose,
  } = props;
  const [reason, setReason] = useState("");
  const [expiry, setExpiry] = useState("");

  useEffect(() => {
    if (open) {
      setReason("");
      setExpiry("");
    }
  }, [open]);

  const trimmed = reason.trim();
  const expiryOk = !(showExpiry && expiryRequired) || expiry !== "";
  const canSubmit = trimmed !== "" && expiryOk && !submitting;

  const close = (): void => {
    onClose();
    // Defer so focus lands after the dialog surface has unmounted.
    setTimeout(() => triggerRef?.current?.focus(), 0);
  };

  return (
    <Dialog
      open={open}
      modalType="alert"
      onOpenChange={(_event, data) => {
        if (!data.open) close();
      }}
    >
      <DialogSurface aria-describedby="change-confirm-body" data-testid="change-confirm-dialog">
        <DialogBody>
          <DialogTitle>{title}</DialogTitle>
          <DialogContent id="change-confirm-body">
            <dl>
              <dt>{STRINGS.target}</dt>
              <dd data-testid="change-target">{target}</dd>
              <dt>{STRINGS.version}</dt>
              <dd data-testid="change-version">{version}</dd>
              <dt>{STRINGS.diff}</dt>
              <dd>
                {diff.length === 0 ? (
                  <span>{STRINGS.noDiff}</span>
                ) : (
                  <ul data-testid="change-diff">
                    {diff.map((row) => (
                      <li key={row.field} data-testid="change-diff-row">
                        <strong>{row.field}</strong>: {STRINGS.before} <code>{row.before}</code>,{" "}
                        {STRINGS.after} <code>{row.after}</code>
                      </li>
                    ))}
                  </ul>
                )}
              </dd>
            </dl>
            <Field label={STRINGS.reason} hint={STRINGS.reasonHint} required>
              <Textarea
                value={reason}
                onChange={(_event, data) => setReason(data.value)}
                disabled={submitting}
              />
            </Field>
            {reasonNote === undefined || reasonNote === null ? null : (
              <p data-testid="change-reason-note">{reasonNote}</p>
            )}
            {showExpiry ? (
              <Field
                label={expiryRequired ? STRINGS.expiryRequired : STRINGS.expiry}
                required={expiryRequired}
              >
                <Input
                  type="datetime-local"
                  value={expiry}
                  onChange={(_event, data) => setExpiry(data.value)}
                  disabled={submitting}
                />
              </Field>
            ) : null}
            {error !== undefined && error !== null ? (
              <div role="alert" data-testid="change-error">
                {error}
              </div>
            ) : null}
          </DialogContent>
          <DialogActions>
            <Button appearance="secondary" onClick={close} disabled={submitting}>
              {STRINGS.cancel}
            </Button>
            <Button
              appearance="primary"
              disabled={!canSubmit}
              onClick={() =>
                onSubmit({ reason: trimmed, expiry: showExpiry && expiry !== "" ? expiry : null })
              }
            >
              {submitting ? STRINGS.submitting : STRINGS.submit}
            </Button>
          </DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
}
