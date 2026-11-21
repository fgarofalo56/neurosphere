import { createMutationHook, createQueryHook } from "../../../api/index.js";
import { CATALOG_API_PREFIX } from "../paths";
import type {
  AccessDependentsResponse,
  AccessQueryBody,
  AccessQueryResponse,
  RegionGroupsResponse,
} from "./types";

export function accessQueryPath(): string {
  return `${CATALOG_API_PREFIX}/access/query`;
}

export function accessDependentsPath(): string {
  return `${CATALOG_API_PREFIX}/access/dependents`;
}

export function accessRegionGroupsPath(): string {
  return `${CATALOG_API_PREFIX}/access/region-groups`;
}

/** Asks who read or wrote the selected assets. Scope comes from the server identity only. */
export const useAccessQuery = createMutationHook<AccessQueryBody, AccessQueryResponse>({
  mutate: (client, body) => client.post<AccessQueryResponse>(accessQueryPath(), body),
});

export interface DependentsVars {
  readonly nodeId: string;
  readonly maxDepth: number;
}

export const useDependents = createMutationHook<DependentsVars, AccessDependentsResponse>({
  mutate: (client, v) =>
    client.post<AccessDependentsResponse>(accessDependentsPath(), {
      node_id: v.nodeId,
      max_depth: v.maxDepth,
    }),
});

export const useRegionGroups = createQueryHook<Record<string, never>, RegionGroupsResponse>({
  key: "catalog-access-region-groups",
  fetcher: (client, _params, signal) =>
    client.get<RegionGroupsResponse>(accessRegionGroupsPath(), undefined, signal),
});
