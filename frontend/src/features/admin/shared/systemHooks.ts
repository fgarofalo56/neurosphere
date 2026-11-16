import { createQueryHook } from "../../../api/index.js";
import { systemPaths } from "./adminPaths";

/** Read-only views of the PRP-45 system routes. Fields not listed here are never read. */
export type ComponentState = "ok" | "failed" | "disabled" | "not_built";

export interface ComponentView {
  readonly name: string;
  readonly state: ComponentState;
  readonly required: boolean;
  readonly reason: string | null;
  readonly blocks_readiness: boolean;
  readonly step: boolean;
}

export interface StoredSettingsState {
  readonly status: "loaded" | "unavailable" | "unconfigured";
  readonly reason: string | null;
  readonly invalid_keys: readonly string[];
}

export interface SystemStatusView {
  readonly ready: boolean;
  readonly components: readonly ComponentView[];
  readonly stored_settings: StoredSettingsState;
}

export type ChecklistStatus = "complete" | "missing" | "disabled" | "not_applicable" | "error";

export interface ChecklistItemView {
  readonly item_id: string;
  readonly component: string;
  readonly status: ChecklistStatus;
  readonly reason: string | null;
  readonly doc_path: string | null;
  readonly required: boolean;
}

export interface ChecklistPageView {
  readonly items: readonly ChecklistItemView[];
}

export interface SettingSummary {
  readonly key: string;
  readonly source: "stored" | "env" | "default";
  readonly restart_required: boolean;
}

export interface SettingsPageView {
  readonly items: readonly SettingSummary[];
  readonly stored_settings: StoredSettingsState;
}

export const useSystemStatus = createQueryHook<Record<string, never>, SystemStatusView>({
  key: "admin-system-status",
  fetcher: (client, _p, signal) =>
    client.get<SystemStatusView>(systemPaths.status(), undefined, signal),
});

export const useChecklist = createQueryHook<Record<string, never>, ChecklistPageView>({
  key: "admin-system-checklist",
  fetcher: (client, _p, signal) =>
    client.get<ChecklistPageView>(systemPaths.checklist(), undefined, signal),
});

export const useSettings = createQueryHook<Record<string, never>, SettingsPageView>({
  key: "admin-system-settings",
  fetcher: (client, _p, signal) =>
    client.get<SettingsPageView>(systemPaths.settings(), undefined, signal),
});

/** Items with a status the console can count; a malformed body yields undefined (unknown). */
export function checklistCounts(
  page: ChecklistPageView | undefined,
): { done: number; total: number } | undefined {
  if (page === undefined || !Array.isArray(page.items)) return undefined;
  const counted = page.items.filter((i) => i.status !== "not_applicable");
  return { done: counted.filter((i) => i.status === "complete").length, total: counted.length };
}

export function restartCount(page: SettingsPageView | undefined): number | undefined {
  if (page === undefined || !Array.isArray(page.items)) return undefined;
  return page.items.filter((i) => i.restart_required).length;
}
