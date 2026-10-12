/**
 * Role display helpers.
 *
 * IMPORTANT: claims NEVER grant access. These values are for display and
 * navigation visibility only (C9). The API (PRP-06) is the only enforcement
 * point and decides authorization server-side on every request.
 */
export const NS_ROLES = ["Viewer", "Analyst", "Steward", "Admin", "Auditor"] as const;
export type NsRole = (typeof NS_ROLES)[number];

export const NO_ROLES_LABEL = "no roles";

const ALIASES: Readonly<Record<string, NsRole>> = {
  viewer: "Viewer",
  analyst: "Analyst",
  pro: "Analyst",
  steward: "Steward",
  domainsteward: "Steward",
  owner: "Steward",
  domainowner: "Steward",
  admin: "Admin",
  securityauditor: "Auditor",
  auditor: "Auditor",
};

function normalise(value: string): string {
  return value.toLowerCase().replace(/[\s_.\-/]+/g, "");
}

/** Maps a raw `roles` claim value to the recognised NS-08 roles (display only). */
export function parseRoles(claim: unknown): NsRole[] {
  const values: unknown[] = Array.isArray(claim) ? claim : typeof claim === "string" ? [claim] : [];
  const found = new Set<NsRole>();
  for (const v of values) {
    if (typeof v !== "string") continue;
    const role = ALIASES[normalise(v)];
    if (role !== undefined) found.add(role);
  }
  return NS_ROLES.filter((r) => found.has(r));
}

export function rolesLabel(roles: readonly NsRole[]): string {
  return roles.length === 0 ? NO_ROLES_LABEL : roles.join(", ");
}
