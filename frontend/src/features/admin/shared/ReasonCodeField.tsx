import { Field, Input } from "@fluentui/react-components";
import type { ReactElement } from "react";

/** The API stores a reason as a code: lower-case letters, digits and underscores, 1-64 chars. */
export const REASON_CODE_PATTERN = /^[a-z][a-z0-9_]{0,63}$/;

export function isReasonCode(value: string): boolean {
  return REASON_CODE_PATTERN.test(value);
}

export interface ReasonCodeFieldProps {
  readonly value: string;
  readonly onChange: (value: string) => void;
  readonly disabled?: boolean;
}

/** A required reason-code input for the confirm dialog's `controls` slot (reason mode "code"). */
export function ReasonCodeField({ value, onChange, disabled }: ReasonCodeFieldProps): ReactElement {
  const invalid = value !== "" && !isReasonCode(value);
  return (
    <Field
      label="Reason code"
      required
      hint="Lower-case letters, digits and underscores, starting with a letter (for example access_review)."
      validationState={invalid ? "error" : "none"}
      validationMessage={
        invalid ? "Use lower-case letters, digits and underscores only." : undefined
      }
    >
      <Input
        value={value}
        onChange={(_event, data) => onChange(data.value)}
        disabled={disabled ?? false}
        maxLength={64}
      />
    </Field>
  );
}
