import { handle as adminCore } from "./admin-core.ts";
import { handle as adminSources } from "./admin-sources.ts";
import { handle as audit } from "./audit.ts";
import { handle as catalog } from "./catalog.ts";
import { handle as catalogAccess } from "./catalog-access.ts";
import type { FeatureMockContext, FeatureMockHandler } from "./context.ts";
import { handle as curation } from "./curation.ts";
import { handle as deploy } from "./deploy.ts";
import { handle as evaluations } from "./evaluations.ts";
import { handle as executionControl } from "./execution-control.ts";
import { handle as federation } from "./federation.ts";
import { handle as finops } from "./finops.ts";
import { handle as compliance } from "./compliance.ts";
import { handle as roleMapping } from "./role-mapping.ts";

export type { FeatureMockContext, FeatureMockHandler } from "./context.ts";

/**
 * PRP-31 feature mocks in dispatch order. Curation comes before catalog because its paths
 * (`/catalog/curation/...`, `/catalog/domains/{d}/curation/...`) sit under the catalog prefix.
 * Lanes edit their own module, never this list.
 */
export const FEATURE_HANDLERS: readonly FeatureMockHandler[] = [
  curation,
  // Before catalog: serves the grounding_source entity list the catalog mock does not seed.
  catalogAccess,
  catalog,
  audit,
  finops,
  federation,
  deploy,
  evaluations,
  executionControl,
  compliance,
  roleMapping,
  // Before adminCore: it answers `/admin/system/**`, and this module owns `/settings/{key}`.
  adminSources,
  adminCore,
];

/** Runs the handlers in order; true when one answered the request. */
export function dispatchFeatureMocks(
  ctx: FeatureMockContext,
  handlers: readonly FeatureMockHandler[] = FEATURE_HANDLERS,
): boolean {
  for (const handler of handlers) {
    if (handler(ctx)) return true;
  }
  return false;
}
