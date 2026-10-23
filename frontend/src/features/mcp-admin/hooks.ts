import { useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";
import { createMutationHook, createQueryHook } from "../../api/index.js";
import {
  mcpServerPath,
  mcpServerSyncPath,
  mcpServerToolsPath,
  mcpServersPath,
  mcpToolApprovalPath,
} from "./paths";
import type {
  ApproveVars,
  ListParams,
  RegisterVars,
  RevokeVars,
  ServerPage,
  ServerParams,
  ServerView,
  SyncVars,
  SyncView,
  ToolList,
  UpdateVars,
} from "./types";

const KEYS = ["mcp-servers", "mcp-server", "mcp-tools"] as const;

export const useMcpServers = createQueryHook<ListParams, ServerPage>({
  key: "mcp-servers",
  fetcher: (client, p, signal) =>
    client.get<ServerPage>(
      mcpServersPath(),
      { cursor: p.cursor === "" ? undefined : p.cursor, limit: p.limit },
      signal,
    ),
});

export const useMcpServer = createQueryHook<ServerParams, ServerView>({
  key: "mcp-server",
  fetcher: (client, p, signal) =>
    client.get<ServerView>(mcpServerPath(p.serverId), undefined, signal),
});

export const useMcpTools = createQueryHook<ServerParams, ToolList>({
  key: "mcp-tools",
  fetcher: (client, p, signal) =>
    client.get<ToolList>(mcpServerToolsPath(p.serverId), undefined, signal),
});

export const useRegisterServer = createMutationHook<RegisterVars, ServerView>({
  mutate: (client, v) =>
    client.post<ServerView>(mcpServersPath(), { url: v.url, display_name: v.displayName }),
});

export const useSyncServer = createMutationHook<SyncVars, SyncView>({
  mutate: (client, v) => client.post<SyncView>(mcpServerSyncPath(v.serverId)),
});

export const useUpdateServer = createMutationHook<UpdateVars, ServerView>({
  mutate: (client, v) =>
    client.patch<ServerView>(
      mcpServerPath(v.serverId),
      {
        ...(v.status !== undefined ? { status: v.status } : {}),
        ...(v.displayName !== undefined ? { display_name: v.displayName } : {}),
      },
      v.etag,
    ),
});

/** The body carries the reviewed hash; the server refuses it if the tool has moved on. */
export const useApproveTool = createMutationHook<ApproveVars, ToolList>({
  mutate: (client, v) =>
    client.request<ToolList>({
      method: "POST",
      path: mcpToolApprovalPath(v.serverId, v.toolName),
      body: { expected_hash: v.expectedHash },
      ifMatch: v.etag,
    }),
});

export const useRevokeTool = createMutationHook<RevokeVars, ToolList>({
  mutate: (client, v) =>
    client.request<ToolList>({
      method: "DELETE",
      path: mcpToolApprovalPath(v.serverId, v.toolName),
      query: { reason: v.reason },
      ifMatch: v.etag,
    }),
});

/** Refetch lists, details and tools after any change. */
export function useInvalidateMcpAdmin(): () => Promise<void> {
  const queryClient = useQueryClient();
  return useCallback(async () => {
    await Promise.all(KEYS.map((key) => queryClient.invalidateQueries({ queryKey: [key] })));
  }, [queryClient]);
}
