import type { CopilotMockContext } from "../copilot.ts";

/**
 * What a PRP-31 feature mock receives: the same request context the copilot and MCP admin mocks
 * use, plus the persona carried by the fake token (lower-cased, undefined when absent) and the
 * request correlation id for problem+json bodies.
 */
export interface FeatureMockContext extends CopilotMockContext {
  readonly role: string | undefined;
  readonly correlationId: string;
}

/** A feature mock: answers the request and returns true, or returns false to pass. */
export type FeatureMockHandler = (ctx: FeatureMockContext) => boolean;
