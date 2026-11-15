/**
 * Vitest setup: jest-dom matchers, vitest-axe matcher and the MSW 3 node server lifecycle.
 * Unhandled requests fail the test that made them, so no test touches the network.
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

/**
 * msw 3 names the option `onUnhandledFrame`; `onUnhandledRequest` no longer exists, so the old
 * setting silently fell back to a warning (#92). The frame is also remembered and re-thrown in
 * afterEach: the 'error' strategy alone only fails that one fetch, which app code may catch.
 * Fix a test that starts failing here with an explicit handler, never a broad catch-all.
 */
const unhandled: string[] = [];

beforeAll(() => {
  server.listen({
    async onUnhandledFrame({ frame, defaults }) {
      unhandled.push(await frame.getUnhandledMessage());
      defaults.error();
    },
  });
});

afterEach(() => {
  server.resetHandlers();
  cleanup();
  const seen = unhandled.splice(0);
  if (seen.length > 0) {
    throw new Error(`Unhandled network request(s); add an explicit handler:\n${seen.join("\n")}`);
  }
});

afterAll(() => {
  server.close();
});
