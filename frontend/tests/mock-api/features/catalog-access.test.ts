import { describe, expect, it } from "vitest";
import {
  ACCESS_ASSET_EMPTY,
  ACCESS_ASSET_FORBIDDEN,
  ACCESS_ASSET_LEDGER,
  ACCESS_ASSET_TRUNCATED,
  ACCESS_NODE_EMPTY,
  ACCESS_NODE_FORBIDDEN,
  ACCESS_NODE_SERVICE,
  ACCESS_NODE_TRUNCATED,
  handle,
} from "./catalog-access.ts";
import type { FeatureMockContext } from "./context.ts";

// A loosely typed JSON body: the assertions below index into it freely.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Body = Record<string, any>;

interface Reply {
  readonly handled: boolean;
  readonly status: number;
  readonly body: Body;
  readonly problem: { status: number; code: string; reason: string | undefined } | null;
}

const BASE = "/api/v1/catalog/access";

async function call(
  method: string,
  path: string,
  body?: unknown,
  authorized = true,
): Promise<Reply> {
  let status = 0;
  let text = "";
  let problem: Reply["problem"] = null;
  let done: () => void = () => undefined;
  const finished = new Promise<void>((resolve) => {
    done = resolve;
  });
  const ctx = {
    req: { method, headers: {} },
    res: {
      writeHead: (s: number) => {
        status = s;
      },
      end: (t: string) => {
        text = t;
        done();
      },
    },
    url: new URL(`http://mock${path}`),
    cors: {},
    readBody: () => Promise.resolve(body === undefined ? "" : JSON.stringify(body)),
    authorized,
    role: "admin",
    correlationId: "corr-test",
    problem: (s: number, code: string, reason: string | undefined) => {
      problem = { status: s, code, reason };
      status = s;
      done();
    },
    forbidden: () => {
      problem = { status: 403, code: "forbidden", reason: undefined };
      status = 403;
      done();
    },
  } as unknown as FeatureMockContext;
  const handled = handle(ctx);
  if (handled) await finished;
  return { handled, status, body: text === "" ? {} : (JSON.parse(text) as Body), problem };
}

const query = (over: Record<string, unknown> = {}) =>
  call("POST", `${BASE}/query`, {
    asset_ids: [ACCESS_ASSET_LEDGER],
    filters: {},
    modes: ["read", "write"],
    include_unassessed: false,
    ...over,
  });

describe("catalog-access mock", () => {
  it("passes on other paths, wrong methods and a context without a url", async () => {
    expect((await call("GET", "/api/v1/catalog/entities")).handled).toBe(false);
    expect((await call("GET", `${BASE}/query`)).handled).toBe(false);
    expect((await call("POST", `${BASE}/region-groups`, {})).handled).toBe(false);
    expect(handle({} as unknown as FeatureMockContext)).toBe(false);
  });

  it("answers 401 without a token", async () => {
    expect((await call("GET", `${BASE}/region-groups`, undefined, false)).status).toBe(401);
    expect((await query()).handled).toBe(true);
  });

  it("lists region groups", async () => {
    const reply = await call("GET", `${BASE}/region-groups`);
    expect(reply.body["groups"].map((g: Body) => g["name"])).toEqual(["eu", "europe"]);
  });

  it("answers a normal result with all three edge statuses and evidence", async () => {
    const reply = await query();
    expect(reply.status).toBe(200);
    expect(reply.body["truncated"]).toBe(false);
    expect(reply.body["unassessed_assets"]).toBeNull();
    const statuses = reply.body["rows"].map((r: Body) => r["status"]).sort();
    expect(statuses).toEqual(["asserted", "curated", "inferred"]);
    expect(reply.body["rows"][0]["evidence_ids"]).toEqual(["trace:a1", "trace:a2"]);
  });

  it("honours the requested modes", async () => {
    const reply = await query({ modes: ["write"] });
    expect(reply.body["rows"].every((r: Body) => r["mode"] === "write")).toBe(true);
  });

  it("answers an empty result", async () => {
    const reply = await query({ asset_ids: [ACCESS_ASSET_EMPTY] });
    expect(reply.body["rows"]).toEqual([]);
    expect(reply.body["truncated"]).toBe(false);
  });

  it("answers a truncated result with a reason and the scan count", async () => {
    const reply = await query({ asset_ids: [ACCESS_ASSET_TRUNCATED] });
    expect(reply.body["truncated"]).toBe(true);
    expect(reply.body["truncated_reason"]).toBe("max_assets");
    expect(reply.body["assets_scanned"]).toBe(200);
  });

  it("adds not assessed assets with null values only when asked", async () => {
    const reply = await query({ include_unassessed: true });
    expect(reply.body["unassessed_count"]).toBe(2);
    expect(reply.body["unassessed_assets"][0]["sensitivity_categories"]).toBeNull();
    expect(reply.body["unassessed_assets"][0]["contains_personal_data"]).toBeNull();
  });

  it("answers 403 for the forbidden asset", async () => {
    const reply = await query({ asset_ids: [ACCESS_ASSET_FORBIDDEN] });
    expect(reply.problem).toEqual({ status: 403, code: "forbidden", reason: undefined });
  });

  it("answers 422 for an unknown region group and for too many assets", async () => {
    const group = await query({ asset_ids: [], filters: { region_group: "mars" } });
    expect(group.problem).toMatchObject({ status: 422, reason: "unknown_region_group" });
    const many = await query({ asset_ids: Array.from({ length: 51 }, (_, i) => `a${String(i)}`) });
    expect(many.problem).toMatchObject({ status: 422, reason: "too_many_assets" });
    const ok = await query({ asset_ids: [], filters: { region_group: "eu" } });
    expect(ok.status).toBe(200);
  });

  it("groups dependents by depth and limits them to max_depth", async () => {
    const deep = await call("POST", `${BASE}/dependents`, {
      node_id: ACCESS_NODE_SERVICE,
      max_depth: 3,
    });
    expect(deep.body["groups"].map((g: Body) => g["depth"])).toEqual([1, 2, 3]);
    expect(deep.body["total"]).toBe(4);
    expect(deep.body["groups"][1]["rows"][0]["relation_path"]).toEqual(["invokes", "uses_tool"]);
    const shallow = await call("POST", `${BASE}/dependents`, {
      node_id: ACCESS_NODE_SERVICE,
      max_depth: 1,
    });
    expect(shallow.body["total"]).toBe(1);
  });

  it("answers empty, truncated and forbidden dependents", async () => {
    const empty = await call("POST", `${BASE}/dependents`, {
      node_id: ACCESS_NODE_EMPTY,
      max_depth: 2,
    });
    expect(empty.body["groups"]).toEqual([]);
    const partial = await call("POST", `${BASE}/dependents`, {
      node_id: ACCESS_NODE_TRUNCATED,
      max_depth: 2,
    });
    expect(partial.body["truncated_reason"]).toBe("max_depth");
    const denied = await call("POST", `${BASE}/dependents`, {
      node_id: ACCESS_NODE_FORBIDDEN,
      max_depth: 2,
    });
    expect(denied.status).toBe(403);
  });

  it("answers 422 for a depth outside 1 to 5", async () => {
    const high = await call("POST", `${BASE}/dependents`, {
      node_id: ACCESS_NODE_SERVICE,
      max_depth: 6,
    });
    expect(high.problem).toMatchObject({ status: 422, reason: "max_depth_exceeded" });
    const low = await call("POST", `${BASE}/dependents`, {
      node_id: ACCESS_NODE_SERVICE,
      max_depth: 0,
    });
    expect(low.problem).toMatchObject({ status: 422, reason: "invalid_depth" });
  });
});
