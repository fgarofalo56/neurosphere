import type { AccountInfo } from "@azure/msal-browser";
import { MsalProvider } from "@azure/msal-react";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { QueryProvider, createApiClient } from "../api/index.js";
import { createStubMsalInstance } from "../../tests/e2e-support/stubMsal";
import {
  AppThemeProvider,
  DEFAULT_THEME_PACK_ID,
  DEFAULT_UI_STYLE_ID,
  UI_STYLE_IDS,
  THEME_NAMES,
  THEME_PACKS,
  reloadStoredTheme,
  useThemeStore,
  type ThemeName,
  type UiStyleId,
} from "../design-system";
import { sandboxRoutes } from "../features/sandbox/routes";
import { STRINGS } from "../features/sandbox/strings";
import { DomainProvider } from "./domain";
import { createAppRoutes } from "./routes";
import { accountWith, domainEntry, stubResizeObserver } from "./test-support";

/**
 * Theme packs are presentation only (PRP-24, NS-10): switching pack or mode must not change a
 * single request the app makes, nor any route-guard outcome. The baseline is the default pack in
 * light mode; every other pack and mode must reproduce it exactly.
 */

beforeAll(stubResizeObserver);
beforeEach(() => {
  window.localStorage.clear();
  reloadStoredTheme();
});
afterEach(() => {
  cleanup();
});

interface RecordedRequest {
  readonly method: string;
  readonly url: string;
  readonly headers: readonly (readonly [string, string])[];
}

type Scenario = "allowed" | "forbidden";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": status >= 400 ? "application/problem+json" : "application/json" },
  });
}

/** Synthetic API: the domain list always answers; every other path is allowed or 403. */
function answer(url: string, scenario: Scenario): Response {
  const { pathname } = new URL(url);
  if (pathname === "/api/v1/me/domains") {
    return jsonResponse(200, { items: [domainEntry("d:1", "One")] });
  }
  if (scenario === "forbidden") return jsonResponse(403, { status: 403, code: "forbidden" });
  if (pathname === "/api/v1/sandbox/status") {
    return jsonResponse(200, {
      environment: "sandbox",
      synthetic: true,
      customer_id: "synthco",
      database: "db",
      counts: { domain: 3 },
      relations: 2,
      total: 5,
    });
  }
  return jsonResponse(200, { items: [] });
}

function normalise(calls: readonly [unknown, RequestInit | undefined][]): RecordedRequest[] {
  return calls
    .map(([input, init]) => {
      const headers = Object.entries((init?.headers ?? {}) as Record<string, string>).map(
        // The correlation id is random per request by design; assert it exists, not its value.
        ([k, v]) =>
          [k.toLowerCase(), k.toLowerCase().includes("correlation") ? "<id>" : v] as const,
      );
      return {
        method: init?.method ?? "GET",
        url: String(input),
        headers: headers.sort(([a], [b]) => a.localeCompare(b)),
      };
    })
    .sort((a, b) => `${a.method} ${a.url}`.localeCompare(`${b.method} ${b.url}`));
}

async function settle(count: () => number): Promise<void> {
  let last = -1;
  await waitFor(
    async () => {
      const now = count();
      const stable = now === last && now > 0;
      last = now;
      await new Promise((r) => setTimeout(r, 60));
      expect(stable).toBe(true);
    },
    { timeout: 4000, interval: 10 },
  );
}

interface Observed {
  readonly requests: RecordedRequest[];
  readonly outcome: string;
  readonly pack: string | null;
  readonly mode: string | null;
  readonly style: string | null;
  readonly live: boolean;
}

async function observe(
  path: string,
  scenario: Scenario,
  packId: string,
  mode: ThemeName,
  styleId: UiStyleId = DEFAULT_UI_STYLE_ID,
): Promise<Observed> {
  useThemeStore.setState({ packId, themeName: mode, styleId });
  const account: AccountInfo = accountWith(`home-${crypto.randomUUID()}`, ["Viewer"]);
  const fetchImpl = vi.fn<typeof fetch>((input) =>
    Promise.resolve(answer(String(input), scenario)),
  );
  const client = createApiClient({
    baseUrl: "http://api.test",
    getToken: () => Promise.resolve("test-credential"),
    fetchImpl,
    maxRetries: 0,
  });
  const base = createStubMsalInstance() as unknown as Record<string, unknown>;
  const msal = {
    ...base,
    getAllAccounts: () => [account],
    getActiveAccount: () => account,
  } as unknown as Parameters<typeof MsalProvider>[0]["instance"];
  const router = createMemoryRouter(
    createAppRoutes({
      extraRoutes: sandboxRoutes,
      navItems: [{ to: "/", label: "Home", group: "Overview" }],
    }),
    { initialEntries: [path] },
  );
  const { container, unmount } = render(
    <AppThemeProvider>
      <MsalProvider instance={msal}>
        <QueryProvider client={client}>
          <DomainProvider>
            <RouterProvider router={router} />
          </DomainProvider>
        </QueryProvider>
      </MsalProvider>
    </AppThemeProvider>,
  );
  await settle(() => fetchImpl.mock.calls.length);
  let outcome = "home";
  if (path === "/sandbox") {
    outcome =
      scenario === "forbidden"
        ? (await screen.findByTestId("sandbox-error")).textContent
        : (await screen.findByTestId("sandbox-total")).textContent;
  }
  const root = container.querySelector("[data-theme]");
  const observed: Observed = {
    requests: normalise(fetchImpl.mock.calls as [unknown, RequestInit | undefined][]),
    outcome,
    pack: root?.getAttribute("data-theme-pack") ?? null,
    mode: root?.getAttribute("data-theme") ?? null,
    style: root?.getAttribute("data-ui-style") ?? null,
    live: container.querySelector("[data-slot='live-indicator']") !== null,
  };
  unmount();
  cleanup();
  return observed;
}

const CASES: readonly (readonly [string, Scenario])[] = [
  ["/", "allowed"],
  ["/sandbox", "allowed"],
  ["/sandbox", "forbidden"],
];

describe("theme packs do not change requests or route-guard outcomes", () => {
  for (const [path, scenario] of CASES) {
    it(`${path} (${scenario}) is identical under every pack and mode`, async () => {
      const baseline = await observe(path, scenario, DEFAULT_THEME_PACK_ID, "light");
      expect(baseline.requests.length).toBeGreaterThan(0);
      expect(baseline.pack).toBe(DEFAULT_THEME_PACK_ID);
      for (const packId of Object.keys(THEME_PACKS)) {
        for (const mode of THEME_NAMES) {
          const run = await observe(path, scenario, packId, mode);
          // The theme really was applied, so identical requests are not a vacuous result.
          expect(run.pack).toBe(packId);
          expect(run.mode).toBe(mode);
          expect(run.requests).toEqual(baseline.requests);
          expect(run.outcome).toBe(baseline.outcome);
        }
      }
    }, 60_000);
  }

  it("a forbidden route stays forbidden under every pack and mode", async () => {
    for (const packId of Object.keys(THEME_PACKS)) {
      for (const mode of THEME_NAMES) {
        const run = await observe("/sandbox", "forbidden", packId, mode);
        expect(run.outcome).toContain(STRINGS.forbidden);
        expect(screen.queryByTestId("sandbox-total")).toBeNull();
      }
    }
  }, 60_000);
});

describe("UI styles do not change requests or route-guard outcomes", () => {
  for (const [path, scenario] of CASES) {
    it(`${path} (${scenario}) is identical under every UI style and mode`, async () => {
      const baseline = await observe(
        path,
        scenario,
        DEFAULT_THEME_PACK_ID,
        "light",
        "enterprise-fluent",
      );
      expect(baseline.requests.length).toBeGreaterThan(0);
      expect(baseline.style).toBe("enterprise-fluent");
      for (const styleId of UI_STYLE_IDS) {
        for (const mode of THEME_NAMES) {
          const run = await observe(path, scenario, DEFAULT_THEME_PACK_ID, mode, styleId);
          // The style really was applied, so identical requests are not a vacuous result.
          expect(run.style).toBe(styleId);
          expect(run.mode).toBe(mode);
          expect(run.requests).toEqual(baseline.requests);
          expect(run.outcome).toBe(baseline.outcome);
        }
      }
    }, 60_000);
  }

  it("the Ops LIVE label is static: shown only in the Ops console, with no extra request", async () => {
    const enterprise = await observe(
      "/",
      "allowed",
      DEFAULT_THEME_PACK_ID,
      "dark",
      "enterprise-fluent",
    );
    const ops = await observe("/", "allowed", DEFAULT_THEME_PACK_ID, "dark", "ops-console");
    expect(enterprise.live).toBe(false);
    expect(ops.live).toBe(true);
    expect(ops.requests).toEqual(enterprise.requests);
  }, 60_000);
});
