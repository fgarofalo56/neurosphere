/**
 * Vitest setup: jest-dom matchers, vitest-axe matcher and the MSW 2.x node
 * server lifecycle. Unhandled requests error so no test touches the network.
 *
 * Wiring (integrator): vite.config.ts test block needs
 *   setupFiles: ["./tests/setup.ts"]
 */
import "@testing-library/jest-dom/vitest";
import { afterAll, afterEach, beforeAll, expect } from "vitest";
import { cleanup } from "@testing-library/react";
import * as axeMatchers from "vitest-axe/matchers";
import { setupServer } from "msw/node";

expect.extend(axeMatchers);

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
