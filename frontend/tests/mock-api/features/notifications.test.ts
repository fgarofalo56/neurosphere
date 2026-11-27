import { beforeEach, describe, expect, it } from "vitest";
import type { FeatureMockContext } from "./context.ts";
import {
  NOTIFICATIONS_API,
  NOTIFICATION_BLOCKED_HOST,
  NOTIFICATION_CHANNEL_ID,
  NOTIFICATION_CROSS_CLOUD_HOST,
  NOTIFICATION_FLAKY_CHANNEL_ID,
  NOTIFICATION_SUBSCRIPTION_ID,
  handle,
  resetNotifications,
} from "./notifications.ts";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Body = Record<string, any>;

interface Reply {
  readonly handled: boolean;
  readonly status: number;
  readonly headers: Record<string, string>;
  readonly body: Body;
}

async function call(
  method: string,
  pathAndQuery: string,
  opts: { role?: string | undefined; body?: unknown; ifMatch?: string; authorized?: boolean } = {},
): Promise<Reply> {
  let status = 0;
  let headers: Record<string, string> = {};
  let text = "";
  let done: () => void = () => undefined;
  const finished = new Promise<void>((resolve) => {
    done = resolve;
  });
  const ctx = {
    req: { method, headers: opts.ifMatch === undefined ? {} : { "if-match": opts.ifMatch } },
    res: {
      writeHead: (s: number, h: Record<string, string>) => {
        status = s;
        headers = h;
      },
      end: (t?: string) => {
        text = t ?? "";
        done();
      },
    },
    url: new URL(`http://mock${pathAndQuery}`),
    cors: {},
    readBody: () => Promise.resolve(opts.body === undefined ? "" : JSON.stringify(opts.body)),
    authorized: opts.authorized ?? true,
    role: "role" in opts ? opts.role : "admin",
    correlationId: "corr-test",
  } as unknown as FeatureMockContext;
  const handled = handle(ctx);
  if (handled) await finished;
  const parse = (): Body => {
    try {
      return JSON.parse(text) as Body;
    } catch {
      return {};
    }
  };
  return { handled, status, headers, body: parse() };
}

const A = NOTIFICATIONS_API;

function newChannel(over: Body = {}): Body {
  return {
    schema_version: "1.0.0",
    channel_id: "new-hook",
    cloud: "commercial",
    customer_id: "e2e",
    domain_id: "commercial:e2e:sandbox:domain:finance",
    display_name: "New hook",
    kind: "webhook",
    allowed_host: "hooks.example.org",
    endpoint_credential: {
      kind: "key_vault_secret",
      secret_uri: "https://kv-e2e.vault.azure.net/secrets/new-endpoint",
    },
    hmac_credential: {
      kind: "key_vault_secret",
      secret_uri: "https://kv-e2e.vault.azure.net/secrets/new-signing",
    },
    local_sink: false,
    local_sink_url: null,
    enabled: true,
    ...over,
  };
}

beforeEach(resetNotifications);

describe("notifications mock", () => {
  it("passes on other paths and an empty context", async () => {
    expect((await call("GET", "/api/v1/admin/capture")).handled).toBe(false);
    expect(handle({} as unknown as FeatureMockContext)).toBe(false);
  });

  it("answers 401 without a token and 403 for a non-admin persona", async () => {
    expect((await call("GET", `${A}/channels`, { authorized: false })).status).toBe(401);
    for (const path of ["channels", "subscriptions", "deliveries", "channel-kinds"]) {
      const reply = await call("GET", `${A}/${path}`, { role: "viewer" });
      expect(reply.status).toBe(403);
      expect(reply.body["code"]).toBe("forbidden");
    }
  });

  it("lists the three kinds with their verdicts", async () => {
    const { body } = await call("GET", `${A}/channel-kinds`);
    expect(body["items"].map((k: Body) => [k["kind"], k["status"]])).toEqual([
      ["webhook", "buildable"],
      ["teams_webhook", "degraded"],
      ["email", "not_built"],
    ]);
  });

  it("lists channels with delivery counts, an ETag and no secret value", async () => {
    const { body, status } = await call("GET", `${A}/channels`);
    expect(status).toBe(200);
    const ops = body["items"].find(
      (v: Body) => v["channel"]["channel_id"] === NOTIFICATION_CHANNEL_ID,
    );
    expect(ops["delivery_counts"]["delivered"]).toBe(2);
    expect(ops["etag"]).toBe('"channel-1"');
    const flaky = body["items"].find(
      (v: Body) => v["channel"]["channel_id"] === NOTIFICATION_FLAKY_CHANNEL_ID,
    );
    expect(flaky["last_error_code"]).toBe("http_500");
    expect(JSON.stringify(body)).not.toMatch(/secret_value|password|client_secret/);
  });

  it("creates a channel and refuses not_built, egress and bad credential references", async () => {
    const created = await call("POST", `${A}/channels`, { body: newChannel() });
    expect(created.status).toBe(201);
    expect(created.headers["etag"]).toBe('"channel-1"');
    expect((await call("POST", `${A}/channels`, { body: newChannel() })).status).toBe(409);
    const email = await call("POST", `${A}/channels`, {
      body: newChannel({ channel_id: "mail", kind: "email" }),
    });
    expect([email.status, email.body["code"], email.body["reason"]]).toEqual([
      409,
      "capability_unavailable",
      "channel_kind_not_built",
    ]);
    const blocked = await call("POST", `${A}/channels`, {
      body: newChannel({ channel_id: "b1", allowed_host: NOTIFICATION_BLOCKED_HOST }),
    });
    expect([blocked.status, blocked.body["reason"]]).toEqual([422, "host_not_allowed"]);
    const cross = await call("POST", `${A}/channels`, {
      body: newChannel({ channel_id: "b2", allowed_host: NOTIFICATION_CROSS_CLOUD_HOST }),
    });
    expect([cross.status, cross.body["reason"]]).toEqual([422, "cloud_boundary"]);
    const raw = await call("POST", `${A}/channels`, {
      body: newChannel({
        channel_id: "b3",
        endpoint_credential: { kind: "key_vault_secret", secret_uri: "not-a-reference" },
      }),
    });
    expect([raw.status, raw.body["reason"]]).toEqual([422, "invalid_credential_reference"]);
  });

  it("requires If-Match: 422 precondition_required without, 409 stale_version on a mismatch, 200 and a new ETag when right", async () => {
    const path = `${A}/channels/${NOTIFICATION_CHANNEL_ID}`;
    const body = newChannel({ channel_id: NOTIFICATION_CHANNEL_ID, enabled: false });
    expect((await call("PUT", path, { body })).status).toBe(422);
    expect((await call("PUT", path, { body, ifMatch: '"channel-9"' })).status).toBe(409);
    const ok = await call("PUT", path, { body, ifMatch: '"channel-1"' });
    expect(ok.status).toBe(200);
    expect(ok.body["version"]).toBe(2);
    expect(ok.headers["etag"]).toBe('"channel-2"');
    expect((await call("DELETE", path)).status).toBe(422);
    expect((await call("DELETE", path, { ifMatch: '"channel-2"' })).status).toBe(204);
    expect((await call("GET", path)).status).toBe(404);
  });

  it("answers a test send, failing for the flaky channel", async () => {
    const ok = await call("POST", `${A}/channels/${NOTIFICATION_CHANNEL_ID}/test`);
    expect(ok.body).toEqual({ ok: true, status_code: 200, reason_code: null });
    const bad = await call("POST", `${A}/channels/${NOTIFICATION_FLAKY_CHANNEL_ID}/test`);
    expect(bad.body).toEqual({ ok: false, status_code: 500, reason_code: "http_500" });
    expect((await call("POST", `${A}/channels/missing/test`)).status).toBe(404);
  });

  it("manages subscriptions with the same If-Match rules and refuses an unknown channel", async () => {
    const list = await call("GET", `${A}/subscriptions`);
    expect(list.body["items"]).toHaveLength(1);
    const sub = list.body["items"][0]["subscription"] as Body;
    const created = await call("POST", `${A}/subscriptions`, {
      body: { ...sub, subscription_id: "second" },
    });
    expect(created.status).toBe(201);
    const unknown = await call("POST", `${A}/subscriptions`, {
      body: { ...sub, subscription_id: "third", channel_id: "nope" },
    });
    expect([unknown.status, unknown.body["reason"]]).toEqual([422, "unknown_channel"]);
    const path = `${A}/subscriptions/${NOTIFICATION_SUBSCRIPTION_ID}`;
    expect((await call("PUT", path, { body: sub })).status).toBe(422);
    expect((await call("PUT", path, { body: sub, ifMatch: '"subscription-1"' })).status).toBe(200);
    expect((await call("DELETE", path, { ifMatch: '"subscription-2"' })).status).toBe(204);
  });

  it("filters deliveries by status and channel", async () => {
    expect((await call("GET", `${A}/deliveries`)).body["items"]).toHaveLength(4);
    const failed = await call("GET", `${A}/deliveries?status=failed`);
    expect(failed.body["items"]).toHaveLength(1);
    const ops = await call("GET", `${A}/deliveries?channel_id=${NOTIFICATION_CHANNEL_ID}&limit=2`);
    expect(ops.body["items"]).toHaveLength(2);
  });
});
