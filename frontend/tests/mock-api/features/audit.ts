import type { FeatureMockHandler } from "./context.ts";

/**
 * PRP-31 placeholder for the audit mock. The owning lane replaces this with a handler that returns
 * true after answering a request it owns, false to let the next handler (and finally server.ts)
 * continue.
 */
export const handle: FeatureMockHandler = () => false;
