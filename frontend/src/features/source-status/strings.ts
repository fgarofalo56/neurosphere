import type { SourceKey } from "./types";

export const SOURCE_STATUS_PATH = "/api/v1/sources/status";
export const CONNECTORS_HREF = "/admin/sources/connectors";

export const SOURCE_LABELS: Readonly<Record<SourceKey, string>> = {
  foundry: "Azure AI Foundry",
  apim_gateway: "API Management gateways",
  billing: "Cost and billing",
  azure_monitor_telemetry: "Azure Monitor telemetry",
};

export const STRINGS = {
  connectLink: "Connect a source in Admin Sources",
  askAdmin: "Ask an administrator to connect a source",
  notConnectedPrefix: "Nothing is connected for this page yet. Missing source:",
  notConnectedPrefixPlural: "Nothing is connected for this page yet. Missing sources:",
  failingSuffix: "(failing; check its run status)",
  unavailableSuffix: "(not available in this release)",
  notArrivedYet: "The sources are connected, but data has not arrived yet.",
  lastSuccess: (when: string): string => `Last successful read: ${when}.`,
  noSuccessYet: "No successful read has been recorded yet.",
} as const;
