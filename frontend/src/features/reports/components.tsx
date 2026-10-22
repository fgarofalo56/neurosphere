import {
  Badge,
  Button,
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
} from "@fluentui/react-components";
import { useState, type ReactElement } from "react";
import {
  DependencyTransientError,
  ForbiddenError,
  InvalidSchemaError,
  StaleVersionError,
  type ApiError,
} from "../../api/index.js";
import {
  useDecidePublication,
  useInvalidateReports,
  useRequestPublication,
  useShareReport,
  useUnshareReport,
} from "./hooks";
import { STRINGS } from "./strings";
import type { Freshness, PublicationState, ReportView, RunCitation } from "./types";

function referenceOf(error: ApiError): string {
  return error.correlationId !== "" ? ` (${STRINGS.errors.reference} ${error.correlationId})` : "";
}

/**
 * Page-level read failure. 403 is an access message, 404 "not found or not shared", 422 a plan
 * that failed server validation, anything else a retryable outage. Never an empty result.
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
  if (error.status === 404) {
    return (
      <MessageBar intent="warning" role="alert" data-testid="not-found-state">
        <MessageBarBody>
          <MessageBarTitle>{STRINGS.notFound}</MessageBarTitle>
          {STRINGS.notFoundDetail}
          {ref}
        </MessageBarBody>
      </MessageBar>
    );
  }
  if (error instanceof InvalidSchemaError) {
    return (
      <MessageBar intent="error" role="alert" data-testid="invalid-plan-state">
        <MessageBarBody>
          <MessageBarTitle>{STRINGS.invalidPlan}</MessageBarTitle>
          {STRINGS.invalidPlanDetail}
          {ref}
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
  const reason = error.problem?.reason;
  if (error instanceof ForbiddenError) {
    if (reason === "not_owner") return STRINGS.errors.notOwner;
    if (reason === "self_approval_refused") return STRINGS.errors.selfApproval;
    return STRINGS.errors.forbidden;
  }
  if (error instanceof StaleVersionError) {
    return reason === "publication_not_pending" ? STRINGS.errors.notPending : STRINGS.errors.stale;
  }
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

export function PublicationBadge({ state }: { readonly state: PublicationState }): ReactElement {
  const color =
    state === "approved"
      ? "success"
      : state === "rejected"
        ? "danger"
        : state === "pending"
          ? "warning"
          : "informative";
  return (
    <Badge appearance="tint" color={color} data-testid="publication-badge">
      {STRINGS.publication[state]}
    </Badge>
  );
}

function freshnessText(f: Freshness): string {
  return STRINGS.freshness[f];
}

export function Citations({
  citations,
}: {
  readonly citations: readonly RunCitation[];
}): ReactElement | null {
  if (citations.length === 0) return null;
  return (
    <section aria-label={STRINGS.citationsTitle} data-testid="citations">
      <h3>{STRINGS.citationsTitle}</h3>
      <ul>
        {citations.map((c) => (
          <li key={c.record_id} data-testid="citation">
            {c.record_id} ({c.source}){" "}
            {c.as_of !== null ? `${STRINGS.citationAsOf} ${c.as_of}, ` : ""}
            {freshnessText(c.freshness)}
          </li>
        ))}
      </ul>
    </section>
  );
}

// ----------------------------------------------------------------------------- sharing

export function ShareDialog({ report }: { readonly report: ReportView }): ReactElement {
  const [principalId, setPrincipalId] = useState("");
  const invalidate = useInvalidateReports();
  const share = useShareReport();
  const unshare = useUnshareReport();
  const params = { domainId: report.domain_id, reportId: report.id };
  const error = share.error ?? unshare.error;

  return (
    <Dialog>
      <DialogTrigger disableButtonEnhancement>
        <Button data-testid="share-open">{STRINGS.share.open}</Button>
      </DialogTrigger>
      <DialogSurface>
        <DialogBody>
          <DialogTitle>{STRINGS.share.title}</DialogTitle>
          <DialogContent>
            <p>{STRINGS.share.description}</p>
            <form
              aria-label={STRINGS.share.title}
              onSubmit={(e) => {
                e.preventDefault();
                const value = principalId.trim();
                if (value === "") return;
                share.mutate(
                  { ...params, principalId: value },
                  {
                    onSuccess: () => {
                      setPrincipalId("");
                      void invalidate();
                    },
                  },
                );
              }}
            >
              <Field label={STRINGS.share.principalLabel}>
                <Input
                  value={principalId}
                  maxLength={512}
                  onChange={(_e, data) => setPrincipalId(data.value)}
                />
              </Field>
              <Button type="submit" appearance="primary" disabled={share.isPending}>
                {STRINGS.share.add}
              </Button>
            </form>
            <h3>{STRINGS.share.current}</h3>
            {report.shares.length === 0 ? (
              <p data-testid="no-shares">{STRINGS.share.none}</p>
            ) : (
              <ul data-testid="share-list">
                {report.shares.map((id) => (
                  <li key={id}>
                    {id}{" "}
                    <Button
                      size="small"
                      disabled={unshare.isPending}
                      onClick={() =>
                        unshare.mutate(
                          { ...params, principalId: id },
                          { onSuccess: () => void invalidate() },
                        )
                      }
                    >
                      {STRINGS.share.remove}
                    </Button>
                  </li>
                ))}
              </ul>
            )}
            {error !== null ? <MutationError error={error} /> : null}
          </DialogContent>
          <DialogActions>
            <DialogTrigger disableButtonEnhancement>
              <Button appearance="secondary">{STRINGS.share.close}</Button>
            </DialogTrigger>
          </DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
}

// ------------------------------------------------------------------------- publication

/**
 * Owner control: request add-to-UI. Shown only to the owner (a server hint; the route still
 * requires `report.create` and ownership).
 */
export function RequestPublication({
  report,
}: {
  readonly report: ReportView;
}): ReactElement | null {
  const invalidate = useInvalidateReports();
  const request = useRequestPublication();
  if (!report.is_owner || report.publication.state === "pending") return null;
  return (
    <span>
      <Button
        data-testid="request-publication"
        disabled={request.isPending}
        onClick={() =>
          request.mutate(
            { domainId: report.domain_id, reportId: report.id },
            { onSuccess: () => void invalidate() },
          )
        }
      >
        {STRINGS.publish.request}
      </Button>
      {request.isSuccess ? (
        <span role="status" data-testid="publication-requested">
          {" "}
          {STRINGS.publish.requested}
        </span>
      ) : null}
      {request.error !== null ? <MutationError error={request.error} /> : null}
    </span>
  );
}

/**
 * Approve / reject. Rendered only when the server says this caller may decide
 * (`can_decide_publication`: config.manage in the domain, not the owner or requester, request
 * pending). Hiding is a usability aid; the decision route enforces and refuses self-approval.
 */
export function DecisionControls({ report }: { readonly report: ReportView }): ReactElement | null {
  const [reason, setReason] = useState("");
  const invalidate = useInvalidateReports();
  const decide = useDecidePublication();
  if (!report.can_decide_publication) return null;
  const send = (decision: "approve" | "reject"): void => {
    decide.mutate(
      { domainId: report.domain_id, reportId: report.id, decision, reason: reason.trim() },
      { onSuccess: () => void invalidate() },
    );
  };
  return (
    <section aria-label={STRINGS.publish.decisionPrompt} data-testid="decision-controls">
      <p>{STRINGS.publish.decisionPrompt}</p>
      <Field label={STRINGS.publish.reasonLabel}>
        <Input value={reason} maxLength={500} onChange={(_e, data) => setReason(data.value)} />
      </Field>
      <Button appearance="primary" disabled={decide.isPending} onClick={() => send("approve")}>
        {STRINGS.publish.approve}
      </Button>{" "}
      <Button disabled={decide.isPending} onClick={() => send("reject")}>
        {STRINGS.publish.reject}
      </Button>
      {decide.isSuccess ? (
        <span role="status" data-testid="decision-recorded">
          {" "}
          {STRINGS.publish.decided}
        </span>
      ) : null}
      {decide.error !== null ? <MutationError error={decide.error} /> : null}
    </section>
  );
}
