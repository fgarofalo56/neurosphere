import { createMutationHook, createQueryHook } from "../../api/index.js";
import { entitiesPath, grantActionPath, mcpActionPath, mcpPublicationPath } from "./paths";
import type {
  ActionView,
  EntityListParams,
  EntityPage,
  EntityParams,
  GrantEntity,
  GrantPublishVars,
  GrantUnpublishVars,
  McpPublicationDraft,
  McpPublicationStatus,
  McpPublishVars,
  McpServerEntity,
  McpUnpublishVars,
} from "./types";

/** The server scopes the list to the caller; the client sends only the entity type. */
export const useGrants = createQueryHook<EntityListParams, EntityPage<GrantEntity>>({
  key: "catalog-grants",
  fetcher: (client, _p, signal) =>
    client.get<EntityPage<GrantEntity>>(entitiesPath(), { entity_type: "grant" }, signal),
});

export const useMcpServerEntities = createQueryHook<EntityListParams, EntityPage<McpServerEntity>>({
  key: "catalog-mcp-servers",
  fetcher: (client, _p, signal) =>
    client.get<EntityPage<McpServerEntity>>(entitiesPath(), { entity_type: "mcp_server" }, signal),
});

export const useMcpPublicationStatus = createQueryHook<EntityParams, McpPublicationStatus>({
  key: "catalog-mcp-publication",
  fetcher: (client, p, signal) =>
    client.get<McpPublicationStatus>(mcpPublicationPath(p.entityId), undefined, signal),
});

export const usePublishGrant = createMutationHook<GrantPublishVars, ActionView>({
  mutate: (client, v) => client.post<ActionView>(grantActionPath(v.entityId, "publish"), v.request),
});

export const useUnpublishGrant = createMutationHook<GrantUnpublishVars, ActionView>({
  mutate: (client, v) =>
    client.post<ActionView>(grantActionPath(v.entityId, "unpublish"), v.request),
});

export const usePublishMcpServer = createMutationHook<McpPublishVars, McpPublicationDraft>({
  mutate: (client, v) =>
    client.post<McpPublicationDraft>(mcpActionPath(v.entityId, "publish"), v.request),
});

export const useUnpublishMcpServer = createMutationHook<McpUnpublishVars, McpPublicationDraft>({
  mutate: (client, v) =>
    client.post<McpPublicationDraft>(mcpActionPath(v.entityId, "unpublish"), v.request),
});
