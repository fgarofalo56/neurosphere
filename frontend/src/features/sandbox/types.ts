/** Mirrors the API's `SandboxSummary` body. */
export interface SandboxSummary {
  readonly environment: "sandbox";
  readonly synthetic: true;
  readonly customer_id: string;
  readonly database: string;
  readonly counts: Readonly<Record<string, number>>;
  readonly relations: number;
  readonly total: number;
}
