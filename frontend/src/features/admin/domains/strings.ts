export const DOMAIN_STRINGS = {
  title: "Domains",
  description:
    "The domain registry. Creating a domain makes it addressable for roles and data; retiring one stops new use. The API decides every change.",
  empty: "No domains are registered.",
  loading: "Loading domains",
  showRetired: "Show retired domains",
  headers: {
    name: "Display name",
    id: "Domain id",
    classification: "Classification",
    region: "Residency region",
    status: "Status",
    control: "Control domain",
    actions: "Actions",
  },
  active: "Active",
  retired: "Retired",
  controlBadge: "Control domain",
  notControl: "No",
  create: "Create domain",
  retire: "Retire",
  controlCannotRetire: "The control domain cannot be retired. The API enforces this.",
  fields: {
    domainId: "Domain id",
    displayName: "Display name",
    classification: "Classification",
    region: "Residency region",
  },
  dialog: {
    create: "Create domain",
    retire: "Retire domain",
    noVersion: "None (new domain)",
    createNote: "Creating a domain takes no reason; the change is recorded on the audit chain.",
    retireNote: "Retiring a domain takes no reason; the change is recorded on the audit chain.",
    readFailed: "Could not read the domain's current version, so nothing was changed.",
  },
  done: (what: string): string => `${what} recorded.`,
} as const;

export const CLASSIFICATIONS = [
  "public",
  "internal",
  "confidential",
  "restricted",
  "unknown",
] as const;
export type Classification = (typeof CLASSIFICATIONS)[number];
