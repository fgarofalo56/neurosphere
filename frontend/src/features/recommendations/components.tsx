import { Badge, MessageBar, MessageBarBody, MessageBarTitle } from "@fluentui/react-components";
import type { ReactElement } from "react";
import { ForbiddenError, type ApiError } from "../../api/index.js";
import { STRINGS, fractionText, orUnknown, priceVersionText } from "./strings";
import type { Coverage, Owner, ProjectedEstimate, Recommendation, Uncertainty } from "./types";

/**
 * Shown on every recommendation while no action gate has passed (PRP-17). The record's own
 * `advisory` flag can only add to this; it can never remove it while `executable` is false.
 */
export function AdvisoryBadge({
  advisory = true,
  executable = false,
}: {
  readonly advisory?: boolean;
  readonly executable?: boolean;
}): ReactElement | null {
  if (!advisory && executable) return null;
  return (
    <span>
      <Badge appearance="tint" color="informative" data-testid="advisory-badge">
        {STRINGS.advisory}
      </Badge>
      {executable ? null : <small data-testid="advisory-reason"> {STRINGS.advisoryReason}</small>}
    </span>
  );
}

export function EvidenceStatus({ rec }: { readonly rec: Recommendation }): ReactElement {
  return (
    <span data-testid="evidence-status">
      {rec.evidence_status === "insufficient_evidence" ? STRINGS.insufficientHistory : "Sufficient"}
    </span>
  );
}

// The contract sends unknown values as `null`, never 0 (and the real API serialises absent
// optionals as `null`), so every guard below is `== null`: it covers both `null` and `undefined`.

export function ownerText(owner: Owner | null | undefined): string {
  if (owner == null || owner.owner_id == null) return STRINGS.unknown;
  return `${owner.owner_id} (${owner.resolution})`;
}

export function coverageText(c: Coverage | null | undefined): string {
  if (c == null) return STRINGS.unknown;
  return `${orUnknown(c.method)}, observed ${fractionText(c.observed_fraction)}`;
}

export function uncertaintyText(u: Uncertainty | null | undefined): string {
  if (u == null) return STRINGS.unknown;
  if (u.method === "not_estimable") return "not estimable";
  const level = u.level == null ? "" : `, level ${u.level}`;
  return `${u.method}: lower ${orUnknown(u.lower)}, upper ${orUnknown(u.upper)}${level}`;
}

export function EstimateBlock({
  estimate,
}: {
  readonly estimate: ProjectedEstimate | null | undefined;
}): ReactElement {
  if (estimate == null) {
    return (
      <p data-testid="estimate-unknown">
        {STRINGS.estimate}: {STRINGS.unknown}
      </p>
    );
  }
  const money = (v: string | null | undefined): string =>
    v == null ? STRINGS.unknown : `${v} ${orUnknown(estimate.currency)}`;
  return (
    <dl data-testid="estimate">
      <dt>Period</dt>
      <dd>{orUnknown(estimate.period)}</dd>
      <dt>Baseline</dt>
      <dd>{money(estimate.baseline_amount)}</dd>
      <dt>Projected</dt>
      <dd>{money(estimate.projected_amount)}</dd>
      <dt>Lower bound</dt>
      <dd>{money(estimate.lower_amount)}</dd>
      <dt>Upper bound</dt>
      <dd>{money(estimate.upper_amount)}</dd>
      <dt>Price</dt>
      <dd data-testid="price-version">
        {priceVersionText(estimate.price_version, estimate.price_effective_date)}
      </dd>
    </dl>
  );
}

/** 403 means the API declined; 503 or anything else is an unavailable state, never empty data. */
export function QueryErrorState({ error }: { readonly error: ApiError }): ReactElement {
  const ref = error.correlationId !== "" ? ` (reference ${error.correlationId})` : "";
  if (error instanceof ForbiddenError) {
    return (
      <MessageBar intent="warning" role="alert" data-testid="forbidden-state">
        <MessageBarBody>
          <MessageBarTitle>{STRINGS.forbidden}</MessageBarTitle>
          Contact your administrator if you need access{ref}.
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
      </MessageBarBody>
    </MessageBar>
  );
}
