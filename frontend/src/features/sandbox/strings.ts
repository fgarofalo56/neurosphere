/** Every user-visible string for sandbox mode lives here so tests assert exact values. */
export const STRINGS = {
  toggleLabel: "Sandbox mode",
  toggleOn: "On: synthetic data only",
  toggleOff: "Off",
  bannerName: "Sandbox mode: synthetic data only",
  bannerText:
    "Sandbox mode is on. You are working with a synthetic dataset. No real data is read or changed.",
  pageTitle: "Sandbox",
  pageDescription:
    "A shared synthetic dataset for evaluation. The server reads and writes only sandbox containers.",
  loading: "Loading...",
  environment: "Environment",
  synthetic: "Synthetic data",
  yes: "Yes",
  headers: { kind: "Kind", count: "Count" },
  relations: "Relations",
  total: "Total documents",
  kinds: {
    domain: "Domains",
    owner: "Owners",
    person: "People",
    model_deployment: "Model deployments",
    grounding_source: "Grounding sources",
    tool: "Tools",
    agent: "Agents",
    agent_version: "Agent versions",
  },
  forbidden: "You do not have access to the sandbox",
  forbiddenDetail: "It needs the data read permission. Contact your administrator",
  unavailable: "Service unavailable",
  unavailableDetail: "The service could not be reached. This is not an empty result. Try again.",
  retry: "Retry",
} as const;
