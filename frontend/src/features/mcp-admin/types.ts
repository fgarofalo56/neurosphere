/** Hand-mirrored from services/api/neurosphere_api/mcp/admin/models.py (wire contract). */
export type ToolState = "pending" | "approved" | "revoked" | "removed";
export type ServerStatus = "active" | "disabled";

export interface ToolEntryView {
  readonly name: string;
  readonly title: string | null;
  readonly description: string;
  readonly input_schema: Readonly<Record<string, unknown>>;
  readonly output_schema: Readonly<Record<string, unknown>> | null;
  readonly annotations: Readonly<Record<string, unknown>> | null;
  readonly tool_hash: string;
}

/** Approved content (before) against the latest advertised content (after). */
export interface ToolChangeView {
  readonly before: ToolEntryView;
  readonly after: ToolEntryView;
  readonly description_changed: boolean;
  readonly input_schema_changed: boolean;
  readonly output_schema_changed: boolean;
}

export interface ToolView {
  readonly name: string;
  readonly state: ToolState;
  /** True only when the tool is approved at its current hash. */
  readonly enabled: boolean;
  readonly current_hash: string;
  readonly approved_hash: string | null;
  readonly approved_by: string | null;
  readonly approved_at: string | null;
  readonly revoked_reason: string | null;
  readonly revoked_by: string | null;
  readonly first_seen_at: string;
  readonly last_seen_at: string;
  readonly updated_at: string;
  readonly entry: ToolEntryView;
  /** Present for a tool revoked because its content changed. */
  readonly change: ToolChangeView | null;
}

export interface ServerView {
  readonly id: string;
  readonly url: string;
  readonly host: string;
  readonly display_name: string;
  readonly cloud: string;
  readonly status: ServerStatus;
  readonly registered_by: string;
  readonly registered_at: string;
  readonly last_synced_at: string | null;
  readonly manifest_hash: string | null;
  readonly etag: string | null;
  readonly tool_count: number;
  readonly pending_count: number;
  readonly approved_count: number;
  readonly revoked_count: number;
}

export interface ServerPage {
  readonly items: readonly ServerView[];
  readonly next_cursor: string | null;
}

export interface ToolList {
  readonly server_id: string;
  /** Send as If-Match when approving or revoking. */
  readonly etag: string | null;
  readonly items: readonly ToolView[];
}

export interface SyncView {
  readonly server: ServerView;
  readonly added: readonly string[];
  readonly changed: readonly string[];
  readonly revoked: readonly string[];
  readonly removed: readonly string[];
  readonly unchanged: readonly string[];
  readonly manifest_hash: string;
  readonly synced_at: string;
}

export interface ListParams {
  readonly cursor: string;
  readonly limit: number;
}

export interface ServerParams {
  readonly serverId: string;
}

export interface RegisterVars {
  readonly url: string;
  readonly displayName: string;
}

export interface SyncVars {
  readonly serverId: string;
}

export interface UpdateVars {
  readonly serverId: string;
  readonly etag: string;
  readonly status?: ServerStatus | undefined;
  readonly displayName?: string | undefined;
}

export interface ApproveVars {
  readonly serverId: string;
  readonly toolName: string;
  /** The hash the administrator reviewed; the server approves only if it is still current. */
  readonly expectedHash: string;
  readonly etag: string;
}

export interface RevokeVars {
  readonly serverId: string;
  readonly toolName: string;
  readonly etag: string;
  readonly reason: string;
}
