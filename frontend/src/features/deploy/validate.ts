/** Pure input checks for the deploy forms (the server re-validates everything). */
import { STRINGS } from "./strings";

const GUID = /^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$/;
const PRINCIPAL = /^[a-z0-9][a-z0-9._:/=-]{0,255}$/;

/** True for anything that looks like an email address: an at sign anywhere is refused. */
export function isEmailShaped(value: string): boolean {
  return value.includes("@");
}

export function splitLines(text: string): string[] {
  return text
    .split(/[\n,]/)
    .map((s) => s.trim())
    .filter((s) => s !== "");
}

export function checkSubscriptions(ids: readonly string[]): string | null {
  if (ids.length === 0) return STRINGS.needSubscription;
  const bad = ids.find((id) => !GUID.test(id));
  return bad === undefined ? null : STRINGS.invalidSubscription(bad);
}

export function checkAttestation(value: string): string | null {
  if (value.trim() === "") return STRINGS.needAttestation;
  return isEmailShaped(value) ? STRINGS.attestationEmail : null;
}

export function isPrincipal(value: string): boolean {
  return PRINCIPAL.test(value);
}
