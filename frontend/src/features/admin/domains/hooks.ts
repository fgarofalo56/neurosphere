import { useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";
import { createQueryHook } from "../../../api/index.js";
import { platformPaths } from "../shared/adminPaths";
import { useEtagMutation } from "../shared/transport";

/** The PRP-44 domain view the registry page reads. */
export interface DomainView {
  readonly domain_id: string;
  readonly display_name: string;
  readonly classification: string;
  readonly residency_region: string;
  readonly status: string;
  readonly is_control_domain: boolean;
  readonly version: number;
}

export interface DomainPageView {
  readonly items: readonly DomainView[];
}

export interface DomainListParams {
  readonly includeRetired: boolean;
}

export const useDomains = createQueryHook<DomainListParams, DomainPageView>({
  key: "admin-domains",
  fetcher: (client, p, signal) =>
    client.get<DomainPageView>(
      platformPaths.domains(),
      { include_retired: p.includeRetired, limit: 200 },
      signal,
    ),
});

/** Reads one domain to get its current ETag before a retire is confirmed. */
export function useReadDomain() {
  return useEtagMutation<string, DomainView>((domainId) => ({
    method: "GET",
    path: platformPaths.domain(domainId),
  }));
}

export interface CreateDomainVars {
  readonly domainId: string;
  readonly displayName: string;
  readonly classification: string;
  readonly residencyRegion: string;
}

export function useCreateDomain() {
  return useEtagMutation<CreateDomainVars, DomainView>((v) => ({
    method: "POST",
    path: platformPaths.domains(),
    body: {
      schema_version: "1.0.0",
      domain_id: v.domainId,
      display_name: v.displayName,
      classification: v.classification,
      residency_region: v.residencyRegion,
      status: "active",
      is_control_domain: false,
    },
  }));
}

export interface RetireDomainVars {
  readonly domainId: string;
  readonly etag: string | undefined;
}

export function useRetireDomain() {
  return useEtagMutation<RetireDomainVars, DomainView>((v) => ({
    method: "POST",
    path: platformPaths.retire(v.domainId),
    ifMatch: v.etag,
  }));
}

export function useInvalidateDomains(): () => Promise<void> {
  const queryClient = useQueryClient();
  return useCallback(
    () => queryClient.invalidateQueries({ queryKey: ["admin-domains"] }),
    [queryClient],
  );
}
