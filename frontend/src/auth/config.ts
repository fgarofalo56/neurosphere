/**
 * Auth configuration shape. Defined locally so `auth/` has no dependency on
 * `app/` (owned by another lane); the integrator wires the runtime
 * `config.json` values (C7) into this type.
 */
export type CloudName = "commercial" | "government";

export interface AuthConfig {
  readonly cloud: CloudName;
  readonly tenantId: string;
  readonly clientId: string;
  /** API scope from runtime config; never hard-coded (audiences differ per cloud). */
  readonly apiScope: string;
  /** Must match the registered SPA redirect URI exactly. Defaults to window origin. */
  readonly redirectUri?: string | undefined;
}
