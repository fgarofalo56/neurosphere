import { useQuery } from "@tanstack/react-query";
import { useApiClient } from "../../api/index.js";
import { useRoles } from "../../auth/useRoles";
import { SOURCE_STATUS_PATH } from "./strings";
import type { SourceStatusEntry, SourceStatusResponse } from "./types";

export const SOURCE_STATUS_KEY = "source-status";

export interface SourceStatusView {
  /** Undefined while loading and when the request failed (403 or any error): pages keep their own text. */
  readonly sources: readonly SourceStatusEntry[] | undefined;
}

/** One cached read of the four first sources, shared by every page. Errors are not retried or shown. */
export function useSourceStatus(): SourceStatusView {
  const client = useApiClient();
  const query = useQuery<SourceStatusResponse>({
    queryKey: [SOURCE_STATUS_KEY],
    queryFn: ({ signal }) =>
      client.get<SourceStatusResponse>(SOURCE_STATUS_PATH, undefined, signal),
    staleTime: 60_000,
  });
  const body: Partial<SourceStatusResponse> | undefined = query.data;
  const sources = Array.isArray(body?.sources) ? body.sources : undefined;
  return { sources };
}

/** Display only: the server decides access; this just chooses between a link and a sentence. */
export function useIsAdmin(): boolean {
  return useRoles().roles.includes("Admin");
}
