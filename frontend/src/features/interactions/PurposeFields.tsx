import { Field, Input, Select } from "@fluentui/react-components";
import type { ReactElement } from "react";
import { STRINGS, purposeLabel } from "./strings";
import { PURPOSE_CODES, type InteractionAccessPurpose, type PurposeCode } from "./types";

/** The purpose as the form holds it: `code` is "" until the user picks one. */
export interface PurposeDraft {
  readonly code: string;
  readonly caseRef: string;
}

export const EMPTY_PURPOSE: PurposeDraft = { code: "", caseRef: "" };

const CASE_REF = /^[A-Za-z0-9._:-]{1,128}$/;
const GUID = /[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}/;

/** The case reference problem, or null when it is empty or acceptable (the server re-checks). */
export function caseRefProblem(value: string): string | null {
  const trimmed = value.trim();
  if (trimmed === "") return null;
  if (GUID.test(trimmed)) return STRINGS.purpose.caseRefGuid;
  if (!CASE_REF.test(trimmed)) return STRINGS.purpose.caseRefInvalid;
  return null;
}

/** The wire purpose, or null while the draft is incomplete or invalid. */
export function toPurpose(draft: PurposeDraft): InteractionAccessPurpose | null {
  if (!(PURPOSE_CODES as readonly string[]).includes(draft.code)) return null;
  if (caseRefProblem(draft.caseRef) !== null) return null;
  const caseRef = draft.caseRef.trim();
  return { purpose_code: draft.code as PurposeCode, case_ref: caseRef === "" ? null : caseRef };
}

export interface PurposeFieldsProps {
  readonly value: PurposeDraft;
  readonly onChange: (next: PurposeDraft) => void;
  /** Show the "choose a purpose" message (after a submit attempt). */
  readonly showRequired: boolean;
  readonly idPrefix: string;
}

export function PurposeFields({
  value,
  onChange,
  showRequired,
  idPrefix,
}: PurposeFieldsProps): ReactElement {
  const caseProblem = caseRefProblem(value.caseRef);
  const missing = showRequired && value.code === "";
  return (
    <>
      <Field
        label={STRINGS.purpose.label}
        required
        validationState={missing ? "error" : "none"}
        validationMessage={missing ? STRINGS.purpose.required : undefined}
      >
        <Select
          id={`${idPrefix}-purpose`}
          data-testid={`${idPrefix}-purpose`}
          value={value.code}
          onChange={(_e, d) => onChange({ ...value, code: d.value })}
        >
          <option value="">{STRINGS.purpose.placeholder}</option>
          {PURPOSE_CODES.map((code) => (
            <option key={code} value={code}>
              {purposeLabel(code)}
            </option>
          ))}
        </Select>
      </Field>
      <Field
        label={STRINGS.purpose.caseRef}
        hint={STRINGS.purpose.caseRefHint}
        validationState={caseProblem !== null ? "error" : "none"}
        validationMessage={caseProblem ?? undefined}
      >
        <Input
          id={`${idPrefix}-case-ref`}
          data-testid={`${idPrefix}-case-ref`}
          value={value.caseRef}
          maxLength={128}
          onChange={(_e, d) => onChange({ ...value, caseRef: d.value })}
        />
      </Field>
    </>
  );
}
