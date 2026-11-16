export const PRODUCER_STRINGS = {
  title: "Ingest producers",
  description:
    "Producers send telemetry to the ingest API. A producer secret is generated once and shown once; only a reference to it is ever stored.",
  loading: "Loading producers",
  empty: "No producers are registered yet.",
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
