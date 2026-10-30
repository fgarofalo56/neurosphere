import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { QueryProvider, createApiClient } from "../../api/index.js";
import type { DomainEntry } from "../../app/domain";
import { gatewayModePath, gatewaysPath } from "./paths";
import { canPropose } from "./permissions";
import { gatewaysNavItems, gatewaysRoutes } from "./routes";
import { STRINGS } from "./strings";
import type { ActionView, GatewayRegistration } from "./types";

const selected = vi.hoisted(() => ({ domains: [] as DomainEntry[] }));

vi.mock("../../app/domain", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../app/domain")>();
  return {
    ...actual,
    useSelectedDomain: () => ({
      domainId: "commercial:contoso:catalog:domain:finance",
      domains: selected.domains,
      setDomain: () => undefined,
      status: "ready" as const,
    }),
  };
});

class ResizeObserverStub {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}

beforeAll(() => {
  vi.stubGlobal("ResizeObserver", ResizeObserverStub);
});

afterEach(() => {
  cleanup();
  selected.domains = [];
});

const DOMAIN = "commercial:contoso:catalog:domain:finance";
const GW_OBSERVE = `gw-${"1".repeat(32)}`;
const GW_MANAGE = `gw-${"2".repeat(32)}`;
const GW_GOV = `gw-${"3".repeat(32)}`;
const INTENT_ID = "22222222-2222-4222-8222-222222222222";
const LIST = `GET ${gatewaysPath(DOMAIN)}`;
const NOW = "2026-10-20T10:00:00Z";

function entry(permissions: readonly string[]): DomainEntry {
  return {
    domain_id: DOMAIN,
    display_name: "Finance",
    display_name_source: "catalog",
    cloud: "commercial",
    permissions,
  };
}

function gateway(over: Partial<GatewayRegistration> = {}): GatewayRegistration {
  return {
    id: GW_OBSERVE,
    domain_id: DOMAIN,
    cloud: "commercial",
    name: "apim-observe",
    tier: "standard_v2",
    mode: "observe",
    mode_changed_at: null,
    mode_changed_by: null,
    mode_revision: 0,
    preflight: null,
    ...over,
  };
}

function drafted(): ActionView {
  return {
    intent: {
      schema_version: "1.0",
      intent_id: INTENT_ID,
      action_kind: "gateway_mode_change",
      actor: { principal_pseudonym: "p-maker", principal_kind: "user", on_behalf_of: null },
      target: { canonical_id: GW_OBSERVE, entity_type: "apim_gateway_mode" },
      target_version: "mode-revision-0",
      proposed_diff: {
        format: "json_patch",
        operations: [{ op: "replace", path: "/mode", value: "manage" }],
      },
      prerequisite_results: [],
      evidence: [],
      confirmation_hash: null,
      confirmation_expires_at: null,
      idempotency_key: "button-mode-0000000001",
      channel: "button",
      state: "drafted",
      status_reason: null,
      dry_run: false,
      correlation_id: "c-1",
      created_at: NOW,
      state_changed_at: NOW,
    },
    advisory: false,
    requires_approval: true,
    self_approval_forbidden: false,
    review_item_id: null,
    execution: null,
  };
}

interface Reply {
  status: number;
  body: unknown;
}

function problem(status: number, code: string, reason?: string, detail?: string): Reply {
  return {
    status,
    body: {
      type: "about:blank",
      title: code,
      status,
      code,
      retryable: false,
      correlation_id: "corr-1",
      ...(reason !== undefined && { reason }),
      ...(detail !== undefined && { detail }),
    },
  };
}

interface Call {
  method: string;
  path: string;
  body: unknown;
}

function setup(routes: Record<string, Reply>) {
  const calls: Call[] = [];
  const fetchImpl = vi.fn<typeof fetch>((input, init) => {
    const url = new URL(String(input));
    const method = init?.method ?? "GET";
    const body = typeof init?.body === "string" ? (JSON.parse(init.body) as unknown) : undefined;
    calls.push({ method, path: url.pathname, body });
    const route = routes[`${method} ${url.pathname}`];
    if (route === undefined) {
      return Promise.resolve(new Response(JSON.stringify({ status: 404 }), { status: 404 }));
    }
    return Promise.resolve(new Response(JSON.stringify(route.body), { status: route.status }));
  });
  const client = createApiClient({
    baseUrl: "http://api.test",
    getToken: () => Promise.resolve("t"),
    fetchImpl,
    maxRetries: 0,
  });
  const router = createMemoryRouter(gatewaysRoutes, { initialEntries: ["/gateways"] });
  render(
    <QueryProvider client={client}>
      <RouterProvider router={router} />
    </QueryProvider>,
  );
  return { calls };
}

describe("exports and permissions", () => {
  it("exports the route and a nav item", () => {
    expect(gatewaysRoutes.map((r) => r.path)).toEqual(["gateways"]);
    expect(gatewaysNavItems()).toEqual([{ to: "/gateways", label: "Gateways" }]);
  });

  it("enables drafting for an unknown domain and disables it without action.propose", () => {
    expect(canPropose([], DOMAIN)).toBe(true);
    expect(canPropose([entry(["data.read"])], DOMAIN)).toBe(false);
    expect(canPropose([entry(["data.read", "action.propose"])], DOMAIN)).toBe(true);
  });
});

describe("gateways page", () => {
  it("shows mode, who and when, the failed preflight with required and missing actions", async () => {
    setup({
      [LIST]: {
        status: 200,
        body: {
          items: [
            gateway({
              mode: "manage",
              name: "apim-manage",
              id: GW_MANAGE,
              mode_changed_by: "p-maker",
              mode_changed_at: NOW,
              mode_revision: 3,
              preflight: {
                passed: false,
                checked_at: NOW,
                required: ["Microsoft.ApiManagement/service/apis/write", "x/write"],
                missing: ["x/write"],
              },
            }),
          ],
          next_cursor: null,
        },
      },
    });
    const panel = await screen.findByTestId("gateway-panel");
    expect(within(panel).getByTestId("gateway-mode").textContent).toBe("Manage");
    expect(within(panel).getByTestId("gateway-changed-by").textContent).toBe("p-maker");
    expect(within(panel).getByTestId("preflight-status").textContent).toBe("Failed");
    expect(within(panel).getByTestId("preflight-required").textContent).toContain("apis/write");
    expect(within(panel).getByTestId("preflight-missing").textContent).toBe("x/write");
    expect(within(panel).getByRole("button", { name: STRINGS.switch.toObserve })).toBeTruthy();
  });

  it("explains observe mode refusals and a missing preflight", async () => {
    setup({ [LIST]: { status: 200, body: { items: [gateway()], next_cursor: null } } });
    expect((await screen.findByTestId("observe-note")).textContent).toContain(
      "gateway_observe_mode",
    );
    expect(screen.getByTestId("preflight-none").textContent).toBe(STRINGS.preflight.none);
    expect(screen.getByTestId("gateway-changed-by").textContent).toBe(STRINGS.mode.neverChanged);
  });

  it("drafts a mode change through the mode route, then links to the approval flow", async () => {
    const { calls } = setup({
      [LIST]: { status: 200, body: { items: [gateway()], next_cursor: null } },
      [`POST ${gatewayModePath(DOMAIN, GW_OBSERVE)}`]: { status: 201, body: drafted() },
    });
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: STRINGS.switch.toManage }));
    const note = await screen.findByTestId("mode-drafted");
    const post = calls.find((c) => c.method === "POST");
    expect(post?.path).toBe(gatewayModePath(DOMAIN, GW_OBSERVE));
    expect(post?.body).toMatchObject({ mode: "manage", channel: "button" });
    expect(JSON.stringify(post?.body)).not.toMatch(/domain_id|customer_id|actor/);
    expect(typeof (post?.body as { idempotency_key: unknown }).idempotency_key).toBe("string");
    const link = within(note).getByRole("link", { name: STRINGS.switch.openApproval });
    expect(link.getAttribute("href")).toBe(
      `/actions/detail?domain_id=${encodeURIComponent(DOMAIN)}&intent_id=${INTENT_ID}`,
    );
    // The page never flips the mode itself: the gateway is still shown in observe mode.
    expect(screen.getByTestId("gateway-mode").textContent).toBe("Observe");
  });

  it("shows the server's refusal reason when a switch is refused as busy", async () => {
    setup({
      [LIST]: { status: 200, body: { items: [gateway()], next_cursor: null } },
      [`POST ${gatewayModePath(DOMAIN, GW_OBSERVE)}`]: problem(
        400,
        "capability_unavailable",
        "gateway_applying",
      ),
    });
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: STRINGS.switch.toManage }));
    const bar = await screen.findByTestId("mode-refusal");
    expect(bar.textContent).toContain(STRINGS.refusals.gateway_applying);
    expect(within(bar).getByTestId("mode-refusal-reason").textContent).toBe("gateway_applying");
  });

  it("disables manage for a Government gateway with the reason and drafts nothing", async () => {
    const { calls } = setup({
      [LIST]: {
        status: 200,
        body: {
          items: [gateway({ id: GW_GOV, cloud: "government", name: "apim-gov" })],
          next_cursor: null,
        },
      },
    });
    const button = await screen.findByRole("button", { name: STRINGS.switch.toManage });
    expect((button as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByTestId("government-blocked").textContent).toBe(STRINGS.switch.government);
    expect(calls.filter((c) => c.method === "POST")).toHaveLength(0);
  });

  it("disables the switch for a caller without action.propose in the domain", async () => {
    selected.domains = [entry(["data.read"])];
    setup({ [LIST]: { status: 200, body: { items: [gateway()], next_cursor: null } } });
    const button = await screen.findByRole("button", { name: STRINGS.switch.toManage });
    expect((button as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByTestId("no-permission").textContent).toBe(STRINGS.switch.noPermission);
  });

  it("shows an honest forbidden state, not an empty list, when the API says 403", async () => {
    setup({ [LIST]: problem(403, "forbidden") });
    await waitFor(() => expect(screen.getByTestId("forbidden-state")).toBeTruthy());
    expect(screen.queryByTestId("gateway-panel")).toBeNull();
  });
});
