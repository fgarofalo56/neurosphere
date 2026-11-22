/** Wire types of `GET /api/v1/sources/status` (PRP-139). No id, name or host is ever returned. */
export const SOURCE_KEYS = [
  "foundry",
  "apim_gateway",
  "billing",
  "azure_monitor_telemetry",
] as const;
export type SourceKey = (typeof SOURCE_KEYS)[number];

export type SourceState = "not_connected" | "connected_no_data" | "connected" | "failing";

export interface SourceStatusEntry {
  readonly source: SourceKey;
  readonly state: SourceState;
  readonly last_success_at: string | null;
  readonly available: boolean;
}

export interface SourceStatusResponse {
  readonly sources: readonly SourceStatusEntry[];
}
