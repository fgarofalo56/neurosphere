import { makeStyles, tokens } from "@fluentui/react-components";
import type { ReactElement } from "react";
import { ForbiddenError, type ApiError } from "../../api/index.js";
import { ErrorState, StatusPill, formatCurrency } from "../../design-system";
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
      <span data-testid="advisory-badge">
        <StatusPill label={STRINGS.advisory} tone="neutral" />
      </span>
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
      <div data-testid="forbidden-state">
        <ErrorState
          title={STRINGS.forbidden}
          message={`Contact your administrator if you need access${ref}.`}
        />
      </div>
    );
  }
  return (
    <div data-testid="unavailable-state">
      <ErrorState title={STRINGS.unavailable} message={`${STRINGS.unavailableDetail}${ref}`} />
    </div>
  );
}

/**
 * Projected change per period (projected minus baseline), in the estimate's one currency. It is
 * an estimate, never a promise; "unknown" when either amount or the currency is missing.
 */
export function impactText(estimate: ProjectedEstimate | null | undefined): string {
  if (estimate == null) return STRINGS.unknown;
  const { baseline_amount: base, projected_amount: proj, currency } = estimate;
  if (base == null || proj == null || currency == null) return STRINGS.unknown;
  if (base.trim() === "" || proj.trim() === "") return STRINGS.unknown;
  const delta = Number(proj) - Number(base);
  if (!Number.isFinite(delta)) return STRINGS.unknown;
  const sign = delta > 0 ? "+" : "";
  const period = estimate.period == null ? "" : ` (${estimate.period})`;
  return `${sign}${formatCurrency(delta, currency)}${period}`;
}

/** Short confidence wording from the evidence status and the uncertainty record. */
export function confidenceText(rec: Recommendation): string {
  if (rec.evidence_status === "insufficient_evidence") return STRINGS.insufficientHistory;
  const u = rec.uncertainty;
  if (u == null) return STRINGS.unknown;
  if (u.method === "not_estimable") return "not estimable";
  return u.level == null ? u.method : `${Number((u.level * 100).toFixed(2))}% interval`;
}

const useFactStyles = makeStyles({
  facts: {
    display: "grid",
    gridTemplateColumns: "max-content 1fr",
    columnGap: tokens.spacingHorizontalL,
    rowGap: tokens.spacingVerticalXXS,
    margin: 0,
  },
  term: { color: tokens.colorNeutralForeground2 },
  def: { margin: 0, overflowWrap: "anywhere" },
});

/** Impact, confidence and owner as a definition list, used on each recommendation card. */
export function Facts({ rec }: { readonly rec: Recommendation }): ReactElement {
  const styles = useFactStyles();
  return (
    <dl className={styles.facts}>
      <dt className={styles.term}>Projected change</dt>
      <dd className={styles.def} data-testid="impact">
        {impactText(rec.projected_estimate)}
      </dd>
      <dt className={styles.term}>Confidence</dt>
      <dd className={styles.def} data-testid="confidence">
        {confidenceText(rec)}
      </dd>
      <dt className={styles.term}>{STRINGS.sections.owner}</dt>
      <dd className={styles.def} data-testid="card-owner">
        {ownerText(rec.owner)}
      </dd>
    </dl>
  );
}
