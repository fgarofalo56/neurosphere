import type { CredentialReference } from "./types";

/** Same shapes as the CredentialReference contract; a client-side hint, the API is the authority. */
export const KEY_VAULT_URI =
  /^https:\/\/[a-z][a-z0-9-]{1,22}[a-z0-9]\.vault\.(azure\.net|usgovcloudapi\.net)\/secrets\/[A-Za-z0-9-]{1,127}(\/[0-9a-f]{32})?$/;
export const CLIENT_ID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

export type CredentialKind = "none" | "key_vault_secret" | "managed_identity";

export interface CredentialDraft {
  readonly kind: CredentialKind;
  readonly value: string;
}

export const EMPTY_CREDENTIAL: CredentialDraft = { kind: "none", value: "" };

/** A message when the draft does not look like a reference, or undefined when it does. */
export function credentialProblem(draft: CredentialDraft): string | undefined {
  const value = draft.value.trim();
  if (draft.kind === "none") return undefined;
  if (draft.kind === "key_vault_secret") {
    return KEY_VAULT_URI.test(value)
      ? undefined
      : "Enter a Key Vault secret URI such as https://<vault>.vault.azure.net/secrets/<name>. A secret value is never accepted here.";
  }
  return CLIENT_ID.test(value)
    ? undefined
    : "Enter the managed identity client id (a GUID). A secret value is never accepted here.";
}

/** The reference sent to the API, or null for none. Call only when `credentialProblem` is clear. */
export function toReference(draft: CredentialDraft): CredentialReference | null {
  const value = draft.value.trim();
  if (draft.kind === "key_vault_secret") return { kind: "key_vault_secret", secret_uri: value };
  if (draft.kind === "managed_identity") {
    return { kind: "managed_identity", managed_identity_client_id: value };
  }
  return null;
}

export function fromReference(ref: CredentialReference | null | undefined): CredentialDraft {
  if (ref === null || ref === undefined) return EMPTY_CREDENTIAL;
  if (ref.kind === "key_vault_secret") {
    return { kind: "key_vault_secret", value: ref.secret_uri ?? "" };
  }
  return { kind: "managed_identity", value: ref.managed_identity_client_id ?? "" };
}

/** Short text for a table cell. */
export function describeReference(ref: CredentialReference | null | undefined): string {
  if (ref === null || ref === undefined) return "None";
  if (ref.kind === "key_vault_secret") return `Key Vault: ${ref.secret_uri ?? ""}`;
  return `Managed identity: ${ref.managed_identity_client_id ?? ""}`;
}
