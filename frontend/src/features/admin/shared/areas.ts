import type { NsRole } from "../../../auth/roles";
import {
  ADMIN_AUDIT_ROUTE,
  ADMIN_DOMAINS_ROUTE,
  ADMIN_IDENTITY_ROUTE,
  ADMIN_SYSTEM_ROUTE,
} from "./adminPaths";

export interface AdminArea {
  readonly id: string;
  readonly label: string;
  readonly to: string;
  readonly description: string;
  /** Cosmetic nav hint only; the API decides every request. */
  readonly roles: readonly NsRole[];
}

/**
 * The admin console areas. `AdminTabs` and the console landing render this list. PRP-57 may only
 * append entries.
 */
export const ADMIN_AREAS: readonly AdminArea[] = [
  {
    id: "identity",
    label: "Identity",
    to: `/${ADMIN_IDENTITY_ROUTE}`,
    description: "Users, roles, domain scopes, grants and revocation.",
    roles: ["Admin"],
  },
  {
    id: "domains",
    label: "Domains",
    to: `/${ADMIN_DOMAINS_ROUTE}`,
    description: "The domain registry: create and retire domains.",
    roles: ["Admin"],
  },
  {
    id: "system",
    label: "System",
    to: `/${ADMIN_SYSTEM_ROUTE}`,
    description: "Component status, first-run checklist and stored settings.",
    roles: ["Admin"],
  },
  {
    id: "audit",
    label: "Audit search",
    to: `/${ADMIN_AUDIT_ROUTE}`,
    description: "Search, denials, SIEM sink status and export.",
    roles: ["Admin", "Auditor"],
  },
];
