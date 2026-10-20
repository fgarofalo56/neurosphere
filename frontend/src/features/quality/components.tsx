import { Badge, MessageBar, MessageBarBody, MessageBarTitle } from "@fluentui/react-components";
import type { ReactElement } from "react";
import { ForbiddenError, type ApiError } from "../../api/index.js";
import { STRINGS, fractionText, levelText, numberText, orUnknown } from "./strings";
import type { CalibrationState, Judge, PilotGroundedRate } from "./types";

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
        <Badge appearance="filled" color="warning" data-testid="calibration-state">
          {STRINGS.uncalibrated}
        </Badge>
        <small> {STRINGS.uncalibratedNote}</small>
      </span>
    );
  }
  return (
    <Badge
      appearance="tint"
      color={state === "calibrated" ? "success" : "informative"}
      data-testid="calibration-state"
    >
      {state === "calibrated" ? STRINGS.calibrated : STRINGS.notApplicable}
    </Badge>
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

export function PilotRate({ rate }: { readonly rate: PilotGroundedRate }): ReactElement {
  const estimable = rate.method === "wilson_score" && rate.value !== null;
  return (
    <section aria-labelledby="pilot-heading" data-testid="pilot-rate">
      <h2 id="pilot-heading">{STRINGS.pilot.title}</h2>
      <p data-testid="pilot-target">{rate.target_label}</p>
      <dl>
        <dt>{STRINGS.pilot.estimate}</dt>
        <dd data-testid="pilot-value">{estimable ? fractionText(rate.value) : STRINGS.unknown}</dd>
        {estimable ? (
          <>
            <dt>{STRINGS.pilot.interval}</dt>
            <dd data-testid="pilot-interval">{intervalText(rate.lower, rate.upper, rate.level)}</dd>
          </>
        ) : null}
        <dt>{STRINGS.pilot.sampleSize}</dt>
        <dd data-testid="pilot-n">{rate.n}</dd>
        {estimable ? (
          <>
            <dt>{STRINGS.pilot.method}</dt>
            <dd>{rate.method}</dd>
          </>
        ) : null}
      </dl>
      {estimable ? null : <p data-testid="pilot-reason">{STRINGS.pilot.notEstimableReason}</p>}
    </section>
  );
}
