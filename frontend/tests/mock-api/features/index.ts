import { handle as audit } from "./audit.ts";
import { handle as catalog } from "./catalog.ts";
import type { FeatureMockContext, FeatureMockHandler } from "./context.ts";
import { handle as curation } from "./curation.ts";
import { handle as deploy } from "./deploy.ts";
import { handle as evaluations } from "./evaluations.ts";
import { handle as executionControl } from "./execution-control.ts";
import { handle as federation } from "./federation.ts";
import { handle as finops } from "./finops.ts";

export type { FeatureMockContext, FeatureMockHandler } from "./context.ts";

/**
 * PRP-31 feature mocks in dispatch order. Curation comes before catalog because its paths
 * (`/catalog/curation/...`, `/catalog/domains/{d}/curation/...`) sit under the catalog prefix.
 * Lanes edit their own module, never this list.
 */
export const FEATURE_HANDLERS: readonly FeatureMockHandler[] = [
  curation,
  catalog,
  audit,
  finops,
  federation,
  deploy,
  evaluations,
  executionControl,
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
