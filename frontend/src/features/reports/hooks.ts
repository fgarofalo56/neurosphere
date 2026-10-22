import { useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";
import { createMutationHook, createQueryHook } from "../../api/index.js";
import {
  reportDecisionPath,
  reportPath,
  reportPublicationPath,
  reportRunPath,
  reportSharePath,
  reportSharesPath,
  reportsPath,
} from "./paths";
import type {
  DecideVars,
  DeleteVars,
  ListParams,
  ReportListResponse,
  ReportParams,
  ReportView,
  RunView,
  SaveVars,
  ShareVars,
  UpdateVars,
} from "./types";

const KEYS = ["reports-list", "reports-detail", "reports-run"] as const;

export const useReportList = createQueryHook<ListParams, ReportListResponse>({
  key: "reports-list",
  fetcher: (client, p, signal) =>
    client.get<ReportListResponse>(
      reportsPath(p.domainId),
      {
        publication_state: p.publicationState === "" ? undefined : p.publicationState,
        cursor: p.cursor === "" ? undefined : p.cursor,
        limit: p.limit,
      },
      signal,
    ),
});

export const useReport = createQueryHook<ReportParams, ReportView>({
  key: "reports-detail",
  fetcher: (client, p, signal) =>
    client.get<ReportView>(reportPath(p.domainId, p.reportId), undefined, signal),
});

/**
 * A run is a POST (the server re-validates the plan and re-authorizes as the caller), but it
 * only reads, so it is modelled as a query. Never cached across callers: the key is per report
 * and the server derives the viewer's scope from the bearer token on every request.
 */
export const useReportRun = createQueryHook<ReportParams, RunView>({
  key: "reports-run",
  fetcher: (client, p, signal) =>
    client.post<RunView>(reportRunPath(p.domainId, p.reportId), undefined, signal),
});

/** Save-from-plan: also the entry point the copilot chat panel uses. */
export const useSaveReport = createMutationHook<SaveVars, ReportView>({
  mutate: (client, v) => client.post<ReportView>(reportsPath(v.domainId), v.body),
});

export const useUpdateReport = createMutationHook<UpdateVars, ReportView>({
  mutate: (client, v) => client.put<ReportView>(reportPath(v.domainId, v.reportId), v.body, v.etag),
});

export const useDeleteReport = createMutationHook<DeleteVars, undefined>({
  mutate: (client, v) =>
    client.request<undefined>({
      method: "DELETE",
      path: reportPath(v.domainId, v.reportId),
      ifMatch: v.etag,
    }),
});

export const useShareReport = createMutationHook<ShareVars, ReportView>({
  mutate: (client, v) =>
    client.post<ReportView>(reportSharesPath(v.domainId, v.reportId), {
      principal_id: v.principalId,
    }),
});

export const useUnshareReport = createMutationHook<ShareVars, ReportView>({
  mutate: (client, v) =>
    client.delete<ReportView>(reportSharePath(v.domainId, v.reportId, v.principalId)),
});

export const useRequestPublication = createMutationHook<ReportParams, ReportView>({
  mutate: (client, v) => client.post<ReportView>(reportPublicationPath(v.domainId, v.reportId)),
});

export const useDecidePublication = createMutationHook<DecideVars, ReportView>({
  mutate: (client, v) =>
    client.post<ReportView>(reportDecisionPath(v.domainId, v.reportId), {
      decision: v.decision,
      ...(v.reason !== undefined && v.reason !== "" ? { reason: v.reason } : {}),
    }),
});

/** Refetch lists and details after a mutation. Runs are refetched too: sharing can change them. */
export function useInvalidateReports(): () => Promise<void> {
  const queryClient = useQueryClient();
  return useCallback(async () => {
    await Promise.all(KEYS.map((key) => queryClient.invalidateQueries({ queryKey: [key] })));
  }, [queryClient]);
}
