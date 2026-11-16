import { Field, Input, Select } from "@fluentui/react-components";
import type { ReactElement } from "react";
import { credentialProblem, type CredentialDraft, type CredentialKind } from "./credentialReference";

/**
 * A credential REFERENCE only: a Key Vault secret URI or a managed identity client id. Anything
 * that does not look like one is blocked before sending; the API remains the authority.
 */
export function CredentialReferenceField({
  value,
  onChange,
  allowNone = true,
  allowKeyVault = true,
  serverError,
}: {
  readonly value: CredentialDraft;
  readonly onChange: (next: CredentialDraft) => void;
  readonly allowNone?: boolean;
  readonly allowKeyVault?: boolean;
  readonly serverError?: string | undefined;
}): ReactElement {
  const problem = value.kind === "none" ? undefined : credentialProblem(value);
  const touched = value.value.trim() !== "";
  const message = serverError ?? (touched ? problem : undefined);
  return (
    <>
      <Field label="Credential type">
        <Select
          value={value.kind}
          onChange={(_e, d) => onChange({ kind: d.value as CredentialKind, value: "" })}
        >
          {allowNone ? <option value="none">None</option> : null}
          {allowKeyVault ? <option value="key_vault_secret">Key Vault secret reference</option> : null}
          <option value="managed_identity">Managed identity</option>
        </Select>
      </Field>
      {value.kind === "none" ? null : (
        <Field
          label={
            value.kind === "key_vault_secret"
              ? "Key Vault secret URI"
              : "Managed identity client id"
          }
          required
          validationState={message === undefined ? "none" : "error"}
          validationMessage={message}
          hint="A reference only. Never paste a key, token or connection string."
        >
          <Input
            autoComplete="off"
            value={value.value}
            onChange={(_e, d) => onChange({ ...value, value: d.value })}
          />
        </Field>
      )}
    </>
  );
}
