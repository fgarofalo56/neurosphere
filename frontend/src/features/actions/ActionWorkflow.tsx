import { Button, MessageBar, MessageBarBody } from "@fluentui/react-components";
import { useRef, useState, type ReactElement } from "react";
import { Link } from "react-router";
import type { ApiError } from "../../api/index.js";
import { ActionError, ConfirmationDialog } from "./components";
import { useConfirmIntent, usePresentConfirmation, useValidateIntent } from "./hooks";
import { STRINGS } from "./strings";
import type { ActionView } from "./types";

export function reviewItemHref(domainId: string, itemId: string): string {
  const p = new URLSearchParams({ domain_id: domainId, item_id: itemId });
  return `/review/item?${p.toString()}`;
}

export interface ActionWorkflowProps {
  readonly domainId: string;
  readonly view: ActionView;
  /** Called with the server's latest view after every successful step. */
  readonly onView: (view: ActionView) => void;
}

/**
 * Walks an intent through validate -> confirmation -> confirm using the same endpoints the REST
 * and chat channels use. Advisory intents get an explanation and no control that could run them.
 * Every step ends on the server's answer; nothing is assumed to have succeeded.
 */
export function ActionWorkflow({ domainId, view, onView }: ActionWorkflowProps): ReactElement {
  const [error, setError] = useState<ApiError | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const validate = useValidateIntent();
  const present = usePresentConfirmation();
  const confirm = useConfirmIntent();
  const intentId = view.intent.intent_id;
  const busy = validate.isPending || present.isPending || confirm.isPending;

  // The dialog unmounts on close, so Fluent cannot restore focus itself; hand it back to the
  // "Review and confirm" trigger once the dialog's own focus handling has settled.
  const closeDialog = (): void => {
    setDialogOpen(false);
    setTimeout(() => triggerRef.current?.focus(), 0);
  };

  if (view.advisory) {
    return (
      <MessageBar intent="info" role="status" data-testid="advisory-note">
        <MessageBarBody>{STRINGS.advisory}</MessageBarBody>
      </MessageBar>
    );
  }

  const step = (run: typeof validate | typeof present, openDialog: boolean): void => {
    setError(null);
    run.mutate(
      { domainId, intentId },
      {
        onSuccess: (next) => {
          onView(next);
          if (openDialog) setDialogOpen(true);
        },
        onError: setError,
      },
    );
  };

  const state = view.intent.state;
  return (
    <div data-testid="workflow">
      {view.requires_approval ? <p>{STRINGS.detail.requiresApproval}</p> : null}
      {view.self_approval_forbidden ? <p>{STRINGS.detail.selfApprovalForbidden}</p> : null}
      {state === "drafted" ? (
        <Button appearance="primary" disabled={busy} onClick={() => step(validate, false)}>
          {busy ? STRINGS.steps.working : STRINGS.steps.validate}
        </Button>
      ) : null}
      {state === "validated" ? (
        <Button appearance="primary" disabled={busy} onClick={() => step(present, true)}>
          {busy ? STRINGS.steps.working : STRINGS.steps.requestConfirmation}
        </Button>
      ) : null}
      {state === "awaiting_confirmation" ? (
        <Button
          ref={triggerRef}
          appearance="primary"
          onClick={() => {
            setError(null);
            setDialogOpen(true);
          }}
        >
          {STRINGS.steps.reviewConfirm}
        </Button>
      ) : null}
      {state === "awaiting_approval" ? (
        <p data-testid="awaiting-approval">
          {STRINGS.detail.waitingReviewer}{" "}
          {view.review_item_id !== null ? (
            <Link to={reviewItemHref(domainId, view.review_item_id)}>
              {STRINGS.detail.reviewItem}
            </Link>
          ) : null}
        </p>
      ) : null}
      {error !== null && !dialogOpen ? <ActionError error={error} /> : null}
      {dialogOpen && state === "awaiting_confirmation" ? (
        <ConfirmationDialog
          intent={view.intent}
          requiresApproval={view.requires_approval}
          submitting={confirm.isPending}
          error={error}
          onClose={closeDialog}
          onSubmit={(confirmationHash) => {
            setError(null);
            confirm.mutate(
              { domainId, intentId, confirmationHash },
              {
                onSuccess: (next) => {
                  setDialogOpen(false);
                  onView(next);
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
