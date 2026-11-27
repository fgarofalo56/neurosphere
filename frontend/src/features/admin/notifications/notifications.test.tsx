import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import {
  fakeFetch,
  problem,
  renderAdmin,
  stubResizeObserver,
  type FakeReply,
  type FakeRequest,
} from "../shared/test-support";
import { ADMIN_AREAS } from "../shared/areas";
import { adminCoreRoutes } from "../routes";
import { NotificationsPage } from "./NotificationsPage";
import { ADMIN_NOTIFICATIONS_ROUTE, notificationPaths } from "./paths";
import type { ChannelView, NotificationChannel, SubscriptionView } from "./types";

beforeAll(stubResizeObserver);
// Fluent dialogs and long forms make several userEvent steps per test slow under jsdom.
vi.setConfig({ testTimeout: 40_000 });
afterEach(cleanup);

const ENDPOINT = "https://kv-test.vault.azure.net/secrets/hook-endpoint";
const SIGNING = "https://kv-test.vault.azure.net/secrets/hook-signing";
const DOMAIN = "commercial:test:sandbox:domain:finance";

function channel(over: Partial<NotificationChannel> = {}): NotificationChannel {
  return {
    schema_version: "1.0.0",
    channel_id: "ops-hook",
    cloud: "commercial",
    customer_id: "test",
    domain_id: DOMAIN,
    display_name: "Ops hook",
    kind: "webhook",
    allowed_host: "hooks.example.org",
    endpoint_credential: { kind: "key_vault_secret", secret_uri: ENDPOINT },
    hmac_credential: { kind: "key_vault_secret", secret_uri: SIGNING },
    local_sink: false,
    local_sink_url: null,
    enabled: true,
    ...over,
  };
}

function view(c: NotificationChannel, over: Partial<ChannelView> = {}): ChannelView {
  return {
    channel: c,
    version: 1,
    etag: '"channel-1"',
    updated_at: "2026-11-26T09:00:00Z",
    updated_by: "psn-test",
    delivery_counts: {
      pending: 0,
      sending: 0,
      delivered: 3,
      failed: 1,
      dead_lettered: 0,
      suppressed: 0,
    },
    last_error_code: "http_500",
    ...over,
  };
}

const KINDS = {
  items: [
    { kind: "webhook", status: "buildable", reason: null },
    {
      kind: "teams_webhook",
      status: "degraded",
      reason: "teams_workflows_commercial_and_gcc_only",
    },
    { kind: "email", status: "not_built", reason: "email_transport_not_built" },
  ],
};

const SUB: SubscriptionView = {
  subscription: {
    schema_version: "1.0.0",
    subscription_id: "ops-hitl",
    cloud: "commercial",
    customer_id: "test",
    domain_id: DOMAIN,
    channel_id: "ops-hook",
    event_classes: ["hitl_item_assigned"],
    audience_roles: ["domain_steward"],
    min_severity: "medium",
    enabled: true,
  },
  version: 1,
  etag: '"subscription-1"',
  updated_at: "2026-11-26T09:00:00Z",
  updated_by: "psn-test",
};

const DELIVERY = {
  notification_id: "00000000-0000-4000-8000-000000000001",
  channel_id: "ops-hook",
  subscription_id: "ops-hitl",
  domain_id: DOMAIN,
  event_class: "hitl_item_assigned",
  severity: "medium",
  title: "Review item assigned",
  status: "failed",
  attempts: 3,
  last_error_code: "http_500",
  created_at: "2026-11-26T09:00:00Z",
  delivered_at: null,
};

function api(extra?: (req: FakeRequest) => FakeReply | undefined) {
  return fakeFetch((req) => {
    const extraReply = extra?.(req);
    if (extraReply !== undefined) return extraReply;
    const path = req.url.pathname;
    if (path === notificationPaths.kinds()) return { body: KINDS };
    if (path === notificationPaths.channels() && req.method === "GET") {
      return { body: { items: [view(channel())] } };
    }
    if (path === notificationPaths.subscriptions() && req.method === "GET") {
      return { body: { items: [SUB] } };
    }
    if (path === notificationPaths.deliveries()) return { body: { items: [DELIVERY] } };
    return undefined;
  });
}

/** The API answers a DELETE with 204 and a null body, which the fake fetch cannot build. */
function withNoContentDelete() {
  const base = api();
  const deletes: Headers[] = [];
  const impl: typeof fetch = (input, init) => {
    if (init?.method === "DELETE") {
      deletes.push(new Headers(init.headers));
      return Promise.resolve(new Response(null, { status: 204 }));
    }
    return base.impl(input, init);
  };
  return { impl, deletes };
}

async function confirm(): Promise<void> {
  const dialog = within(await screen.findByTestId("change-confirm-dialog"));
  await userEvent.click(dialog.getByRole("button", { name: "Confirm change", hidden: true }));
}

describe("notifications admin wiring", () => {
  it("is an admin area and a route", () => {
    expect(ADMIN_AREAS.some((a) => a.to === `/${ADMIN_NOTIFICATIONS_ROUTE}`)).toBe(true);
    expect(adminCoreRoutes.some((r) => r.path === ADMIN_NOTIFICATIONS_ROUTE)).toBe(true);
  });
});

describe("Channels tab", () => {
  it("lists channels with kind, host, state, delivery counts and the last error", async () => {
    const { impl } = api();
    renderAdmin(<NotificationsPage />, impl);
    const row = await screen.findByTestId("channel-row");
    expect(row.textContent).toContain("ops-hook");
    expect(row.textContent).toContain("webhook");
    expect(row.textContent).toContain("hooks.example.org");
    expect(row.textContent).toContain("Enabled");
    expect(within(row).getByTestId("channel-counts").textContent).toBe("delivered 3, failed 1");
    expect(row.textContent).toContain("http_500");
  });

  it("shows the forbidden state on 403", async () => {
    const { impl } = fakeFetch(() => problem(403, "forbidden", "customer_scope_required"));
    renderAdmin(<NotificationsPage />, impl);
    expect(await screen.findByTestId("forbidden-state")).toBeTruthy();
  });

  it("disables not_built kinds with their reason and labels degraded ones", async () => {
    const { impl } = api();
    renderAdmin(<NotificationsPage />, impl);
    await screen.findByTestId("channel-row");
    await userEvent.click(screen.getByRole("button", { name: "New channel" }));
    const kind = (await screen.findByLabelText("Kind")) as HTMLSelectElement;
    const options = Array.from(kind.options);
    const email = options.find((o) => o.value === "email");
    expect(email?.disabled).toBe(true);
    expect(email?.textContent).toContain("email_transport_not_built");
    const teams = options.find((o) => o.value === "teams_webhook");
    expect(teams?.disabled).toBe(false);
    expect(teams?.textContent).toContain("teams_workflows_commercial_and_gcc_only");
    expect(screen.getByTestId("secret-note").textContent).toContain("never a secret value");
  });

  it("creates a channel with Key Vault references only, after the confirm dialog", async () => {
    const { impl, calls } = api((req) =>
      req.method === "POST" && req.url.pathname === notificationPaths.channels()
        ? {
            status: 201,
            body: view(channel({ channel_id: "new-hook" })),
            headers: { ETag: '"channel-1"' },
          }
        : undefined,
    );
    renderAdmin(<NotificationsPage />, impl);
    await screen.findByTestId("channel-row");
    await userEvent.click(screen.getByRole("button", { name: "New channel" }));
    fireEvent.change(await screen.findByLabelText(/^Channel id/, { selector: "input" }), {
      target: { value: "new-hook" },
    });
    fireEvent.change(screen.getByLabelText(/^Display name/, { selector: "input" }), {
      target: { value: "New hook" },
    });
    fireEvent.change(screen.getByLabelText(/^Allowed host/, { selector: "input" }), {
      target: { value: "hooks.example.org" },
    });
    // A raw secret is refused client-side and nothing is sent.
    fireEvent.change(
      screen.getByLabelText(/Endpoint secret \(Key Vault secret reference/, { selector: "input" }),
      { target: { value: "s3cr3t-value-not-a-uri" } },
    );
    fireEvent.change(
      screen.getByLabelText(/Signing secret \(Key Vault secret reference/, { selector: "input" }),
      { target: { value: SIGNING } },
    );
    await userEvent.click(screen.getByRole("button", { name: "Review change" }));
    expect(await screen.findByText(/Not a Key Vault secret reference/)).toBeTruthy();
    expect(screen.queryByTestId("change-confirm-dialog")).toBeNull();
    fireEvent.change(
      screen.getByLabelText(/Endpoint secret \(Key Vault secret reference/, { selector: "input" }),
      { target: { value: ENDPOINT } },
    );
    await userEvent.click(screen.getByRole("button", { name: "Review change" }));
    await confirm();
    await waitFor(() => expect(calls.some((c) => c.method === "POST")).toBe(true));
    const post = calls.find((c) => c.method === "POST");
    const sent = post?.body as NotificationChannel;
    expect(sent.channel_id).toBe("new-hook");
    expect(sent.endpoint_credential).toEqual({ kind: "key_vault_secret", secret_uri: ENDPOINT });
    expect(JSON.stringify(sent)).not.toContain("s3cr3t");
    await waitFor(() => expect(screen.queryByTestId("channel-form")).toBeNull());
  });

  it("shows the API refusal reason when create is refused", async () => {
    const { impl } = api((req) =>
      req.method === "POST" ? problem(422, "invalid_schema", "host_not_allowed") : undefined,
    );
    renderAdmin(<NotificationsPage />, impl);
    await screen.findByTestId("channel-row");
    await userEvent.click(screen.getByRole("button", { name: "New channel" }));
    fireEvent.change(await screen.findByLabelText(/^Channel id/, { selector: "input" }), {
      target: { value: "bad" },
    });
    fireEvent.change(screen.getByLabelText(/^Display name/, { selector: "input" }), {
      target: { value: "Bad" },
    });
    fireEvent.change(screen.getByLabelText(/^Allowed host/, { selector: "input" }), {
      target: { value: "evil.example.net" },
    });
    fireEvent.change(screen.getByLabelText(/Endpoint secret \(/, { selector: "input" }), {
      target: { value: ENDPOINT },
    });
    fireEvent.change(screen.getByLabelText(/Signing secret \(/, { selector: "input" }), {
      target: { value: SIGNING },
    });
    await userEvent.click(screen.getByRole("button", { name: "Review change" }));
    await confirm();
    expect((await screen.findByTestId("notification-error")).textContent).toContain(
      "host_not_allowed",
    );
  });

  it("disables a channel with If-Match from the loaded ETag", async () => {
    const { impl, calls } = api((req) =>
      req.method === "PUT"
        ? { body: view(channel({ enabled: false }), { etag: '"channel-2"' }) }
        : undefined,
    );
    renderAdmin(<NotificationsPage />, impl);
    await screen.findByTestId("channel-row");
    await userEvent.click(screen.getByRole("button", { name: "Disable ops-hook" }));
    const dialog = within(await screen.findByTestId("change-confirm-dialog"));
    expect(dialog.getByTestId("change-diff").textContent).toContain("enabled");
    await confirm();
    await waitFor(() => expect(calls.some((c) => c.method === "PUT")).toBe(true));
    const put = calls.find((c) => c.method === "PUT");
    expect(put?.headers.get("If-Match")).toBe('"channel-1"');
    expect((put?.body as NotificationChannel).enabled).toBe(false);
  });

  it("explains a stale version on 412", async () => {
    const { impl } = api((req) =>
      req.method === "PUT" ? problem(412, "stale_version", "etag_mismatch") : undefined,
    );
    renderAdmin(<NotificationsPage />, impl);
    await screen.findByTestId("channel-row");
    await userEvent.click(screen.getByRole("button", { name: "Disable ops-hook" }));
    await confirm();
    expect((await screen.findByTestId("notification-error")).textContent).toContain("Reload");
  });

  it("deletes with If-Match and treats 204 as success", async () => {
    const { impl, deletes } = withNoContentDelete();
    renderAdmin(<NotificationsPage />, impl);
    await screen.findByTestId("channel-row");
    await userEvent.click(screen.getByRole("button", { name: "Delete ops-hook" }));
    await confirm();
    await waitFor(() => expect(deletes).toHaveLength(1));
    expect(deletes[0]?.get("If-Match")).toBe('"channel-1"');
    await waitFor(() => expect(screen.queryByTestId("change-confirm-dialog")).toBeNull());
    expect(screen.queryByTestId("notification-error")).toBeNull();
  });

  it("shows the test send outcome", async () => {
    const ok = api((req) =>
      req.method === "POST" && req.url.pathname === notificationPaths.channelTest("ops-hook")
        ? { body: { ok: true, status_code: 200, reason_code: null } }
        : undefined,
    );
    renderAdmin(<NotificationsPage />, ok.impl);
    await screen.findByTestId("channel-row");
    await userEvent.click(screen.getByRole("button", { name: "Send test to ops-hook" }));
    await confirm();
    expect((await screen.findByTestId("test-result")).textContent).toBe(
      "Test send to ops-hook succeeded (HTTP 200).",
    );
    cleanup();
    const bad = api((req) =>
      req.method === "POST" && req.url.pathname === notificationPaths.channelTest("ops-hook")
        ? { body: { ok: false, status_code: 500, reason_code: "http_500" } }
        : undefined,
    );
    renderAdmin(<NotificationsPage />, bad.impl);
    await screen.findByTestId("channel-row");
    await userEvent.click(screen.getByRole("button", { name: "Send test to ops-hook" }));
    await confirm();
    expect((await screen.findByTestId("test-result")).textContent).toContain(
      "failed: http_500 (HTTP 500)",
    );
  });
});

describe("Subscriptions tab", () => {
  it("lists subscriptions and creates one for a channel", async () => {
    const { impl, calls } = api((req) =>
      req.method === "POST" && req.url.pathname === notificationPaths.subscriptions()
        ? { status: 201, body: SUB }
        : undefined,
    );
    renderAdmin(<NotificationsPage />, impl);
    await userEvent.click(await screen.findByRole("tab", { name: "Subscriptions" }));
    const row = await screen.findByTestId("subscription-row");
    expect(row.textContent).toContain("hitl_item_assigned");
    expect(row.textContent).toContain("domain_steward");
    await userEvent.click(screen.getByRole("button", { name: "New subscription" }));
    fireEvent.change(await screen.findByLabelText(/^Subscription id/, { selector: "input" }), {
      target: { value: "second" },
    });
    await userEvent.click(screen.getByRole("checkbox", { name: "action_failed" }));
    await userEvent.click(screen.getByRole("checkbox", { name: "admin" }));
    await userEvent.click(screen.getByRole("button", { name: "Review change" }));
    await confirm();
    await waitFor(() => expect(calls.some((c) => c.method === "POST")).toBe(true));
    const sent = calls.find((c) => c.method === "POST")?.body as SubscriptionView["subscription"];
    expect(sent.subscription_id).toBe("second");
    expect(sent.channel_id).toBe("ops-hook");
    expect(sent.event_classes).toEqual(["action_failed"]);
    expect(sent.audience_roles).toEqual(["admin"]);
  });

  it("requires at least one event class and one role", async () => {
    const { impl, calls } = api();
    renderAdmin(<NotificationsPage />, impl);
    await userEvent.click(await screen.findByRole("tab", { name: "Subscriptions" }));
    await screen.findByTestId("subscription-row");
    await userEvent.click(screen.getByRole("button", { name: "New subscription" }));
    fireEvent.change(await screen.findByLabelText(/^Subscription id/, { selector: "input" }), {
      target: { value: "empty" },
    });
    await userEvent.click(screen.getByRole("button", { name: "Review change" }));
    expect(await screen.findByText("Pick at least one event class")).toBeTruthy();
    expect(screen.queryByTestId("change-confirm-dialog")).toBeNull();
    expect(calls.some((c) => c.method === "POST")).toBe(false);
  });

  it("deletes a subscription with If-Match", async () => {
    const { impl, deletes } = withNoContentDelete();
    renderAdmin(<NotificationsPage />, impl);
    await userEvent.click(await screen.findByRole("tab", { name: "Subscriptions" }));
    await screen.findByTestId("subscription-row");
    await userEvent.click(screen.getByRole("button", { name: "Delete subscription ops-hitl" }));
    await confirm();
    await waitFor(() => expect(deletes).toHaveLength(1));
    expect(deletes[0]?.get("If-Match")).toBe('"subscription-1"');
  });
});

describe("Deliveries tab", () => {
  it("lists deliveries and filters by status through the query", async () => {
    const { impl, calls } = api();
    renderAdmin(<NotificationsPage />, impl);
    await userEvent.click(await screen.findByRole("tab", { name: "Deliveries" }));
    const row = await screen.findByTestId("delivery-row");
    expect(row.textContent).toContain("failed");
    expect(row.textContent).toContain("hitl_item_assigned");
    expect(row.textContent).toContain("ops-hook");
    expect(row.textContent).toContain("3");
    expect(row.textContent).toContain("http_500");
    fireEvent.change(screen.getByLabelText("Status filter"), { target: { value: "delivered" } });
    await waitFor(() =>
      expect(
        calls.some(
          (c) =>
            c.url.pathname === notificationPaths.deliveries() &&
            c.url.searchParams.get("status") === "delivered",
        ),
      ).toBe(true),
    );
  });
});
