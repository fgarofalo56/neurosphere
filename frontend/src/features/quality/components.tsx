import { makeStyles, tokens } from "@fluentui/react-components";
import type { ReactElement } from "react";
import { ForbiddenError, type ApiError } from "../../api/index.js";
import { ErrorState, Panel, StatusPill } from "../../design-system";
import { STRINGS, fractionText, levelText, numberText, orUnknown } from "./strings";
import type { CalibrationState, Judge, PilotGroundedRate } from "./types";

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

export function judgeText(j: Judge): string {
  const parts = [
    j.judge_kind,
    `model ${orUnknown(j.judge_model_id)} ${orUnknown(j.judge_model_version)}`,
  ];
  if (j.judge_prompt_version !== null) parts.push(`prompt ${j.judge_prompt_version}`);
  if (j.program_version !== null) parts.push(`program ${j.program_version}`);
  return parts.join(", ");
}

export function CalibrationBadge({ state }: { readonly state: CalibrationState }): ReactElement {
  if (state === "uncalibrated") {
    return (
      <span>
        <span data-testid="calibration-state">
          <StatusPill label={STRINGS.uncalibrated} tone="warning" />
        </span>
        <small> {STRINGS.uncalibratedNote}</small>
      </span>
    );
  }
  return (
    <span data-testid="calibration-state">
      <StatusPill
        label={state === "calibrated" ? STRINGS.calibrated : STRINGS.notApplicable}
        tone={state === "calibrated" ? "success" : "neutral"}
      />
    </span>
  );
}

export function intervalText(
  lower: number | null,
  upper: number | null,
  level: number | null,
): string {
  if (lower === null || upper === null) return STRINGS.notEstimable;
  return `${numberText(lower)} to ${numberText(upper)} (${levelText(level)})`;
}

const useStyles = makeStyles({
  list: {
    display: "grid",
    gridTemplateColumns: "max-content 1fr",
    columnGap: tokens.spacingHorizontalL,
    rowGap: tokens.spacingVerticalXXS,
    margin: 0,
  },
  term: { color: tokens.colorNeutralForeground2 },
  def: { margin: 0, fontWeight: tokens.fontWeightSemibold },
});

export function PilotRate({ rate }: { readonly rate: PilotGroundedRate }): ReactElement {
  const styles = useStyles();
  const estimable = rate.method === "wilson_score" && rate.value !== null;
  return (
    <Panel landmark="region" title={STRINGS.pilot.title} testId="pilot-rate">
      <p data-testid="pilot-target">{rate.target_label}</p>
      <dl className={styles.list}>
        <dt className={styles.term}>{STRINGS.pilot.estimate}</dt>
        <dd className={styles.def} data-testid="pilot-value">
          {estimable ? fractionText(rate.value) : STRINGS.unknown}
        </dd>
        {estimable ? (
          <>
            <dt className={styles.term}>{STRINGS.pilot.interval}</dt>
            <dd className={styles.def} data-testid="pilot-interval">
              {intervalText(rate.lower, rate.upper, rate.level)}
            </dd>
          </>
        ) : null}
        <dt className={styles.term}>{STRINGS.pilot.sampleSize}</dt>
        <dd className={styles.def} data-testid="pilot-n">
          {rate.n}
        </dd>
        {estimable ? (
          <>
            <dt className={styles.term}>{STRINGS.pilot.method}</dt>
            <dd className={styles.def}>{rate.method}</dd>
          </>
        ) : null}
      </dl>
      {estimable ? null : <p data-testid="pilot-reason">{STRINGS.pilot.notEstimableReason}</p>}
    </Panel>
  );
}
