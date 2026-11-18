/** Strings shared by the admin console pages, so tests assert exact values. */
export const ADMIN_STRINGS = {
  consoleTitle: "Admin console",
  consoleDescription:
    "Identity, domains, system status and audit search for the deployment administrator and the security auditor. Every control is a usability aid: the API decides access on every request.",
  tabsLabel: "Admin areas",
  areasHeading: "Console areas",
  checklistHeading: "First-run checklist",
  checklistSummary: (done: number, total: number): string =>
    `${done} of ${total} checklist items complete`,
  restartHeading: "Settings awaiting restart",
  restartCount: (n: number): string =>
    n === 1 ? "1 setting needs a restart" : `${n} settings need a restart`,
  summaryUnknown: "Unknown: the system status could not be read.",
  forbidden: "Access denied",
  forbiddenDetail:
    "The service declined this request. If you need access, contact your administrator.",
  forbiddenDeployment:
    "This permission is needed on the whole deployment (the customer control domain), not on a single domain.",
  forbiddenDomain: "This permission is needed on the domain or resource this view reads.",
  forbiddenAccessLink: "See your access",
  access: {
    disclosure: "Your access",
    loading: "Loading your access",
    failed: "Your access could not be read.",
    none: "You hold no NeuroSphere role.",
    overage:
      "Group-based roles were not applied: your token did not list your groups (group overage). Roles from Entra app roles and the policy store still apply.",
    sources: {
      entra_app_role: "Entra app role",
      entra_group: "Entra group",
      policy_store: "Policy store",
    },
    wholeDeployment: "Whole deployment",
    domains: (n: number): string => (n === 1 ? "1 domain" : `${n} domains`),
    expires: (at: string): string => `expires ${at}`,
    noExpiry: "no expiry",
    entry: (id: string): string => `mapping entry ${id}`,
  },
  unavailable: "Could not load this view",
  unavailableDetail: "The request failed. This is not an empty result. Try again later.",
  reference: "Reference",
  retry: "Retry",
  loading: "Loading",
  nextPage: "Next page",
  firstPage: "First page",
  unknown: "Unknown",
  stale:
    "This record changed since you loaded it. Reload the page, review the current state and confirm again.",
  copy: "Copy",
  copied: "Copied",
  none: "None",
} as const;
