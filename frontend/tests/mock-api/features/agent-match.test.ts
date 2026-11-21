import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { beforeEach, describe, expect, it } from "vitest";
import {
  MATCH_COLD_START_ENTITY,
  MATCH_COLD_START_SIGNALS,
  MATCH_EMPTY_TASK_TEXT,
  MATCH_GRAPH_ENTITY,
  MATCH_GRAPH_RELATED,
  MATCH_PARTIAL_TASK_TEXT,
  MATCH_REASON_DOMAIN,
  MATCH_REASON_UNKNOWN_CANDIDATE,
  MATCH_REASON_UNKNOWN_MATCH,
  MATCH_REASON_VIEWER,
  MATCH_TASK_TEXT,
  MATCH_TELEMETRY_ENTITY,
  handle,
  resetAgentMatch,
} from "./agent-match.ts";
import type { FeatureMockContext } from "./context.ts";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Body = Record<string, any>;

const DOMAIN = "commercial:e2e:sandbox:domain:finance";
const OTHER_DOMAIN = "commercial:e2e:sandbox:domain:forbidden";
const BASE = `/api/v1/recommendations/domains/${encodeURIComponent(DOMAIN)}/match`;

interface Reply {
  readonly handled: boolean;
  readonly status: number;
  readonly body: Body;
}

async function call(
  method: string,
  path: string,
  opts: { role?: string | undefined; body?: unknown; authorized?: boolean } = {},
): Promise<Reply> {
  let status = 0;
  let text = "";
  let done: () => void = () => undefined;
  const finished = new Promise<void>((resolveDone) => {
    done = resolveDone;
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
    readBody: () => Promise.resolve(opts.body === undefined ? "" : JSON.stringify(opts.body)),
    authorized: opts.authorized ?? true,
    readableDomains: [DOMAIN],
    role: "role" in opts ? opts.role : "analyst",
    correlationId: "corr-test",
  } as unknown as FeatureMockContext;
  const handled = handle(ctx);
  if (handled) await finished;
  return { handled, status, body: text === "" ? {} : (JSON.parse(text) as Body) };
}

const request = (task: string, extra: Body = {}): Body => ({
  schema_version: "1.0.0",
  task_text: task,
  ...extra,
});
const match = (task: string, opts: { role?: string | undefined } = {}): Promise<Reply> =>
  call("POST", BASE, { ...opts, body: request(task) });
const feedback = (
  matchId: string,
  entityId: string,
  decision: string,
  opts: { role?: string | undefined } = {},
): Promise<Reply> =>
  call("POST", `${BASE}/feedback`, {
    ...opts,
    body: { schema_version: "1.0.0", match_id: matchId, entity_id: entityId, decision },
  });
const metrics = (opts: { role?: string | undefined } = {}): Promise<Reply> =>
  call("GET", `${BASE}/metrics`, opts);

// ---- a small JSON Schema checker: the frontend has no direct ajv dependency, and the PRP-70
// schemas use only these keywords (plus $ref across files, resolved by path).
const SCHEMAS = resolve(
  dirname(fileURLToPath(import.meta.url)),
  "../../../../packages/contracts/schemas",
);
type Schema = Record<string, unknown>;
interface Scope {
  readonly file: string;
  readonly root: Schema;
}
const cache = new Map<string, Schema>();
function load(file: string): Schema {
  let doc = cache.get(file);
  if (doc === undefined) {
    doc = JSON.parse(readFileSync(file, "utf8")) as Schema;
    cache.set(file, doc);
  }
  return doc;
}
function resolveRef(ref: string, scope: Scope): { schema: Schema; scope: Scope } {
  const [filePart = "", pointer = ""] = ref.split("#");
  const file = filePart === "" ? scope.file : resolve(dirname(scope.file), filePart);
  const root = filePart === "" ? scope.root : load(file);
  let node: unknown = root;
  for (const seg of pointer.split("/").filter((s) => s !== "")) {
    node = (node as Schema)[seg];
  }
  return { schema: node as Schema, scope: { file, root } };
}

function check(value: unknown, schema: Schema, scope: Scope, at: string): string[] {
  if (typeof schema["$ref"] === "string") {
    const next = resolveRef(schema["$ref"], scope);
    return check(value, next.schema, next.scope, at);
  }
  const errors: string[] = [];
  const oneOf = schema["oneOf"] as Schema[] | undefined;
  if (oneOf !== undefined) {
    const passing = oneOf.filter((s) => check(value, s, scope, at).length === 0).length;
    if (passing !== 1) errors.push(`${at}: oneOf matched ${String(passing)}`);
    return errors;
  }
  const type = schema["type"] as string | undefined;
  const isInt = typeof value === "number" && Number.isInteger(value);
  const typeOk =
    type === undefined ||
    (type === "string" && typeof value === "string") ||
    (type === "number" && typeof value === "number") ||
    (type === "integer" && isInt) ||
    (type === "boolean" && typeof value === "boolean") ||
    (type === "null" && value === null) ||
    (type === "array" && Array.isArray(value)) ||
    (type === "object" && typeof value === "object" && value !== null && !Array.isArray(value));
  if (!typeOk) return [`${at}: expected ${String(type)}`];
  if (schema["enum"] !== undefined && !(schema["enum"] as unknown[]).includes(value)) {
    errors.push(`${at}: not in enum`);
  }
  if (typeof value === "string") {
    const pattern = schema["pattern"];
    if (typeof pattern === "string" && !new RegExp(pattern, "u").test(value)) {
      errors.push(`${at}: pattern ${pattern}`);
    }
    if (typeof schema["minLength"] === "number" && value.length < schema["minLength"]) {
      errors.push(`${at}: too short`);
    }
    if (typeof schema["maxLength"] === "number" && value.length > schema["maxLength"]) {
      errors.push(`${at}: too long`);
    }
  }
  if (typeof value === "number") {
    if (typeof schema["minimum"] === "number" && value < schema["minimum"])
      errors.push(`${at}: < min`);
    if (typeof schema["maximum"] === "number" && value > schema["maximum"])
      errors.push(`${at}: > max`);
  }
  if (Array.isArray(value)) {
    if (typeof schema["maxItems"] === "number" && value.length > schema["maxItems"]) {
      errors.push(`${at}: too many items`);
    }
    if (
      schema["uniqueItems"] === true &&
      new Set(value.map((v) => JSON.stringify(v))).size !== value.length
    ) {
      errors.push(`${at}: duplicate items`);
    }
    const items = schema["items"] as Schema | undefined;
    if (items !== undefined) {
      value.forEach((v, i) => errors.push(...check(v, items, scope, `${at}[${String(i)}]`)));
    }
  }
  if (typeof value === "object" && value !== null && !Array.isArray(value)) {
    const obj = value as Body;
    const props = (schema["properties"] ?? {}) as Record<string, Schema>;
    for (const key of (schema["required"] ?? []) as string[]) {
      if (!(key in obj)) errors.push(`${at}: missing ${key}`);
    }
    for (const [key, v] of Object.entries(obj)) {
      const prop = props[key];
      if (prop === undefined) {
        if (schema["additionalProperties"] === false) errors.push(`${at}: unknown ${key}`);
      } else {
        errors.push(...check(v, prop, scope, `${at}.${key}`));
      }
    }
  }
  return errors;
}

function validate(value: unknown, name: string): string[] {
  const file = resolve(SCHEMAS, "recommendations/v1", name);
  return check(value, load(file), { file, root: load(file) }, "$");
}

beforeEach(resetAgentMatch);

describe("agent-match mock", () => {
  it("passes on other paths, the recommendation list and an empty context", async () => {
    expect((await call("GET", `/api/v1/recommendations/domains/${DOMAIN}`)).handled).toBe(false);
    expect((await call("GET", `/api/v1/recommendations/domains/${DOMAIN}/items/x`)).handled).toBe(
      false,
    );
    expect((await call("GET", BASE)).handled).toBe(false);
    expect(handle({} as unknown as FeatureMockContext)).toBe(false);
  });

  it("answers a schema-valid, best-first result with the three candidate kinds", async () => {
    const reply = await match(MATCH_TASK_TEXT);
    expect(reply.status).toBe(200);
    expect(validate(reply.body["match"], "agent-match-response.schema.json")).toEqual([]);
    const m = reply.body["match"] as Body;
    expect(m["domain_id"]).toBe(DOMAIN);
    const ids = (m["candidates"] as Body[]).map((c) => c["entity_id"]);
    expect(ids).toEqual([MATCH_TELEMETRY_ENTITY, MATCH_GRAPH_ENTITY, MATCH_COLD_START_ENTITY]);
    const scores = (m["candidates"] as Body[]).map((c) => c["score"] as number);
    expect(scores).toEqual([...scores].sort((a, b) => b - a));
    expect((m["candidates"] as Body[]).map((c) => c["rank"])).toEqual([1, 2, 3]);
    for (const c of m["candidates"] as Body[]) {
      expect(String(c["entity_id"]).startsWith("commercial:e2e:")).toBe(true);
    }
    expect(m["truncated"]).toBe(false);
    expect(m["partial_reason"]).toBeNull();
    expect(reply.body["confidence_note"]).toContain("not a probability");
    expect(reply.body["assessments"]).toEqual([
      { entity_id: MATCH_TELEMETRY_ENTITY, confidence: 0.86, cold_start: false },
      { entity_id: MATCH_GRAPH_ENTITY, confidence: 0.58, cold_start: false },
      { entity_id: MATCH_COLD_START_ENTITY, confidence: 0.21, cold_start: true },
    ]);
  });

  it("explains each candidate: telemetry observed, graph related, cold start unknown not zero", async () => {
    const m = (await match(MATCH_TASK_TEXT)).body["match"] as Body;
    const [rich, graph, cold] = m["candidates"] as Body[];
    const value = (c: Body | undefined, name: string): unknown =>
      ((c?.["signals"] as Body[]).find((s) => s["signal"] === name) as Body)["value"];
    expect((rich?.["signals"] as Body[]).every((s) => typeof s["value"] === "number")).toBe(true);
    expect(value(graph, "graph_proximity")).toBeGreaterThan(0.9);
    expect((graph?.["relations"] as Body[]).map((r) => r["entity_id"])).toEqual([
      ...MATCH_GRAPH_RELATED,
    ]);
    for (const name of MATCH_COLD_START_SIGNALS) expect(value(cold, name)).toBeNull();
    expect(m["cold_start"]).toBe(true);
    expect(m["signals_unavailable"]).toEqual([...MATCH_COLD_START_SIGNALS]);
  });

  it("answers the partial and empty variants from fixed task texts", async () => {
    const partial = await match(MATCH_PARTIAL_TASK_TEXT);
    expect(validate(partial.body["match"], "agent-match-response.schema.json")).toEqual([]);
    expect(partial.body["match"]["truncated"]).toBe(true);
    expect(partial.body["match"]["partial_reason"]).toBe("limit");
    expect(partial.body["match"]["candidates"]).toHaveLength(2);
    const empty = await match(MATCH_EMPTY_TASK_TEXT);
    expect(validate(empty.body["match"], "agent-match-response.schema.json")).toEqual([]);
    expect(empty.body["match"]["candidates"]).toEqual([]);
    expect(empty.body["assessments"]).toEqual([]);
  });

  it("rejects an invalid request body with 422", async () => {
    for (const body of [
      {},
      request("ab"),
      request("ok task", { domain_id: DOMAIN }),
      request("bad\u0001text"),
      request("ok task", { limit: 0 }),
      request("ok task", { candidate_types: [] }),
    ]) {
      expect((await call("POST", BASE, { body })).status).toBe(422);
    }
  });

  it("stores feedback per match and entity, a later decision replaces the earlier", async () => {
    const m = (await match(MATCH_TASK_TEXT)).body["match"] as Body;
    const id = m["match_id"] as string;
    const first = await feedback(id, MATCH_TELEMETRY_ENTITY, "accepted");
    expect(first.status).toBe(202);
    expect(first.body).toMatchObject({
      match_id: id,
      entity_id: MATCH_TELEMETRY_ENTITY,
      decision: "accepted",
    });
    expect(typeof first.body["decided_at"]).toBe("string");
    expect((await metrics()).body).toMatchObject({
      matches: 1,
      accepts: 1,
      rejects: 0,
      acceptance_rate: 1,
    });
    await feedback(id, MATCH_TELEMETRY_ENTITY, "rejected");
    expect((await metrics()).body).toMatchObject({ accepts: 0, rejects: 1, acceptance_rate: 0 });
    await feedback(id, MATCH_GRAPH_ENTITY, "accepted");
    expect((await metrics()).body).toMatchObject({
      accepts: 1,
      rejects: 1,
      matches_with_feedback: 1,
      acceptance_rate: 0.5,
    });
  });

  it("answers metrics that validate, with a null acceptance rate when there is no feedback", async () => {
    await match(MATCH_TASK_TEXT);
    await match(MATCH_TASK_TEXT);
    const reply = await metrics();
    expect(reply.status).toBe(200);
    expect(reply.body).toMatchObject({ domain_id: DOMAIN, matches: 2, accepts: 0, rejects: 0 });
    expect(reply.body["acceptance_rate"]).toBeNull();
    expect((await metrics({ role: "steward" })).body["matches"]).toBe(0);
  });

  it("refuses feedback for an unknown match or an entity that is not in the match", async () => {
    const id = ((await match(MATCH_PARTIAL_TASK_TEXT)).body["match"] as Body)["match_id"] as string;
    const unknown = await feedback("no-such-match", MATCH_TELEMETRY_ENTITY, "accepted");
    expect(unknown.status).toBe(403);
    expect(unknown.body["reason"]).toBe(MATCH_REASON_UNKNOWN_MATCH);
    // The partial variant has no cold-start candidate.
    const stranger = await feedback(id, MATCH_COLD_START_ENTITY, "accepted");
    expect(stranger.status).toBe(403);
    expect(stranger.body["reason"]).toBe(MATCH_REASON_UNKNOWN_CANDIDATE);
    // Another principal cannot decide on this match.
    expect(
      (await feedback(id, MATCH_TELEMETRY_ENTITY, "accepted", { role: "steward" })).status,
    ).toBe(403);
    expect((await metrics()).body["accepts"]).toBe(0);
    const bad = await call("POST", `${BASE}/feedback`, {
      body: {
        schema_version: "1.0.0",
        match_id: id,
        entity_id: MATCH_TELEMETRY_ENTITY,
        decision: "maybe",
      },
    });
    expect(bad.status).toBe(422);
  });

  it("answers 401 without a token and 403 for the viewer persona and an unreadable domain", async () => {
    expect(
      (await call("POST", BASE, { authorized: false, body: request(MATCH_TASK_TEXT) })).status,
    ).toBe(401);
    for (const role of ["viewer", "nodomain"]) {
      for (const reply of [
        await match(MATCH_TASK_TEXT, { role }),
        await feedback("m", MATCH_TELEMETRY_ENTITY, "accepted", { role }),
        await metrics({ role }),
      ]) {
        expect(reply.status).toBe(403);
        expect(reply.body["reason"]).toBe(MATCH_REASON_VIEWER);
      }
    }
    const other = `/api/v1/recommendations/domains/${encodeURIComponent(OTHER_DOMAIN)}/match`;
    const reply = await call("POST", other, { body: request(MATCH_TASK_TEXT) });
    expect(reply.status).toBe(403);
    expect(reply.body["reason"]).toBe(MATCH_REASON_DOMAIN);
  });

  it("answers 404 for the catalog completeness path", async () => {
    const reply = await call("GET", "/api/v1/catalog/completeness");
    expect(reply.handled).toBe(true);
    expect(reply.status).toBe(404);
    expect(reply.body["code"]).toBe("not_found");
  });
});
