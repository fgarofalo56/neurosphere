import { beforeEach, describe, expect, it } from "vitest";
import {
  SOURCES_BUDGET_ID,
  SOURCES_CONNECTOR_ID,
  SOURCES_CONNECTOR_STALE,
  SOURCES_PRODUCER_ID,
  SOURCES_PRODUCER_STALE,
  SOURCES_SECRET,
  handle,
  resetAdminSources,
} from "./admin-sources.ts";
import type { FeatureMockContext } from "./context.ts";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Body = Record<string, any>;

interface Reply {
  readonly handled: boolean;
  readonly status: number;
  readonly headers: Record<string, string>;
  readonly body: Body;
  readonly text: string;
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
      end: (t: string) => {
        text = t;
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
  let body: Body = {};
  try {
    body = JSON.parse(text) as Body;
  } catch {
    body = {};
  }
  return { handled, status, headers, body, text };
}

const P = "/api/v1/admin/sources/producers";
const C = "/api/v1/admin/sources/connectors";
const PL = "/api/v1/admin/platform";
const S = "/api/v1/admin/system/settings";

beforeEach(resetAdminSources);

describe("admin-sources mock", () => {
  it("passes on other paths, including the settings list that admin-core owns", async () => {
    expect((await call("GET", "/api/v1/admin/platform/domains")).handled).toBe(false);
    expect((await call("GET", S)).handled).toBe(false);
    expect(handle({} as unknown as FeatureMockContext)).toBe(false);
  });

  it("answers 401 without a token and 403 for a non-admin persona on every area", async () => {
    expect((await call("GET", P, { authorized: false })).status).toBe(401);
    for (const path of [P, C, `${PL}/price-sheets`, `${PL}/budgets`, `${PL}/review-policy`, `${S}/copilot`]) {
      expect((await call("GET", path, { role: "viewer" })).status).toBe(403);
    }
    expect((await call("POST", "/api/v1/catalog/import", { role: "viewer", body: {} })).status).toBe(403);
  });

  it("returns the secret in exactly the create and rotate responses", async () => {
    const list = await call("GET", P);
    expect(list.text).not.toContain("SYNTHETIC");
    const one = await call("GET", `${P}/${SOURCES_PRODUCER_ID}`);
    expect(one.text).not.toContain("SYNTHETIC");
    expect(one.headers["etag"]).toBe('"producer-1"');
    const created = await call("POST", P, {
      body: { producer_id: "ingest-new", cloud: "commercial", sources: { s1: "gateway" } },
    });
    expect(created.status).toBe(201);
    expect(created.body["secret"]).toBe(SOURCES_SECRET);
    expect((await call("GET", P)).text).not.toContain(SOURCES_SECRET);
    const rotated = await call("POST", `${P}/${SOURCES_PRODUCER_ID}/rotate`, { ifMatch: '"producer-1"' });
    expect(rotated.status).toBe(200);
    expect(rotated.text).not.toContain(SOURCES_SECRET);
    expect(rotated.body["secret"]).toBeTypeOf("string");
  });

  it("answers 422, 409 and stale fixtures for producers", async () => {
    expect((await call("POST", P, { body: { producer_id: "bad id!", sources: {} } })).status).toBe(422);
    expect((await call("POST", P, { body: { producer_id: SOURCES_PRODUCER_ID, sources: { a: "gateway" } } })).status).toBe(409);
    expect((await call("POST", `${P}/${SOURCES_PRODUCER_STALE}/disable`, { ifMatch: '"producer-1"' })).status).toBe(409);
    expect((await call("POST", `${P}/${SOURCES_PRODUCER_ID}/disable`, { ifMatch: '"producer-9"' })).status).toBe(409);
    expect((await call("POST", `${P}/${SOURCES_PRODUCER_ID}/disable`, { ifMatch: '"producer-1"' })).body["status"]).toBe("disabled");
  });

  it("validates connector credential references and warns for otel", async () => {
    const config = {
      connector_id: "otel-main",
      connector_kind: "otel",
      domain_ids: ["d"],
      settings: {},
      enabled: true,
    };
    const bad = await call("POST", C, { body: { ...config, credential: { kind: "key_vault_secret", secret_uri: "hunter2" } } });
    expect(bad.status).toBe(422);
    expect(bad.body["detail"]).toContain("secret_uri");
    const ok = await call("POST", C, { body: { ...config, credential: null } });
    expect(ok.status).toBe(201);
    expect(ok.body["warnings"]).toEqual(["producer_not_in_store"]);
    expect((await call("POST", `${C}/${SOURCES_CONNECTOR_STALE}/disable`, { ifMatch: '"connector-1"' })).status).toBe(409);
    const retired = await call("DELETE", `${C}/${SOURCES_CONNECTOR_ID}`, { ifMatch: '"connector-1"' });
    expect(retired.body["status"]).toBe("retired");
    expect((await call("GET", C)).body["items"].some((i: Body) => i["connector_id"] === SOURCES_CONNECTOR_ID)).toBe(false);
  });

  it("keeps price sheets, budgets and amounts as decimal strings", async () => {
    const sheets = await call("GET", `${PL}/price-sheets`);
    expect(sheets.body["items"]).toHaveLength(2);
    const badRow = await call("POST", `${PL}/price-sheets`, {
      body: { snapshot_id: "s", rows: [{ retail_price: 0.1 }] },
    });
    expect(badRow.status).toBe(422);
    expect(badRow.body["detail"]).toContain("rows/0/retail_price");
    const budgets = await call("GET", `${PL}/budgets`);
    expect(budgets.body["items"][0]["amount"]).toBeTypeOf("string");
    const badBudget = await call("PUT", `${PL}/budgets/${SOURCES_BUDGET_ID}`, {
      ifMatch: '"budget-1"',
      body: { budget_id: SOURCES_BUDGET_ID, amount: "1e3" },
    });
    expect(badBudget.status).toBe(422);
  });

  it("round-trips the review policy and settings with ETags", async () => {
    const policy = await call("GET", `${PL}/review-policy`);
    expect(policy.headers["etag"]).toBe('"policy-1"');
    const stale = await call("PUT", `${PL}/review-policy`, { ifMatch: '"policy-9"', body: policy.body["document"] });
    expect(stale.status).toBe(409);
    const saved = await call("PUT", `${PL}/review-policy`, { ifMatch: '"policy-1"', body: policy.body["document"] });
    expect(saved.status).toBe(200);
    const setting = await call("GET", `${S}/copilot`);
    expect(setting.headers["etag"]).toBe('"setting-copilot-3"');
    const bad = await call("PUT", `${S}/copilot`, {
      ifMatch: '"setting-copilot-3"',
      body: { setting_key: "copilot", copilot: { endpoint: "https://wrong-cloud.invalid/x" } },
    });
    expect(bad.status).toBe(422);
    expect((await call("GET", `${S}/nope`)).status).toBe(404);
  });

  it("answers the import dry run and commit with mixed outcomes", async () => {
    const items = [{ id: "a" }, { id: "b", reject: true }, { name: "no id" }];
    const dry = await call("POST", "/api/v1/catalog/import", { body: { items, dry_run: true } });
    expect(dry.body["items"].map((i: Body) => i["status"])).toEqual(["valid", "rejected", "rejected"]);
    const tooMany = await call("POST", "/api/v1/catalog/import", {
      body: { items: Array.from({ length: 101 }, (_, i) => ({ id: String(i) })) },
    });
    expect(tooMany.status).toBe(422);
    const clean = await call("POST", "/api/v1/catalog/import", { body: { items: [{ id: "a" }], dry_run: false } });
    expect(clean.body).toMatchObject({ committed: true, dry_run: false });
  });
});
