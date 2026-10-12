import {
  QueryClient,
  QueryClientProvider,
  useInfiniteQuery,
  useMutation,
  useQuery,
  type InfiniteData,
  type UseInfiniteQueryResult,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query";
import { createContext, useContext, useState, type ReactNode } from "react";
import type { ApiClient } from "./client.js";
import type { ApiError } from "./errors.js";
import { nextCursor, type PagedResponse } from "./pagination.js";

const ApiClientContext = createContext<ApiClient | undefined>(undefined);

export function useApiClient(): ApiClient {
  const client = useContext(ApiClientContext);
  if (client === undefined) throw new Error("useApiClient must be used inside <QueryProvider>");
  return client;
}

/** The client already retries 429/5xx with Retry-After, so TanStack never retries a second time. */
export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, refetchOnWindowFocus: false },
      mutations: { retry: false },
    },
  });
}

export interface QueryProviderProps {
  client: ApiClient;
  queryClient?: QueryClient;
  children: ReactNode;
}

export function QueryProvider({ client, queryClient, children }: QueryProviderProps) {
  const [owned] = useState(() => queryClient ?? createQueryClient());
  return (
    <ApiClientContext.Provider value={client}>
      <QueryClientProvider client={queryClient ?? owned}>{children}</QueryClientProvider>
    </ApiClientContext.Provider>
  );
}

/** Errors surface as `error` (an ApiError); a failed request is never turned into empty data. */
export function createQueryHook<TParams, TData>(spec: {
  key: string;
  fetcher: (client: ApiClient, params: TParams, signal: AbortSignal) => Promise<TData>;
}): (params: TParams, enabled?: boolean) => UseQueryResult<TData, ApiError> {
  return (params, enabled = true) => {
    const client = useApiClient();
    return useQuery<TData, ApiError>({
      queryKey: [spec.key, params],
      queryFn: ({ signal }) => spec.fetcher(client, params, signal),
      enabled,
    });
  };
}

export function createInfiniteQueryHook<TParams, TItem>(spec: {
  key: string;
  fetcher: (
    client: ApiClient,
    params: TParams,
    cursor: string | undefined,
    signal: AbortSignal,
  ) => Promise<PagedResponse<TItem>>;
}): (
  params: TParams,
) => UseInfiniteQueryResult<InfiniteData<PagedResponse<TItem>, string | undefined>, ApiError> {
  return (params) => {
    const client = useApiClient();
    return useInfiniteQuery<
      PagedResponse<TItem>,
      ApiError,
      InfiniteData<PagedResponse<TItem>, string | undefined>,
      unknown[],
      string | undefined
    >({
      queryKey: [spec.key, params],
      initialPageParam: undefined,
      queryFn: ({ pageParam, signal }) => spec.fetcher(client, params, pageParam, signal),
      getNextPageParam: (last) => nextCursor(last.page),
    });
  };
}

export function createMutationHook<TVars, TData>(spec: {
  mutate: (client: ApiClient, vars: TVars) => Promise<TData>;
}): () => UseMutationResult<TData, ApiError, TVars> {
  return () => {
    const client = useApiClient();
    return useMutation<TData, ApiError, TVars>({
      mutationFn: (vars) => spec.mutate(client, vars),
    });
  };
}
