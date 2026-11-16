import { Checkbox, Field, Input, Radio, RadioGroup, Select } from "@fluentui/react-components";
import type { ReactElement } from "react";
import { ReasonCodeField } from "../shared/ReasonCodeField";
import { needsReason, type ChangeForm, type Draft } from "./changes";
import { IDENTITY_STRINGS as S } from "./strings";
import { GRANT_PERMISSIONS, ROLE_NAMES, type GrantPermission, type RoleName } from "./types";

export interface ChangeControlsProps {
  readonly draft: Draft;
  readonly form: ChangeForm;
  readonly disabled: boolean;
  readonly onChange: (next: ChangeForm) => void;
}

/** The fields each change needs, rendered in the confirm dialog's controls slot. */
export function ChangeControls({
  draft,
  form,
  disabled,
  onChange,
}: ChangeControlsProps): ReactElement {
  const set = (patch: Partial<ChangeForm>): void => onChange({ ...form, ...patch });
  return (
    <>
      {draft.kind === "assign-role" ? (
        <>
          <Field label={S.fields.role} required>
            <Select
              value={form.role}
              disabled={disabled}
              onChange={(_e, data) => set({ role: data.value as RoleName })}
            >
              {ROLE_NAMES.map((name) => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
            </Select>
          </Field>
          <Field label={S.fields.domainIds} required>
            <Input
              value={form.domainIds}
              disabled={disabled}
              onChange={(_e, data) => set({ domainIds: data.value })}
            />
          </Field>
        </>
      ) : null}
      {draft.kind === "add-membership" ? (
        <Field label={S.fields.domainId} required>
          <Input
            value={form.domainId}
            disabled={disabled}
            onChange={(_e, data) => set({ domainId: data.value })}
          />
        </Field>
      ) : null}
      {draft.kind === "put-grant" ? (
        <>
          <Field label={S.fields.resourceId} required>
            <Input
              value={form.resourceId}
              disabled={disabled}
              onChange={(_e, data) => set({ resourceId: data.value })}
            />
          </Field>
          <Field label={S.fields.permissions} required>
            <div role="group" aria-label={S.fields.permissions}>
              {GRANT_PERMISSIONS.map((permission) => (
                <Checkbox
                  key={permission}
                  label={permission}
                  disabled={disabled}
                  checked={form.permissions.includes(permission)}
                  onChange={(_e, data) =>
                    set({
                      permissions: data.checked
                        ? [...form.permissions, permission as GrantPermission]
                        : form.permissions.filter((p) => p !== permission),
                    })
                  }
                />
              ))}
            </div>
          </Field>
        </>
      ) : null}
      {draft.kind === "revoke" ? (
        <Field label={S.fields.mode} required>
          <RadioGroup
            value={form.mode}
            disabled={disabled}
            onChange={(_e, data) => set({ mode: data.value as ChangeForm["mode"] })}
          >
            <Radio value="until_lifted" label={S.fields.untilLifted} />
            <Radio value="issued_before" label={S.fields.issuedBefore} />
          </RadioGroup>
        </Field>
      ) : null}
      {needsReason(draft.kind) ? (
        <ReasonCodeField
          value={form.reason}
          disabled={disabled}
          onChange={(reason) => set({ reason })}
        />
      ) : null}
    </>
  );
}
