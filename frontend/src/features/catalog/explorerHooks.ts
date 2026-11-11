import {
  useInfiniteQuery,
  useQueryClient,
  type InfiniteData,
  type UseInfiniteQueryResult,
} from "@tanstack/react-query";
import { useCallback } from "react";
import {
  createMutationHook,
  createQueryHook,
  useApiClient,
  type ApiClient,
  type ApiError,
} from "../../api/index.js";
import {
  domainEntitiesPath,
  domainEntityPath,
  domainExportPath,
  domainSearchPath,
  entityDeprecatePath,
  entityPath,
  entityRecertifyPath,
  lineageImpactPath,
  lineageNeighborsPath,
  recertificationsPath,
  staleAgentsConfirmPath,
  staleAgentsDryRunPath,
} from "./paths";
import type { ReasonCode } from "./reasonCodes";
import type {
  BudgetBody,
  CatalogEntityView,
  EntityListPage,
  EntityTypeName,
  ExportPageView,
  GraphResultView,
  LifecycleName,
  RecertificationPageView,
  RecertInclude,
  StaleAgentOutcomeView,
  StaleAgentPlanView,
  StaleCandidateView,
} from "./explorerTypes";

export const LIST_PAGE_SIZE = 25;
const SEARCH_BUDGET: BudgetBody = { timeout_ms: 5000, limit: 50, max_depth: 0 };
const LINEAGE_BUDGET: BudgetBody = {
  timeout_ms: 5000,
  limit: 50,
  max_depth: 2,
  max_nodes: 50,
  max_edges: 100,
};

export interface ListParams {
  readonly domain: string;
  readonly entityType: EntityTypeName | "";
  readonly lifecycle: LifecycleName | "";
}

/** Cursor-paged list; the domain is a path segment (the client refuses `domain_id` elsewhere). */
export function useEntityList(
  params: ListParams,
  enabled: boolean,
): UseInfiniteQueryResult<InfiniteData<EntityListPage, string | undefined>, ApiError> {
  const client = useApiClient();
  return useInfiniteQuery<
    EntityListPage,
    ApiError,
    InfiniteData<EntityListPage, string | undefined>,
    unknown[],
    string | undefined
  >({
    queryKey: ["catalog-explorer-list", params],
    enabled: enabled && params.domain !== "",
    initialPageParam: undefined,
    queryFn: ({ pageParam, signal }) =>
      client.get<EntityListPage>(
        domainEntitiesPath(params.domain),
        {
          page_size: LIST_PAGE_SIZE,
          entity_type: params.entityType === "" ? undefined : params.entityType,
          lifecycle: params.lifecycle === "" ? undefined : params.lifecycle,
          cursor: pageParam,
        },
        signal,
      ),
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  });
}

export interface SearchParams {
  readonly domain: string;
  readonly term: string;
  readonly entityType: EntityTypeName | "";
}

export const useEntitySearch = createQueryHook<SearchParams, GraphResultView>({
  key: "catalog-explorer-search",
  fetcher: async (client, p, signal) =>
    client.request<GraphResultView>({
      method: "POST",
      path: domainSearchPath(p.domain),
      body: {
        term: p.term,
        ...(p.entityType === "" ? {} : { entity_types: [p.entityType] }),
        budget: SEARCH_BUDGET,
      },
      signal,
    }),
});

export interface ExportRequest {
  readonly domain: string;
  readonly entityType: EntityTypeName | "";
  readonly lifecycle: LifecycleName | "";
  readonly cursor: string | undefined;
}

export function fetchExportPage(client: ApiClient, p: ExportRequest): Promise<ExportPageView> {
  return client.get<ExportPageView>(domainExportPath(p.domain), {
    page_size: 100,
    entity_type: p.entityType === "" ? undefined : p.entityType,
    lifecycle: p.lifecycle === "" ? undefined : p.lifecycle,
    cursor: p.cursor,
  });
}

export const useEntity = createQueryHook<{ readonly entityId: string }, CatalogEntityView>({
  key: "catalog-explorer-entity",
  fetcher: (client, p, signal) =>
    client.get<CatalogEntityView>(entityPath(p.entityId), undefined, signal),
});

export interface NeighborsParams {
  readonly entityId: string;
}

export const useNeighbors = createQueryHook<NeighborsParams, GraphResultView>({
  key: "catalog-explorer-neighbors",
  fetcher: (client, p, signal) =>
    client.request<GraphResultView>({
      method: "POST",
      path: lineageNeighborsPath(),
      body: { node_id: p.entityId, direction: "both", budget: LINEAGE_BUDGET },
      signal,
    }),
});

export interface ImpactParams {
  readonly entityId: string;
  readonly direction: "downstream" | "upstream";
}

export const useImpact = createQueryHook<ImpactParams, GraphResultView>({
  key: "catalog-explorer-impact",
  fetcher: (client, p, signal) =>
    client.request<GraphResultView>({
      method: "POST",
      path: lineageImpactPath(),
      body: { node_id: p.entityId, direction: p.direction, budget: LINEAGE_BUDGET },
      signal,
    }),
});

export interface DeprecateVars {
  readonly entityId: string;
  readonly etag: string;
  readonly reasonCode?: ReasonCode;
}

export const useDeprecate = createMutationHook<DeprecateVars, CatalogEntityView>({
  mutate: (client, v) =>
    client.request<CatalogEntityView>({
      method: "POST",
      path: entityDeprecatePath(v.entityId),
      ...(v.reasonCode !== undefined && { body: { reason_code: v.reasonCode } }),
      ifMatch: v.etag,
    }),
});

export interface RecertifyVars extends DeprecateVars {
  readonly validForDays: number;
}

export const useRecertify = createMutationHook<RecertifyVars, CatalogEntityView>({
  mutate: (client, v) =>
    client.request<CatalogEntityView>({
      method: "POST",
      path: entityRecertifyPath(v.entityId),
      body: {
        valid_for_days: v.validForDays,
        ...(v.reasonCode !== undefined && { reason_code: v.reasonCode }),
      },
      ifMatch: v.etag,
    }),
});

export interface CreateEntityVars {
  readonly domain: string;
  /** The entity document without any server-owned key (see entityFormModel.ts). */
  readonly body: Readonly<Record<string, unknown>>;
}

/** Item 13: the domain rides in the path; the body carries no scope or server-owned key. */
export const useCreateEntity = createMutationHook<CreateEntityVars, CatalogEntityView>({
  mutate: (client, v) => client.post<CatalogEntityView>(domainEntitiesPath(v.domain), v.body),
});

export interface UpdateEntityVars extends CreateEntityVars {
  readonly entityId: string;
  readonly etag: string;
}

export const useUpdateEntity = createMutationHook<UpdateEntityVars, CatalogEntityView>({
  mutate: (client, v) =>
    client.put<CatalogEntityView>(domainEntityPath(v.domain, v.entityId), v.body, v.etag),
});

/** Re-reads the entity and its lineage after a change or a 409. */
export function useReloadEntity(): () => Promise<void> {
  const queryClient = useQueryClient();
  return useCallback(async () => {
    await queryClient.invalidateQueries({ queryKey: ["catalog-explorer-list"] });
    await queryClient.invalidateQueries({ queryKey: ["catalog-explorer-search"] });
    await queryClient.invalidateQueries({ queryKey: ["catalog-explorer-entity"] });
    await queryClient.invalidateQueries({ queryKey: ["catalog-explorer-neighbors"] });
    await queryClient.invalidateQueries({ queryKey: ["catalog-explorer-impact"] });
  }, [queryClient]);
}

export interface RecertParams {
  readonly withinDays: number;
  readonly include: RecertInclude;
}

export function useRecertifications(
  params: RecertParams,
): UseInfiniteQueryResult<InfiniteData<RecertificationPageView, string | undefined>, ApiError> {
  const client = useApiClient();
  return useInfiniteQuery<
    RecertificationPageView,
    ApiError,
    InfiniteData<RecertificationPageView, string | undefined>,
    unknown[],
    string | undefined
  >({
    queryKey: ["catalog-explorer-recertifications", params],
    initialPageParam: undefined,
    queryFn: ({ pageParam, signal }) =>
      client.get<RecertificationPageView>(
        recertificationsPath(),
        {
          within_days: params.withinDays,
          include: params.include,
          page_size: 50,
          cursor: pageParam,
        },
        signal,
      ),
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  });
}

export const useStaleDryRun = createMutationHook<
  { readonly windowDays: number },
  StaleAgentPlanView
>({
  mutate: (client, v) =>
    client.post<StaleAgentPlanView>(staleAgentsDryRunPath(), { window_days: v.windowDays }),
});

/** Echoes the dry-run plan back; only agent id and etag of each candidate are sent. */
export const useStaleConfirm = createMutationHook<
  { readonly plan: StaleAgentPlanView },
  StaleAgentOutcomeView
>({
  mutate: (client, v) =>
    client.post<StaleAgentOutcomeView>(staleAgentsConfirmPath(), {
      plan_id: v.plan.plan_id,
      as_of: v.plan.as_of,
      window_days: v.plan.window_days,
      candidates: v.plan.candidates.map((c: StaleCandidateView) => ({
        agent_id: c.agent_id,
        etag: c.etag,
      })),
    }),
});
