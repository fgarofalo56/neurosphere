import type { ActionView } from "../actions/types";

export type { ActionView };

/** Hand-mirrored from services/api/neurosphere_api/catalog/ (wire contract, openapi.json). */
export type PublishKind = "grant" | "mcp_server";

export interface GrantEntity {
  readonly id: string;
  readonly entity_type: "grant";
  readonly domain_id: string;
  readonly lifecycle_status: string;
  readonly enabled: boolean;
  readonly principal: {
    readonly kind: string;
    readonly object_id: string;
    readonly display?: string | null;
  };
  readonly target: { readonly kind: string; readonly ref: string };
}

export interface McpServerEntity {
  readonly id: string;
  readonly entity_type: "mcp_server";
  readonly domain_id: string;
  readonly lifecycle_status: string;
  readonly display_name: string;
  readonly url: string;
  readonly publishable: boolean;
}

export interface EntityPage<T> {
  readonly items: readonly T[];
  readonly next_cursor: string | null;
}

export type McpStage = "publish" | "deny" | "change" | "remove";
export type McpPublicationState = "unpublished" | "published" | "denied";

export interface McpPublicationStatus {
  readonly server_id: string;
  readonly state: McpPublicationState;
  readonly gateway_id: string | null;
  readonly api_path: string | null;
  readonly next_publish_stage: McpStage | null;
  readonly next_unpublish_stage: McpStage | null;
  readonly diagnostics: readonly string[];
}

/** `POST .../mcp-servers/{id}/publish|unpublish` (201): the drafted action plus the stage. */
export interface McpPublicationDraft {
  readonly action: ActionView;
  readonly stage: McpStage;
  readonly state: McpPublicationState;
  readonly diagnostics: readonly string[];
}

export interface GrantPublishRequest {
  readonly gateway_id: string;
  readonly api_id: string;
  readonly access: "subscription" | "entra";
  readonly idempotency_key: string;
  readonly channel: "button";
}

export interface IdempotentRequest {
  readonly idempotency_key: string;
  readonly channel: "button";
}

export interface McpPublishRequest extends IdempotentRequest {
  readonly gateway_id?: string;
  readonly api_path?: string;
}

export interface EntityListParams {
  readonly entityType: PublishKind;
}

export interface EntityParams {
  readonly entityId: string;
}

export interface GrantPublishVars {
  readonly entityId: string;
  readonly request: GrantPublishRequest;
}

export interface GrantUnpublishVars {
  readonly entityId: string;
  readonly request: IdempotentRequest;
}

export interface McpPublishVars {
  readonly entityId: string;
  readonly request: McpPublishRequest;
}

export interface McpUnpublishVars {
  readonly entityId: string;
  readonly request: IdempotentRequest;
}
