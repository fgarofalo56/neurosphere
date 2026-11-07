import { createMutationHook, createQueryHook } from "../../api/index.js";
import {
  applyPlanPath,
  approvePlanPath,
  capabilitiesPath,
  deployPlanPath,
  deployScanPath,
  uninstallPreviewPath,
} from "./paths";
import type {
  ApplyRequest,
  ApplyView,
  ApprovedPlanView,
  ApprovePlanRequest,
  CapabilityMatrixView,
  CapabilityRow,
  DomainVars,
  PlanRequest,
  PlanResponse,
  ScanRequest,
  ScanResponse,
  UninstallPreviewRequest,
  UninstallPreviewView,
} from "./types";

export const useScan = createMutationHook<ScanRequest, ScanResponse>({
  mutate: (client, body) => client.post<ScanResponse>(deployScanPath(), body),
});

export const usePlan = createMutationHook<PlanRequest, PlanResponse>({
  mutate: (client, body) => client.post<PlanResponse>(deployPlanPath(), body),
});

export const useApprovePlan = createMutationHook<DomainVars<ApprovePlanRequest>, ApprovedPlanView>({
  mutate: (client, v) => client.post<ApprovedPlanView>(approvePlanPath(v.domainId), v.body),
});

export const useApplyPlan = createMutationHook<DomainVars<ApplyRequest>, ApplyView>({
  mutate: (client, v) => client.post<ApplyView>(applyPlanPath(v.domainId), v.body),
});

export const useUninstallPreview = createMutationHook<
  DomainVars<UninstallPreviewRequest>,
  UninstallPreviewView
>({
  mutate: (client, v) =>
    client.post<UninstallPreviewView>(uninstallPreviewPath(v.domainId), v.body),
});

export interface CapabilityFilter {
  readonly cloud: "commercial" | "government";
  readonly region: string;
}

export const useCapabilities = createQueryHook<CapabilityFilter, CapabilityMatrixView>({
  key: "deploy-capabilities",
  fetcher: (client, f, signal) =>
    client.get<CapabilityMatrixView>(
      capabilitiesPath(),
      { cloud: f.cloud, ...(f.region === "" ? {} : { region: f.region }) },
      signal,
    ),
});

/**
 * A row is enabled only when the source says `available`. preview, unavailable and unverified rows
 * are disabled with their reason; the UI never upgrades a row, and a row of another cloud is
 * never enabled for the selected one.
 */
export function rowState(
  row: CapabilityRow,
  cloud: "commercial" | "government",
): { readonly enabled: boolean; readonly reason: string | null } {
  if (row.cloud !== cloud) return { enabled: false, reason: `Offered in ${row.cloud} only` };
  if (row.availability === "available") return { enabled: true, reason: null };
  const base = `Availability is ${row.availability}`;
  return { enabled: false, reason: row.notes === null ? base : `${base}. ${row.notes}` };
}
