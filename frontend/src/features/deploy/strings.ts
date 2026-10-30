export const STRINGS = {
  pageTitle: "Deployment",
  pageDescription:
    "Scan, choose and plan a deployment. The plan is advisory: nothing is provisioned, applied or deleted from this page.",
  capabilitiesTitle: "Deployment capabilities",
  capabilitiesDescription:
    "Capability matrix with availability, release status and authorization scope as separate facts.",
  stepsLabel: "Deployment steps",
  steps: ["Scan", "Choices", "Plan"],
  stepOf: (n: number, name: string): string => `Step ${n} of 3: ${name}`,
  back: "Back",
  next: "Next",

  // Step 1
  subscriptionsLabel: "Subscription ids (one per line)",
  subscriptionsHint:
    "Subscription GUIDs to scan. Only subscriptions covered by the consent record are scanned.",
  consentIdLabel: "Consent record id",
  attestationLabel: "Attestation reference",
  attestationHint: "Pseudonymous id or ticket reference. Do not enter an email address or a name.",
  attestationEmail: "Enter a pseudonymous id or ticket reference, not an email address.",
  consentSame: "Consent covers every subscription listed above",
  consentedLabel: "Consented subscriptions (one per line)",
  scanButton: "Run scan",
  scanFailed: "The scan could not be run",
  scanRequired: "Run a scan first.",
  invalidSubscription: (value: string): string => `Not a subscription GUID: ${value}`,
  needSubscription: "Enter at least one subscription id.",
  needConsentId: "A consent record id is required.",
  needAttestation: "An attestation reference is required.",
  scanResultTitle: "Scan result",
  visibilityNoteLabel: "Visibility note",
  scannedAt: "Scanned at",
  subscriptionsTable: "Scanned subscriptions",
  resourcesTable: "Discovered resources",
  noResources: "No resources were discovered in the visible subscriptions.",
  visible: "visible",
  notVisible: "not_visible",

  // Step 2
  profileTitle: "Deployment profile",
  cloudLabel: "Cloud",
  regionLabel: "Region",
  hostingLabel: "Hosting",
  analyticsLabel: "Analytics",
  servicesTitle: "Service choices",
  servicesHint: "Without a choice the planner reuses a discovered candidate, otherwise it creates.",
  decisionDefault: "Planner default",
  resourceIdLabel: "Existing resource id",
  skuLabel: "SKU",
  fallbackLabel: "Fallback when reuse is not possible",
  candidates: "Discovered candidates",
  useCandidate: (name: string): string => `Use ${name}`,
  consentsTitle: "Owner consent records",
  consentsHint:
    "Reusing a shared resource needs a granted owner consent that lists its resource id.",
  ownerConsentId: "Owner consent id",
  ownerPrincipal: "Owner principal (pseudonymous id)",
  ownerResourceIds: "Covered resource ids (one per line)",
  ownerGranted: "Consent granted",
  addConsent: "Add owner consent",
  removeConsent: (id: string): string => `Remove consent ${id}`,
  principalInvalid:
    "Use a pseudonymous id (lowercase letters, digits, . _ : / = -), not an email address.",
  needOwnerConsentId: "An owner consent id is required.",
  needOwnerResources: "List at least one resource id.",
  needGrantedPrincipal: "A granted consent must name an owner principal.",

  // Step 3
  planButton: "Build plan",
  planFailed: "The plan could not be built",
  planTitle: "Plan",
  planTable: "Plan items",
  planNotApplied: "This plan is advisory. Nothing has been provisioned, applied or deleted.",
  warningsTitle: "Capability warnings",
  downloadManifest: "Download manifest (JSON)",
  shared: "shared",
  neurosphereCreated: "neurosphere_created",
  sourceLink: "Source",
  unknown: "unknown",
  columns: {
    service: "Service",
    status: "Status",
    resource: "Resource",
    flags: "Flags",
    checks: "Checks",
    cost: "Cost basis",
    reason: "Disabled reason",
    source: "Source",
  },

  // Capabilities
  capCloud: "Cloud",
  capRegion: "Region (optional)",
  capRegionInvalid: "Use a lowercase region name such as eastus.",
  capApply: "Apply filter",
  capLoading: "Loading capability matrix",
  capFailed: "The capability matrix could not be loaded",
  capEmptyTitle: "No matrix rows",
  capEmptyBody: "No rows match this cloud and region. Absence of a row is not support.",
  capTable: "Capability matrix",
  capMeta: (version: string, observed: string): string =>
    `Matrix version ${version}, observed ${observed}.`,
  capEnabled: "enabled",
  capDisabled: "disabled",
  capColumns: {
    state: "State",
    service: "Service / feature",
    cloud: "Cloud",
    region: "Region",
    sku: "SKU",
    availability: "Availability",
    ga: "GA status",
    scope: "Authorization scope (citation)",
    source: "Source",
    observed: "Observed",
  },
  forbiddenWorkspace: "deployment",
} as const;

export const CLOUD_OPTIONS = ["commercial", "government"] as const;
export type Cloud = (typeof CLOUD_OPTIONS)[number];

/** Regions offered per cloud; a Government profile never lists a Commercial region. */
export const REGIONS: Readonly<Record<Cloud, readonly string[]>> = {
  commercial: ["eastus", "eastus2", "westus2"],
  government: ["usgovvirginia", "usgovarizona"],
};

export const HOSTING_OPTIONS = ["aks", "appservice"] as const;
export const ANALYTICS_OPTIONS = ["fabric", "synapse", "databricks"] as const;
