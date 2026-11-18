import { useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";
import { createQueryHook } from "../../../api/index.js";
import { ADMIN_IDENTITY_API, identityPaths } from "../shared/adminPaths";
import { useAdminGet, useEtagMutation, type AdminRequest } from "../shared/transport";
import type {
  MyAccessView,
  PrincipalListParams,
  PrincipalPageView,
  PrincipalSummary,
  RoleMappingView,
} from "./types";

/** PRP-138 read views. Both are GET only; nothing in the console writes the mapping. */
export const ME_ACCESS_PATH = "/api/v1/me/access";
export const ROLE_MAPPING_PATH = `${ADMIN_IDENTITY_API}/role-mapping`;

/** The caller's own roles and where each came from. Pass `enabled` false to defer the read. */
export const useMyAccess = createQueryHook<null, MyAccessView>({
  key: "me-access",
  fetcher: (client, _p, signal) => client.get<MyAccessView>(ME_ACCESS_PATH, undefined, signal),
});

/** The effective Entra role mapping (needs deployment-scoped `policy.manage`). */
export const useRoleMapping = createQueryHook<null, RoleMappingView>({
  key: "admin-role-mapping",
  fetcher: (client, _p, signal) =>
    client.get<RoleMappingView>(ROLE_MAPPING_PATH, undefined, signal),
});

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
