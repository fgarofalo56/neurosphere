import type { ActionView } from "../actions/types";

export type { ActionView };

/** Hand-mirrored from services/api/neurosphere_api/gateway/ (wire contract, openapi.json). */
export type GatewayMode = "observe" | "manage";
export type GatewayCloud = "commercial" | "government";

/** Outcome of the write-permission preflight; only ARM action names, never a credential. */
export interface ModePreflight {
  readonly passed: boolean;
  readonly checked_at: string;
  /** ARM actions the APIM write connector needs at the gateway scope. */
  readonly required: readonly string[];
  /** The subset the service identity does not hold. */
  readonly missing?: readonly string[];
}

export interface GatewayRegistration {
  readonly id: string;
  readonly domain_id: string;
  readonly cloud: GatewayCloud;
  readonly name: string;
  readonly tier: string;
  readonly mode: GatewayMode;
  readonly mode_changed_at: string | null;
  readonly mode_changed_by: string | null;
  readonly mode_revision: number;
  readonly preflight: ModePreflight | null;
}

export interface GatewayList {
  readonly items: readonly GatewayRegistration[];
  readonly next_cursor: string | null;
}

export interface GatewayListParams {
  readonly domainId: string;
}

/** Body of POST .../mode. No identity, customer or domain fields: the server derives them. */
export interface ModeChangeRequest {
  readonly mode: GatewayMode;
  readonly idempotency_key: string;
  readonly channel: "button";
}

export interface ModeChangeVars {
  readonly domainId: string;
  readonly gatewayId: string;
  readonly request: ModeChangeRequest;
}
