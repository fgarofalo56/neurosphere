import {
  Badge,
  Button,
  MessageBar,
  MessageBarBody,
  MessageBarTitle,
} from "@fluentui/react-components";
import type { ReactElement } from "react";
import {
  DependencyTransientError,
  ForbiddenError,
  InvalidSchemaError,
  StaleVersionError,
  type ApiError,
} from "../../api/index.js";
import { STRINGS, orUnknown } from "./strings";
import type { ApprovalDecision, Decision, ReviewItemView } from "./types";

function referenceOf(error: ApiError): string {
  return error.correlationId !== "" ? ` (${STRINGS.reference} ${error.correlationId})` : "";
}

/**
 * Read failure. 403 is an access message (never an empty list); everything else, including a 503
 * policy-store outage, is a retryable "service unavailable" state.
 */
export function QueryErrorState({
  error,
  onRetry,
  item = false,
}: {
  readonly error: ApiError;
  readonly onRetry?: (() => void) | undefined;
  /** True on the item page, where 403 means "not allowed to review this item". */
  readonly item?: boolean;
}): ReactElement {
  const ref = referenceOf(error);
  if (error instanceof ForbiddenError) {
    return (
      <MessageBar intent="warning" role="alert" data-testid="forbidden-state">
        <MessageBarBody>
          <MessageBarTitle>{item ? STRINGS.forbiddenItem : STRINGS.forbidden}</MessageBarTitle>
          {item ? STRINGS.forbiddenItemDetail : STRINGS.forbiddenDetail}
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

/** A failed claim/decision. Nothing is assumed to have been recorded. */
export function MutationError({
  error,
  action,
}: {
  readonly error: ApiError;
  readonly action: Decision | "claim";
}): ReactElement {
  const reason = error.problem?.reason;
  let text: string = STRINGS.errors.generic;
  if (error instanceof ForbiddenError) {
    text =
      action === "claim"
        ? STRINGS.errors.forbiddenClaim
        : STRINGS.errors.forbiddenDecision(action === "approved" ? "approve" : "reject");
    if (reason === "self_approval_forbidden") text = STRINGS.errors.selfApproval;
  } else if (error instanceof StaleVersionError) {
    text = STRINGS.errors.stale;
  } else if (error instanceof InvalidSchemaError) {
    text = STRINGS.errors.invalid;
  } else if (error instanceof DependencyTransientError) {
    text = STRINGS.errors.unavailable;
  }
  return (
    <MessageBar intent="error" role="alert" data-testid="mutation-error">
      <MessageBarBody>
        {text}
        {referenceOf(error)}
      </MessageBarBody>
    </MessageBar>
  );
}

export function slaText(slaDueAt: string, now: number = Date.now()): string {
  const at = Date.parse(slaDueAt);
  return !Number.isNaN(at) && at < now ? `${slaDueAt} (${STRINGS.overdue})` : slaDueAt;
}

export function StateBadge({ state }: { readonly state: string }): ReactElement {
  const color =
    state === "approved" || state === "executed"
      ? "success"
      : state === "rejected" || state === "failed" || state === "expired"
        ? "danger"
        : state === "escalated"
          ? "warning"
          : "informative";
  return (
    <Badge appearance="tint" color={color} data-testid="state-badge">
      {state}
    </Badge>
  );
}

/**
 * Lists every logged decision. Only the effective one took effect; the others lost a race or were
 * overtaken by a timer and stay visible as history, marked superseded.
 */
export function DecisionList({ item }: { readonly item: ReviewItemView }): ReactElement {
  const D = STRINGS.detail;
  if (item.decisions.length === 0) return <p data-testid="decisions-empty">{D.noDecisions}</p>;
  const superseded = new Set(item.superseded_decision_ids);
  return (
    <>
      <ul aria-label={D.decisions} data-testid="decisions">
        {item.decisions.map((d: ApprovalDecision) => {
          const isSuperseded = superseded.has(d.decision_id);
          const isEffective = d.decision_id === item.effective_decision_id;
          return (
            <li key={d.decision_id} data-testid="decision" data-superseded={isSuperseded}>
              <strong>{d.decision}</strong>{" "}
              {isEffective ? (
                <Badge appearance="filled" color="success" data-testid="decision-effective">
                  {D.effective}
                </Badge>
              ) : null}
              {isSuperseded ? (
                <Badge appearance="outline" color="subtle" data-testid="decision-superseded">
                  {D.superseded}
                </Badge>
              ) : null}
              <br />
              {D.reviewer}: {orUnknown(d.reviewer.principal_pseudonym)}; {D.decidedAt}:{" "}
              {d.decided_at}; {D.reason}: {d.reason}
            </li>
          );
        })}
      </ul>
      {item.superseded_decision_ids.length > 0 ? <p>{D.supersededNote}</p> : null}
    </>
  );
}
