import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { QueryProvider, createApiClient } from "../../api/index.js";
import { gatewaysPath } from "../gateways/paths";
import { entitiesPath, grantActionPath, mcpActionPath, mcpPublicationPath } from "./paths";
import { catalogNavItems, catalogRoutes } from "./routes";
import { STRINGS } from "./strings";
import type { ActionView, GrantEntity, McpPublicationStatus, McpServerEntity } from "./types";

const DOMAIN = "commercial:contoso:catalog:domain:finance";
const GRANT_ID = "commercial:contoso:catalog:grant:analysts";
const MCP_ID = "commercial:contoso:catalog:mcp_server:tools";
const GW_ID = `gw-${"2".repeat(32)}`;
const INTENT_ID = "33333333-3333-4333-8333-333333333333";
const NOW = "2026-10-20T10:00:00Z";

const selected = vi.hoisted(() => ({ domains: [] as unknown[] }));

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

const GRANT: GrantEntity = {
  id: GRANT_ID,
  entity_type: "grant",
  domain_id: DOMAIN,
  lifecycle_status: "active",
  enabled: true,
  principal: {
    kind: "user",
    object_id: "11111111-1111-4111-8111-111111111111",
    display: "Analysts",
  },
  target: { kind: "model_api", ref: "commercial:contoso:foundry:service:gpt" },
};

const SERVER: McpServerEntity = {
  id: MCP_ID,
  entity_type: "mcp_server",
  domain_id: DOMAIN,
  lifecycle_status: "active",
  display_name: "Finance tools",
  url: "https://tools.example.com/mcp",
  publishable: true,
};

function status(over: Partial<McpPublicationStatus>): McpPublicationStatus {
  return {
    server_id: MCP_ID,
    state: "published",
    gateway_id: GW_ID,
    api_path: "tools",
    next_publish_stage: "change",
    next_unpublish_stage: "deny",
    diagnostics: [],
    ...over,
  };
}

function view(): ActionView {
  return {
    intent: {
      schema_version: "1.0",
      intent_id: INTENT_ID,
      action_kind: "grant_publish",
      actor: { principal_pseudonym: "p-maker", principal_kind: "user", on_behalf_of: null },
      target: { canonical_id: GRANT_ID, entity_type: "grant" },
      target_version: "unpublished",
      proposed_diff: {
        format: "json_patch",
        operations: [{ op: "replace", path: "/mode", value: "manage" }],
      },
      prerequisite_results: [],
      evidence: [],
      confirmation_hash: null,
      confirmation_expires_at: null,
      idempotency_key: "button-publish-000001",
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

function problem(status: number, code: string, reason?: string): Reply {
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
    },
  };
}

interface Call {
  method: string;
  path: string;
  search: string;
  body: unknown;
}

const ENTITIES = `GET ${entitiesPath()}`;

/** The entity list answers by the requested entity type; other routes come from `routes`. */
function withLists(
  grants: GrantEntity[],
  servers: McpServerEntity[],
  routes: Record<string, Reply>,
): { calls: Call[] } {
  const calls: Call[] = [];
  const fetchImpl = vi.fn<typeof fetch>((input, init) => {
    const url = new URL(String(input));
    const method = init?.method ?? "GET";
    const body = typeof init?.body === "string" ? (JSON.parse(init.body) as unknown) : undefined;
    calls.push({ method, path: url.pathname, search: url.search, body });
    let reply: Reply | undefined = routes[`${method} ${url.pathname}`];
    if (`${method} ${url.pathname}` === ENTITIES) {
      const type = url.searchParams.get("entity_type");
      reply = {
        status: 200,
        body: { items: type === "grant" ? grants : servers, next_cursor: null },
      };
    }
    return Promise.resolve(
      new Response(JSON.stringify(reply?.body ?? { status: 404 }), {
        status: reply?.status ?? 404,
      }),
    );
  });
  const client = createApiClient({
    baseUrl: "http://api.test",
    getToken: () => Promise.resolve("t"),
    fetchImpl,
    maxRetries: 0,
  });
  const router = createMemoryRouter(catalogRoutes, { initialEntries: ["/catalog/publication"] });
  render(
    <QueryProvider client={client}>
      <RouterProvider router={router} />
    </QueryProvider>,
  );
  return { calls };
}

describe("exports", () => {
  it("exports the route and a nav item", () => {
    expect(catalogRoutes.map((r) => r.path)).toEqual(["catalog/publication"]);
    expect(catalogNavItems()).toEqual([{ to: "/catalog/publication", label: "Publication" }]);
  });
});

describe("grant publish and unpublish", () => {
  it("drafts an unpublish through the grant route and links to the approval flow", async () => {
    const { calls } = withLists([GRANT], [], {
      [`POST ${grantActionPath(GRANT_ID, "unpublish")}`]: { status: 200, body: view() },
    });
    const user = userEvent.setup();
    const row = await screen.findByTestId("grant-row");
    await user.click(within(row).getByRole("button", { name: STRINGS.unpublish }));
    const bar = await screen.findByTestId("publish-drafted");
    const post = calls.find((c) => c.method === "POST");
    expect(post?.path).toBe(grantActionPath(GRANT_ID, "unpublish"));
    expect(post?.body).toMatchObject({ channel: "button" });
    expect(within(bar).getByRole("link", { name: STRINGS.openApproval }).getAttribute("href")).toBe(
      `/actions/detail?domain_id=${encodeURIComponent(DOMAIN)}&intent_id=${INTENT_ID}`,
    );
  });

  it("collects the gateway and API id in a dialog, then drafts the publish", async () => {
    const { calls } = withLists([GRANT], [], {
      [`GET ${gatewaysPath(DOMAIN)}`]: {
        status: 200,
        body: {
          items: [{ id: GW_ID, name: "apim-manage", mode: "manage", domain_id: DOMAIN }],
          next_cursor: null,
        },
      },
      [`POST ${grantActionPath(GRANT_ID, "publish")}`]: { status: 201, body: view() },
    });
    const user = userEvent.setup();
    const row = await screen.findByTestId("grant-row");
    await user.click(within(row).getByRole("button", { name: STRINGS.publish }));
    const dialog = await screen.findByRole("alertdialog", { hidden: true });
    const submit = within(dialog).getByRole("button", {
      name: STRINGS.dialog.submit,
      hidden: true,
    });
    expect((submit as HTMLButtonElement).disabled).toBe(true);
    await waitFor(() =>
      expect(
        within(dialog).getByRole("option", { name: "apim-manage (manage)", hidden: true }),
      ).toBeTruthy(),
    );
    await user.selectOptions(
      within(dialog).getByRole("combobox", { name: STRINGS.dialog.gateway, hidden: true }),
      GW_ID,
    );
    await user.type(
      within(dialog).getByLabelText(STRINGS.dialog.apiId, { exact: false }),
      "finance-api",
    );
    await user.click(submit);
    await screen.findByTestId("publish-drafted");
    const post = calls.find((c) => c.method === "POST");
    expect(post?.path).toBe(grantActionPath(GRANT_ID, "publish"));
    expect(post?.body).toMatchObject({
      gateway_id: GW_ID,
      api_id: "finance-api",
      access: "subscription",
      channel: "button",
    });
  });

  it("shows the observe-mode refusal reason from the server", async () => {
    withLists([GRANT], [], {
      [`POST ${grantActionPath(GRANT_ID, "unpublish")}`]: problem(
        400,
        "capability_unavailable",
        "gateway_observe_mode",
      ),
    });
    const user = userEvent.setup();
    const row = await screen.findByTestId("grant-row");
    await user.click(within(row).getByRole("button", { name: STRINGS.unpublish }));
    const refusal = await screen.findByTestId("publish-refusal");
    expect(refusal.textContent).toContain("observe mode");
    expect(within(refusal).getByTestId("publish-refusal-reason").textContent).toBe(
      "gateway_observe_mode",
    );
  });

  it("disables both buttons without action.propose in the entity's domain", async () => {
    selected.domains = [
      {
        domain_id: DOMAIN,
        display_name: "Finance",
        display_name_source: "catalog",
        cloud: "commercial",
        permissions: ["data.read"],
      },
    ];
    withLists([GRANT], [], {});
    const row = await screen.findByTestId("grant-row");
    for (const name of [STRINGS.publish, STRINGS.unpublish]) {
      expect((within(row).getByRole("button", { name }) as HTMLButtonElement).disabled).toBe(true);
    }
    expect(within(row).getByTestId("no-permission").textContent).toBe(STRINGS.noPermission);
  });
});

describe("mcp server publish and unpublish", () => {
  it("names unpublish step 1 (deny) and drafts that stage, with the two-step copy", async () => {
    const { calls } = withLists([], [SERVER], {
      [`GET ${mcpPublicationPath(MCP_ID)}`]: { status: 200, body: status({}) },
      [`POST ${mcpActionPath(MCP_ID, "unpublish")}`]: {
        status: 201,
        body: { action: view(), stage: "deny", state: "published", diagnostics: [] },
      },
    });
    const user = userEvent.setup();
    const row = await screen.findByTestId("mcp-row");
    expect(await within(row).findByTestId("mcp-next-unpublish")).toBeTruthy();
    expect(within(row).getByTestId("mcp-next-unpublish").textContent).toBe(STRINGS.mcp.nextDeny);
    expect(within(row).getByTestId("mcp-two-step").textContent).toBe(STRINGS.mcp.twoStep);
    await user.click(within(row).getByRole("button", { name: STRINGS.unpublishDeny }));
    const bar = await screen.findByTestId("publish-drafted");
    expect(within(bar).getByTestId("drafted-stage").textContent).toBe("deny");
    const post = calls.find((c) => c.method === "POST");
    expect(post?.path).toBe(mcpActionPath(MCP_ID, "unpublish"));
    expect(post?.body).toMatchObject({ channel: "button" });
  });

  it("offers the remove step once access is denied", async () => {
    withLists([], [SERVER], {
      [`GET ${mcpPublicationPath(MCP_ID)}`]: {
        status: 200,
        body: status({
          state: "denied",
          next_unpublish_stage: "remove",
          next_publish_stage: "publish",
        }),
      },
    });
    const row = await screen.findByTestId("mcp-row");
    expect(await within(row).findByRole("button", { name: STRINGS.unpublishRemove })).toBeTruthy();
    expect(within(row).getByTestId("mcp-next-unpublish").textContent).toBe(STRINGS.mcp.nextRemove);
  });

  it("disables unpublish for an unpublished server and asks for gateway and path to publish", async () => {
    withLists([], [SERVER], {
      [`GET ${mcpPublicationPath(MCP_ID)}`]: {
        status: 200,
        body: status({
          state: "unpublished",
          gateway_id: null,
          api_path: null,
          next_publish_stage: "publish",
          next_unpublish_stage: null,
        }),
      },
    });
    const user = userEvent.setup();
    const row = await screen.findByTestId("mcp-row");
    await waitFor(() =>
      expect(
        (within(row).getByRole("button", { name: STRINGS.publish }) as HTMLButtonElement).disabled,
      ).toBe(false),
    );
    expect(
      (within(row).getByRole("button", { name: STRINGS.unpublish }) as HTMLButtonElement).disabled,
    ).toBe(true);
    await user.click(within(row).getByRole("button", { name: STRINGS.publish }));
    const dialog = await screen.findByRole("alertdialog", { hidden: true });
    expect(within(dialog).getByLabelText(STRINGS.dialog.apiPath, { exact: false })).toBeTruthy();
  });

  it("shows an honest message when the publication status cannot be read", async () => {
    withLists([], [SERVER], {});
    const row = await screen.findByTestId("mcp-row");
    expect(await within(row).findByTestId("mcp-status-unavailable")).toBeTruthy();
  });
});
