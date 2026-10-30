import { useInfiniteQuery } from "@tanstack/react-query";
import {
  createMutationHook,
  createQueryHook,
  useApiClient,
  type ApiClient,
  type ApiError,
} from "../../api/index.js";
import { auditDomainsPath, auditRecordsPath, auditVerifyPath } from "./paths";
import type { AuditDomainList, AuditRecordPage, ChainVerification } from "./types";

/** Records per request (the adapter allows up to its range maximum). */
export const AUDIT_PAGE_SIZE = 25;

/** The domain list comes from the audit adapter; an auditor holds no data.read for /me/domains. */
export const useAuditDomains = createQueryHook<Record<string, never>, AuditDomainList>({
  key: "audit-domains",
  fetcher: (client, _p, signal) =>
    client.get<AuditDomainList>(auditDomainsPath(), undefined, signal),
});

function fetchRecords(
  client: ApiClient,
  domain: string,
  cursor: string | undefined,
  signal: AbortSignal,
): Promise<AuditRecordPage> {
  return client.get<AuditRecordPage>(
    auditRecordsPath(domain),
    { page_size: AUDIT_PAGE_SIZE, ...(cursor === undefined ? {} : { cursor }) },
    signal,
  );
}

/** Cursor-paged records for one domain; the next cursor is the server's, never computed here. */
export function useAuditRecords(domain: string) {
  const client = useApiClient();
  return useInfiniteQuery<
    AuditRecordPage,
    ApiError,
    readonly AuditRecordPage[],
    unknown[],
    string | undefined
  >({
    queryKey: ["audit-records", domain],
    initialPageParam: undefined,
    queryFn: ({ pageParam, signal }) => fetchRecords(client, domain, pageParam, signal),
    getNextPageParam: (last) => last.next_cursor ?? undefined,
    select: (data) => data.pages,
  });
}

/** Verification is a read-only GET triggered by the button. */
export const useVerifyChain = createMutationHook<{ domain: string }, ChainVerification>({
  mutate: (client, vars) => client.get<ChainVerification>(auditVerifyPath(vars.domain)),
});
