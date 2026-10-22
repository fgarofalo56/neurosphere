/**
 * Vitest setup: jest-dom matchers, vitest-axe matcher and the MSW 2.x node
 * server lifecycle. Unhandled requests error so no test touches the network.
 *
 * Wiring (integrator): vite.config.ts test block needs
 *   setupFiles: ["./tests/setup.ts"]
 */
import "@testing-library/jest-dom/vitest";
import { afterAll, afterEach, beforeAll, expect } from "vitest";
import { cleanup, configure } from "@testing-library/react";
import * as axeMatchers from "vitest-axe/matchers";
import { setupServer } from "msw/node";

expect.extend(axeMatchers);

/**
 * findBy and waitFor default to 1 s. Fluent dialogs and portals mount slower than that when
 * every test file runs in parallel workers, which made the full suite flaky about 1 run in 5
 * (PRP-19). The cap only bounds how long a lookup may wait; passing tests are not slowed.
 */
configure({ asyncUtilTimeout: 5000 });

/** Shared MSW server; tests add per-test handlers with server.use(...). */
export const server = setupServer();

beforeAll(() => {
  server.listen({ onUnhandledRequest: "error" });
});

afterEach(() => {
  server.resetHandlers();
  cleanup();
});

afterAll(() => {
  server.close();
});
