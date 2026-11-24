import { beforeEach, describe, expect, it } from "vitest";
import type { FeatureMockContext } from "./context.ts";
import {
  DOMAIN_MAP_INCIDENT,
  INCIDENT_IDS as I,
  handle,
  incidentDomain,
  resetMapTopology,
} from "./map-topology.ts";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Body = Record<string, any>;

interface Reply {
  readonly handled: boolean;
  readonly status: number;
  readonly body: Body;
}

const base = (domain: string): string => `/api/v1/map/domains/${encodeURIComponent(domain)}`;

async function call(
  method: string,
  pathAndQuery: string,
  opts: { body?: unknown; authorized?: boolean } = {},
): Promise<Reply> {
  let status = 0;
  let text = "";
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
    url: new URL(`http://mock${pathAndQuery}`),
    cors: {},
    readBody: () => Promise.resolve(opts.body === undefined ? "" : JSON.stringify(opts.body)),
    authorized: opts.authorized ?? true,
    role: "admin",
    correlationId: "corr-test",
  } as unknown as FeatureMockContext;
  const handled = handle(ctx);
  if (handled) await finished;
  return { handled, status, body: text === "" ? {} : (JSON.parse(text) as Body) };
}

const D = DOMAIN_MAP_INCIDENT;
const ids = (r: Reply): string[] => r.body["nodes"].map((n: Body) => n["id"]);

beforeEach(resetMapTopology);

describe("map-topology mock", () => {
  it("passes every other path and domain through, and tolerates an empty context", async () => {
    expect((await call("GET", "/api/v1/map/domains/other/viewport")).handled).toBe(false);
    expect(
      (await call("GET", `${base("commercial:e2e:sandbox:domain:map-perf")}/viewport`)).handled,
    ).toBe(false);
    expect((await call("GET", `${base(D)}/unknown`)).handled).toBe(false);
    expect((await call("GET", "/api/v1/health")).handled).toBe(false);
    expect((await call("DELETE", `${base(D)}/viewport`)).handled).toBe(false);
    expect(handle({} as unknown as FeatureMockContext)).toBe(false);
  });

  it("answers 401 without a token", async () => {
    expect((await call("GET", `${base(D)}/viewport`, { authorized: false })).status).toBe(401);
  });

  it("serves a viewport with facets, a mix of kinds, and hides off-screen nodes", async () => {
    const r = await call("GET", `${base(D)}/viewport?node_budget=2000`);
    expect(r.status).toBe(200);
    const kinds = new Set(r.body["nodes"].map((n: Body) => n["kind"]));
    for (const k of ["service", "tool", "mcp_server", "agent", "model", "source", "person"]) {
      expect(kinds.has(k)).toBe(true);
    }
    expect(ids(r)).not.toContain(I.archive);
    expect(r.body["truncated"]).toBe(true);
    const ledger = r.body["nodes"].find((n: Body) => n["id"] === I.ledger);
    expect(ledger["facets"]).toMatchObject({
      environment: "production",
      cloud: "commercial",
      health: "failing",
      tags: ["payments"],
    });
    expect(ledger["facets"]["error_rate"]).toBeGreaterThan(0.1);
    // Unknown figures are null, never 0.
    const person = r.body["nodes"].find((n: Body) => n["id"] === I.person);
    expect(person["facets"]["error_rate"]).toBeNull();
    // Every edge joins two returned nodes.
    const have = new Set(ids(r));
    for (const e of r.body["edges"]) {
      expect(have.has(e["source"]) && have.has(e["target"])).toBe(true);
    }
  });

  it("honours every filter parameter in the viewport", async () => {
    const q = async (query: string): Promise<string[]> =>
      ids(await call("GET", `${base(D)}/viewport?${query}`));
    expect(await q("environment=staging")).toEqual([I.report, I.tax, I.gpt, I.queue]);
    expect(await q("cloud=government")).toEqual([I.docs]);
    expect(await q("health=failing")).toEqual([I.ledger]);
    expect(await q("node_type=service")).toEqual([I.ledger, I.queue]);
    expect(await q("tag=payments")).toEqual([I.ledger, I.billing, I.refund]);
    expect(await q("environment=staging&node_type=tool")).toEqual([I.tax]);
    expect(await q("environment=production&cloud=government&health=failing")).toEqual([]);
    expect(await q("cluster_id=cluster:x")).toEqual([]);
  });

  it("searches by label, counts the matches and includes off-screen nodes", async () => {
    const all = await call("GET", `${base(D)}/search?q=&limit=1`);
    expect(all.body["matches"]).toHaveLength(1);
    expect(all.body["counts"]["by_kind"]["agent"]).toBe(5);
    expect(all.body["counts"]["by_environment"]["staging"]).toBe(4);
    expect(all.body["counts"]["by_cloud"]["government"]).toBe(1);
    expect(all.body["counts"]["by_health"]).toMatchObject({ failing: 1, degraded: 1 });

    const hit = await call("GET", `${base(D)}/search?q=ARCH&limit=20`);
    expect(hit.body["matches"].map((m: Body) => m["node"]["id"])).toEqual([I.archive]);
    expect(hit.body["matches"][0]["node"]["facets"]["environment"]).toBe("production");

    const narrowed = await call("GET", `${base(D)}/search?q=agent&environment=staging`);
    expect(narrowed.body["matches"].map((m: Body) => m["node"]["id"])).toEqual([I.report]);
    expect(narrowed.body["counts"]["by_kind"]).toEqual({ agent: 1 });
    expect((await call("GET", `${base(D)}/search?q=zzz-none`)).body["matches"]).toEqual([]);
  });

  it("returns a node and its direct neighbours, and 404 for an unknown node", async () => {
    const r = await call("GET", `${base(D)}/neighborhood/${encodeURIComponent(I.archive)}`);
    expect(r.status).toBe(200);
    expect(ids(r).sort()).toEqual([I.archive, I.refund].sort());
    expect(r.body["edges"]).toHaveLength(1);
    const slashes = await call("GET", `${base(D)}/neighborhood/${I.archive}`);
    expect(slashes.status).toBe(200);
    expect((await call("GET", `${base(D)}/neighborhood/nope`)).status).toBe(404);
  });

  it("computes dependents by depth and validates the request", async () => {
    const post = (body: unknown): Promise<Reply> => call("POST", `${base(D)}/impact`, { body });
    const one = await post({ node_id: I.ledger, max_depth: 1 });
    expect(one.body["direction"]).toBe("dependents");
    expect(one.body["levels"]).toHaveLength(1);
    expect(one.body["levels"][0]["nodes"].map((n: Body) => n["id"]).sort()).toEqual(
      [I.billing, I.refund].sort(),
    );
    const two = await post({ node_id: I.ledger, max_depth: 2 });
    expect(two.body["levels"]).toHaveLength(2);
    expect(two.body["levels"][1]["depth"]).toBe(2);
    expect(two.body["levels"][1]["nodes"].map((n: Body) => n["id"]).sort()).toEqual(
      [I.archive, I.reconcile, I.report].sort(),
    );
    expect(two.body["levels"][1]["nodes"][0]).toMatchObject({ health: "ok", domain_id: D });
    expect(two.body["levels"][1]["edge_ids"]).toHaveLength(3);
    // A leaf has no dependents.
    expect((await post({ node_id: I.reconcile, max_depth: 3 })).body["levels"]).toEqual([]);
    expect((await post({ node_id: "nope", max_depth: 2 })).status).toBe(404);
    expect((await post({ node_id: I.ledger, max_depth: 6 })).status).toBe(422);
    expect((await post({ max_depth: 2 })).status).toBe(422);
    expect((await call("GET", `${base(D)}/impact`)).handled).toBe(false);
  });

  it("flips health through the control route and every answer follows", async () => {
    const control = (body: unknown): Promise<Reply> =>
      call("POST", `${base(D)}/__e2e/control`, { body });
    expect((await control({ action: "flip", node_id: I.billing, health: "failing" })).status).toBe(
      200,
    );
    const impact = await call("POST", `${base(D)}/impact`, {
      body: { node_id: I.ledger, max_depth: 1 },
    });
    const billing = impact.body["levels"][0]["nodes"].find((n: Body) => n["id"] === I.billing);
    expect(billing["health"]).toBe("failing");
    const view = await call("GET", `${base(D)}/viewport?health=failing`);
    expect(ids(view).sort()).toEqual([I.billing, I.ledger].sort());
    const found = await call("GET", `${base(D)}/search?q=billing`);
    expect(found.body["matches"][0]["node"]["metrics"]["health"]).toBe("failing");
    expect((await control({ action: "flip", node_id: "nope", health: "failing" })).status).toBe(
      422,
    );
    expect((await control({ action: "flip", node_id: I.billing, health: "bad" })).status).toBe(422);
    expect((await control({ action: "nope" })).status).toBe(422);
    await control({ action: "reset" });
    expect(ids(await call("GET", `${base(D)}/viewport?health=failing`))).toEqual([I.ledger]);
  });

  it("adds a node with a dependency edge through the control route", async () => {
    const added = await call("POST", `${base(D)}/__e2e/control`, {
      body: {
        action: "add_node",
        node_id: "inc:agent:new",
        label: "new-agent",
        depends_on: I.ledger,
      },
    });
    expect(added.status).toBe(200);
    const view = await call("GET", `${base(D)}/viewport`);
    expect(ids(view)).toContain("inc:agent:new");
    expect(view.body["edges"].some((e: Body) => e["source"] === "inc:agent:new")).toBe(true);
    const dup = await call("POST", `${base(D)}/__e2e/control`, {
      body: { action: "add_node", node_id: "inc:agent:new", label: "again" },
    });
    expect(dup.status).toBe(422);
  });

  it("keeps instances of the fixture family isolated", async () => {
    const other = incidentDomain("iso");
    await call("POST", `${base(other)}/__e2e/control`, {
      body: { action: "flip", node_id: I.tax, health: "failing" },
    });
    expect(ids(await call("GET", `${base(other)}/viewport?health=failing`))).toContain(I.tax);
    expect(ids(await call("GET", `${base(D)}/viewport?health=failing`))).not.toContain(I.tax);
    expect((await call("GET", `${base(incidentDomain("two-words"))}/viewport`)).status).toBe(200);
    // A look-alike domain outside the family is not answered.
    expect((await call("GET", `${base(`${D}-Bad_Suffix`)}/viewport`)).handled).toBe(false);
  });
});
