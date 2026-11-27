import type { NsRole } from "../../../auth/roles";
import {
  ADMIN_AUDIT_ROUTE,
  ADMIN_DOMAINS_ROUTE,
  ADMIN_IDENTITY_ROUTE,
  ADMIN_SYSTEM_ROUTE,
} from "./adminPaths";
import {
  ADMIN_CATALOG_IMPORT_ROUTE,
  ADMIN_CONNECTORS_ROUTE,
  ADMIN_FEATURES_ROUTE,
  ADMIN_GATEWAYS_ROUTE,
  ADMIN_PRICING_ROUTE,
  ADMIN_PRODUCERS_ROUTE,
  ADMIN_REVIEW_POLICY_ROUTE,
} from "../sources/apiPaths";
import { ADMIN_CAPTURE_ROUTE } from "../capture/paths";
import { ADMIN_NOTIFICATIONS_ROUTE } from "../notifications/paths";

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
  // PRP-57: data sources, pricing and feature settings.
  {
    id: "producers",
    label: "Producers",
    to: `/${ADMIN_PRODUCERS_ROUTE}`,
    description: "Ingest producers: create, rotate the secret once, disable.",
    roles: ["Admin"],
  },
  {
    id: "connectors",
    label: "Connectors",
    to: `/${ADMIN_CONNECTORS_ROUTE}`,
    description: "Connector configurations with credential references.",
    roles: ["Admin"],
  },
  {
    id: "gateways",
    label: "Gateways",
    to: `/${ADMIN_GATEWAYS_ROUTE}`,
    description: "Register an API Management gateway.",
    roles: ["Admin"],
  },
  {
    id: "catalog-import",
    label: "Catalog import",
    to: `/${ADMIN_CATALOG_IMPORT_ROUTE}`,
    description: "Import catalog entities, dry run first.",
    roles: ["Admin"],
  },
  {
    id: "pricing",
    label: "Pricing",
    to: `/${ADMIN_PRICING_ROUTE}`,
    description: "Price sheets and budgets.",
    roles: ["Admin"],
  },
  {
    id: "features",
    label: "Features",
    to: `/${ADMIN_FEATURES_ROUTE}`,
    description: "Models and feature settings.",
    roles: ["Admin"],
  },
  {
    id: "review-policy",
    label: "Review policy",
    to: `/${ADMIN_REVIEW_POLICY_ROUTE}`,
    description: "Approval rules, SLAs and escalation for human review.",
    roles: ["Admin"],
  },
  // PRP-103 item 5: read-only interaction capture policies and status.
  {
    id: "capture",
    label: "Interaction capture",
    to: `/${ADMIN_CAPTURE_ROUTE}`,
    description: "Capture policies, capture status, off reasons and counters (read-only).",
    roles: ["Admin"],
  },
  // PRP-107 item 7: notification channels, subscriptions and deliveries.
  {
    id: "notifications",
    label: "Notifications",
    to: `/${ADMIN_NOTIFICATIONS_ROUTE}`,
    description: "Channels, subscriptions and delivery status for governance alerts.",
    roles: ["Admin"],
  },
];
