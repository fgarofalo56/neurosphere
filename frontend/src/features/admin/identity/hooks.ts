import { useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";
import { createQueryHook } from "../../../api/index.js";
import { identityPaths } from "../shared/adminPaths";
import { useAdminGet, useEtagMutation, type AdminRequest } from "../shared/transport";
import type { PrincipalListParams, PrincipalPageView, PrincipalSummary } from "./types";

export const usePrincipals = createQueryHook<PrincipalListParams, PrincipalPageView>({
  key: "admin-principals",
  fetcher: (client, p, signal) =>
    client.get<PrincipalPageView>(
      identityPaths.principals(),
      { cursor: p.cursor === "" ? undefined : p.cursor, limit: p.limit },
      signal,
    ),
});

/** The detail read keeps the ETag header: every change is bound to it through If-Match. */
export function usePrincipal(principalId: string) {
  return useAdminGet<PrincipalSummary>(
    "admin-principal",
    { path: identityPaths.principal(principalId) },
    principalId !== "",
  );
}

/** One mutation for every identity write; the caller builds the request it confirmed. */
export function useIdentityChange() {
  return useEtagMutation<AdminRequest, PrincipalSummary | Record<string, unknown>>((req) => req);
}

export function useInvalidateIdentity(): () => Promise<void> {
  const queryClient = useQueryClient();
  return useCallback(async () => {
    await Promise.all(
      ["admin-principals", "admin-principal"].map((key) =>
        queryClient.invalidateQueries({ queryKey: [key] }),
      ),
    );
  }, [queryClient]);
}
