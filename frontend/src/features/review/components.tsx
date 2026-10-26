import { Button } from "@fluentui/react-components";
import type { ReactElement } from "react";
import { StatusPill, Timestamp, type StatusTone } from "../../design-system";
import { StatePanel } from "../workspaces/StatePanel";
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
      <StatePanel
        tone="warning"
        title={item ? STRINGS.forbiddenItem : STRINGS.forbidden}
        data-testid="forbidden-state"
      >
        {item ? STRINGS.forbiddenItemDetail : STRINGS.forbiddenDetail}
        {ref}.
      </StatePanel>
    );
  }
  return (
    <StatePanel
      tone="danger"
      title={STRINGS.unavailable}
      data-testid="unavailable-state"
      action={
        onRetry !== undefined ? (
          <Button size="small" onClick={onRetry}>
            {STRINGS.retry}
          </Button>
        ) : undefined
      }
    >
      {STRINGS.unavailableDetail}
      {ref}
    </StatePanel>
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
    <StatePanel tone="danger" title={STRINGS.errors.title} data-testid="mutation-error">
      {text}
      {referenceOf(error)}
    </StatePanel>
  );
}

/** SLA due time as a `Timestamp`, with an "overdue" pill once it has passed. */
export function SlaDue({
  slaDueAt,
  now = Date.now(),
}: {
  readonly slaDueAt: string;
  readonly now?: number;
}): ReactElement {
  const at = Date.parse(slaDueAt);
  const overdue = !Number.isNaN(at) && at < now;
  return (
    <>
      <Timestamp value={slaDueAt} now={now} />
      {overdue ? (
        <>
          {" "}
          <StatusPill label={STRINGS.overdue} tone="danger" />
        </>
      ) : null}
    </>
  );
}

export function StateBadge({ state }: { readonly state: string }): ReactElement {
  const tone: StatusTone =
    state === "approved" || state === "executed"
      ? "success"
      : state === "rejected" || state === "failed" || state === "expired"
        ? "danger"
        : state === "escalated"
          ? "warning"
          : "neutral";
  return (
    <span data-testid="state-badge">
      <StatusPill label={state} tone={tone} />
    </span>
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
                <span data-testid="decision-effective">
                  <StatusPill label={D.effective} tone="success" />
                </span>
              ) : null}
              {isSuperseded ? (
                <span data-testid="decision-superseded">
                  <StatusPill label={D.superseded} />
                </span>
              ) : null}
              <br />
              {D.reviewer}: {orUnknown(d.reviewer.principal_pseudonym)}; {D.decidedAt}:{" "}
              <Timestamp value={d.decided_at} />; {D.reason}: {d.reason}
            </li>
          );
        })}
      </ul>
      {item.superseded_decision_ids.length > 0 ? <p>{D.supersededNote}</p> : null}
    </>
  );
}
