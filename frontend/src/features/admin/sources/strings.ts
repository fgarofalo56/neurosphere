export const PRODUCER_STRINGS = {
  title: "Ingest producers",
  description:
    "Producers send telemetry to the ingest API. A producer secret is generated once and shown once; only a reference to it is ever stored.",
  loading: "Loading producers",
  empty: "No producers are registered yet.",
  emptyHint:
    "Producers push telemetry in. To pull data from Azure instead, connect a source on the Connectors page.",
  create: "Create producer",
  headers: {
    id: "Producer",
    cloud: "Cloud",
    sources: "Sources",
    status: "Status",
    rotated: "Last rotated",
    actions: "Actions",
  },
  never: "Never rotated",
  active: "Active",
  disabled: "Disabled",
  rotate: "Rotate secret",
  disable: "Disable",
  enable: "Enable",
  fields: {
    producerId: "Producer id",
    cloud: "Cloud",
    sources: "Sources (one per line: source_id kind)",
  },
  sourcesHint: "Kinds: gateway, application, billing. Example: apim-main gateway",
  sourcesInvalid: "Each line needs a source id and one of gateway, application, billing.",
  dialog: {
    create: "Create producer",
    rotate: "Rotate producer secret",
    disable: "Disable producer",
    enable: "Enable producer",
    noVersion: "New producer",
    rotateNote:
      "Rotating issues a new secret and invalidates the old one. The new secret is shown once.",
    readFailed: "Could not read the producer before changing it.",
  },
  secret: {
    title: "Producer secret",
    warning:
      "Copy this secret now. It is shown once and cannot be displayed again. Store it in your secret store.",
    label: "Secret",
    copy: "Copy secret",
    copied: "Secret copied to the clipboard",
    confirm: "I stored it",
  },
  done: (what: string): string => `${what}: done.`,
} as const;

/** The Azure role each connector kind needs, and on what kind of resource (PRP-139 Sources table). */
const ACCESS_DENIED: Readonly<Record<string, string>> = {
  foundry_discovery:
    "Access denied: the role Foundry User is missing on the Foundry account. The owner of that account must approve the access.",
  gateway_poll:
    "Access denied: the role Log Analytics Data Reader is missing on the gateway's Log Analytics workspace (registration also needs API Management Service Reader on the API Management service). The owner of those resources must approve the access.",
  billing_export:
    "Access denied: the role Storage Blob Data Reader is missing on the export storage account. The owner of that storage account must approve the access.",
  azure_monitor_ai:
    "Access denied: the role Log Analytics Data Reader is missing on the Log Analytics workspace behind the Application Insights resource (Privileged Monitoring Data Reader is also needed when its tables are protected). The owner of that workspace must approve the access.",
};
const ACCESS_DENIED_GENERIC =
  "Access denied: an Azure role the connector needs is missing. The owner of the resource must approve the access.";

const REASON_SENTENCES: Readonly<Record<string, string>> = {
  source_unreachable: "The source could not be reached on the last run. It will be tried again.",
  partial_results: "The last run read only part of the data. The rest will be retried.",
  ingest_failed: "The data was read but could not be stored. It will be retried.",
  cloud_not_supported: "This source is not supported in this cloud.",
  incomplete_export:
    "The export is not complete yet, for example a month that is still open. Only closed months are read.",
  unchanged: "Nothing changed since the last successful run.",
  tick_error: "The last run stopped on an internal error. It will be tried again.",
  awaiting_first_run: "Configured, waiting for the first run.",
  query_budget_exhausted:
    "The last run stopped at its limit on queries. It continues from where it stopped on the next run.",
  event_budget_exhausted:
    "The last run stopped at its limit on events. It continues from where it stopped on the next run.",
  rate_limited:
    "The source asked the reader to slow down. The reader waited and will continue on the next run.",
  stalled:
    "The last run made no progress. The reader keeps its place and will try again on the next run.",
  cloud_mismatch:
    "The configuration or the producer belongs to a different cloud than this deployment. Nothing was read.",
  refused_government_unverified:
    "Reading this source in Azure Government is not enabled. An administrator must allow unverified Government use first. Nothing was read.",
};

export const SOURCE_STRINGS = {
  panelTitle: "First sources",
  panelIntro:
    "The four places NeuroSphere can read from. Each reads metadata only, with the managed identity of the deployment; no key or connection string is entered here.",
  headers: {
    source: "Source",
    state: "State",
    lastSuccess: "Last success",
    access: "Access needed",
    action: "Action",
  },
  connect: "Connect",
  connectLabel: (name: string): string => `Connect ${name}`,
  notAvailableAction: "Not available",
  noSuccess: "No successful run yet",
  statusUnavailable: "status unavailable",
  statusColumnUnavailable: "Status unavailable",
  statusNote:
    "Run status could not be loaded (it needs customer-level configuration access). The rest of the page works.",
  noRunStatus: "No run status for this kind",
  sources: {
    foundry: "Azure AI Foundry",
    apim_gateway: "API Management AI gateways",
    billing: "Cost and billing",
    azure_monitor_telemetry: "Azure Monitor and Application Insights",
  },
  /** Connector kind that the Connect action pre-sets; absent for the source that is not available. */
  connectKind: {
    foundry: "foundry_discovery",
    apim_gateway: "gateway_poll",
    billing: "billing_export",
    azure_monitor_telemetry: "azure_monitor_ai",
  },
  /** Settings pre-filled by the Connect action; the operator adds the workspace ids. */
  connectTemplate: {
    azure_monitor_ai:
      "interval_seconds=300\nproducer_id=azure-monitor-ai\nsource_id=azure-monitor-ai\napi_base_url=",
  } as Readonly<Record<string, string>>,
  access: {
    foundry:
      "Reads agents and model deployments of the Foundry projects you name. Needs the Foundry User role on each Foundry account, granted to the workers identity. Metadata only; managed identity; no key or connection string.",
    apim_gateway:
      "Reads gateway and LLM log rows (token counts, model, status, latency; no bodies or headers) from the gateway's Log Analytics workspace. Needs Log Analytics Data Reader on that workspace for the workers identity and API Management Service Reader on the API Management service for registration. Managed identity; no key or connection string.",
    billing:
      "Reads the CSV files of a Cost Management export you already created, for closed months. Needs Storage Blob Data Reader on the export storage account for the workers identity. Metadata only; managed identity; no key or connection string.",
    azure_monitor_telemetry:
      "Reads call spans of AI workloads (model, tokens, status, latency; never prompts, completions or message content) from the Log Analytics workspace behind your Application Insights resource. Needs Log Analytics Data Reader on that workspace for the workers identity, and Privileged Monitoring Data Reader as well if the tables are protected; the owner of the workspace approves both. Metadata only; managed identity for reads; the producer secret is a Key Vault reference; no key, connection string or instrumentation key.",
  },
  state: {
    not_connected: "Not connected",
    connected_no_data: "Connected, no data yet",
    connected: "Connected",
    failing: "Failing",
  },
  runState: {
    ok: "OK",
    partial: "Partly worked",
    failed: "Failed",
    idle: "Idle",
    not_configured: "Not configured",
  },
  /** One human sentence per reason code; an unknown code gets a generic sentence. */
  reasonText: (code: string | null, kind: string | null): string | null => {
    if (code === null) return null;
    if (code === "source_access_denied") {
      return (kind === null ? undefined : ACCESS_DENIED[kind]) ?? ACCESS_DENIED_GENERIC;
    }
    return (
      REASON_SENTENCES[code] ??
      "The last run reported a condition this page does not describe. Check the worker logs."
    );
  },
  producersEmptyLink: "Connect a source on the Connectors page",
} as const;

export const CONNECTOR_STRINGS = {
  title: "Connector configurations",
  description:
    "Connectors pull data in. Each holds bounded settings and a credential reference, never a credential value.",
  loading: "Loading connectors",
  empty: "No connector configurations yet.",
  create: "Create connector",
  edit: "Replace",
  enable: "Enable",
  disable: "Disable",
  retire: "Retire",
  headers: {
    id: "Connector",
    kind: "Kind",
    domains: "Domains",
    credential: "Credential",
    status: "Status",
    warnings: "Warnings",
    runStatus: "Run status",
    actions: "Actions",
  },
  fields: {
    id: "Connector id",
    kind: "Connector kind",
    domains: "Domains",
    settings: "Settings (one per line: name=value)",
    enabled: "Enabled",
  },
  settingsHint: "Scalar values only. Names such as secret, token or key are refused by the API.",
  azureMonitorHint:
    "For Azure Monitor: workspace_ids (1 to 4 workspace GUIDs, comma separated), interval_seconds (60 or more), producer_id, source_id and api_base_url. The credential is the Key Vault reference of the producer secret; a managed identity is refused. One domain only.",
  settingsInvalid: "Each line must look like name=value with a lower-case name.",
  restartNote:
    "Changes apply after the API and workers restart. For a Key Vault reference, grant the runtime identity the Key Vault Secrets User role on that vault.",
  dialog: {
    create: "Create connector",
    replace: "Replace connector configuration",
    enable: "Enable connector",
    disable: "Disable connector",
    retire: "Retire connector",
    noVersion: "New connector",
    readFailed: "Could not read the connector before changing it.",
  },
  warningText: (code: string): string =>
    code === "producer_not_in_store"
      ? "producer_not_in_store: the producer this connector uses is not registered in the producer store."
      : code,
  done: (what: string): string => `${what}: done.`,
} as const;
