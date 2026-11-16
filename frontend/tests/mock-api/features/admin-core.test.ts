import { beforeEach, describe, expect, it } from "vitest";
import {
  ADMIN_AUDIT_COUNT,
  ADMIN_DOMAIN_CONTROL,
  ADMIN_DOMAIN_FINANCE,
  ADMIN_DOMAIN_RESERVED,
  ADMIN_DOMAIN_STALE,
  ADMIN_PRINCIPAL_FORBIDDEN,
  ADMIN_PRINCIPAL_ID,
  ADMIN_PRINCIPAL_REVOKED,
  ADMIN_PRINCIPAL_STALE,
  ADMIN_RESERVED_TEXT,
  ADMIN_SETTING_KEYS,
  handle,
  resetAdminCore,
} from "./admin-core.ts";
import type { FeatureMockContext } from "./context.ts";

// A loosely typed JSON body: the assertions below index into it freely.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Body = Record<string, any>;

interface Reply {
  readonly handled: boolean;
  readonly status: number;
  readonly headers: Record<string, string>;
  readonly body: Body;
  readonly text: string;
}

function parseBody(text: string): Body {
  try {
    return JSON.parse(text) as Body;
  } catch {
    return {}; // an export is not JSON; its text is on the reply
  }
}

const SINCE = "2026-10-01T00:00:00Z";
const UNTIL = "2026-10-31T00:00:00Z";
const RANGE = `since=${SINCE}&until=${UNTIL}`;

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
  return { handled, status, headers, body: parseBody(text), text };
}

const IDENTITY = "/api/v1/admin/identity/principals";
const principal = (id: string): string => `${IDENTITY}/${encodeURIComponent(id)}`;

beforeEach(resetAdminCore);

describe("admin-core mock", () => {
  it("passes on unknown paths and on a context without a url", async () => {
    expect((await call("GET", "/api/v1/audit/domains")).handled).toBe(false);
    expect((await call("GET", "/api/v1/admin/platform/budgets")).handled).toBe(false);
    expect(handle({} as unknown as FeatureMockContext)).toBe(false);
  });

  it("answers 401 without a token and 403 for a non-admin persona", async () => {
    expect((await call("GET", IDENTITY, { authorized: false })).status).toBe(401);
    expect((await call("GET", IDENTITY, { role: "viewer" })).status).toBe(403);
    expect((await call("GET", "/api/v1/admin/system/status", { role: "auditor" })).status).toBe(
      403,
    );
  });

  it("lists principals with a cursor and returns the ETag on a read", async () => {
    const first = await call("GET", `${IDENTITY}?limit=2`);
    expect(first.body["items"]).toHaveLength(2);
    expect(first.body["next_cursor"]).toBe(ADMIN_PRINCIPAL_REVOKED);
    const second = await call(
      "GET",
      `${IDENTITY}?limit=2&cursor=${encodeURIComponent(first.body["next_cursor"])}`,
    );
    expect(second.body["items"]).toHaveLength(2);
    expect(second.body["next_cursor"]).toBeNull();
    const detail = await call("GET", principal(ADMIN_PRINCIPAL_ID));
    expect(detail.headers["etag"]).toBe('"principal-1"');
  });

  it("applies a role change, advances the ETag and rejects stale, forbidden and bad input", async () => {
    const path = `${principal(ADMIN_PRINCIPAL_ID)}/role-assignments/r-new`;
    const body = {
      op: "assign",
      role: "viewer",
      domain_ids: [ADMIN_DOMAIN_FINANCE],
      reason: "access_review",
    };
    const ok = await call("PUT", path, { body, ifMatch: '"principal-1"' });
    expect(ok.status).toBe(200);
    expect(ok.headers["etag"]).toBe('"principal-2"');
    expect(
      ok.body["assignments"].some((a: { assignment_id: string }) => a.assignment_id === "r-new"),
    ).toBe(true);
    expect((await call("PUT", path, { body, ifMatch: '"principal-1"' })).status).toBe(409);
    expect(
      (
        await call("PUT", path, {
          body: { ...body, reason: "Not A Code" },
          ifMatch: '"principal-2"',
        })
      ).status,
    ).toBe(422);
    const stale = await call("PUT", `${principal(ADMIN_PRINCIPAL_STALE)}/role-assignments/x`, {
      body,
    });
    expect(stale.status).toBe(409);
    expect(stale.body["code"]).toBe("stale_version");
    expect((await call("GET", principal(ADMIN_PRINCIPAL_FORBIDDEN))).status).toBe(403);
    const removed = await call("DELETE", `${path}?reason=access_review`, {
      ifMatch: '"principal-2"',
    });
    expect(
      removed.body["assignments"].some(
        (a: { assignment_id: string }) => a.assignment_id === "r-new",
      ),
    ).toBe(false);
  });

  it("refuses a past grant expiry and stores a future one", async () => {
    const path = `${principal(ADMIN_PRINCIPAL_ID)}/grants/g1`;
    const grant = {
      resource_id: "commercial:e2e:catalog:report:x",
      permissions: ["read"],
      reason: "audit_support",
    };
    expect(
      (await call("PUT", path, { body: { ...grant, expires_at: "2020-01-01T00:00:00Z" } })).status,
    ).toBe(422);
    expect(
      (await call("PUT", path, { body: { ...grant, expires_at: "2099-01-01T00:00:00Z" } })).status,
    ).toBe(200);
  });

  it("revokes and lifts", async () => {
    const path = `${principal(ADMIN_PRINCIPAL_ID)}/revocation`;
    expect(
      (await call("POST", path, { body: { mode: "until_lifted", reason: "offboarding" } })).body[
        "revoked"
      ],
    ).toBe(true);
    expect((await call("GET", path)).body["mode"]).toBe("until_lifted");
    expect((await call("POST", path, { body: { mode: "bogus", reason: "x" } })).status).toBe(422);
    expect((await call("DELETE", `${path}?reason=mistake`)).body["revoked"]).toBe(false);
  });

  it("lists, creates and retires domains with the API's own error text", async () => {
    const base = "/api/v1/admin/platform/domains";
    expect((await call("GET", base)).body["items"]).toHaveLength(3);
    expect((await call("GET", `${base}?include_retired=true`)).body["items"]).toHaveLength(4);
    const created = await call("POST", base, {
      body: {
        domain_id: "commercial:e2e:catalog:domain:ops",
        display_name: "Ops",
        classification: "internal",
        residency_region: "eastus",
        status: "active",
        is_control_domain: false,
      },
    });
    expect(created.status).toBe(201);
    const reserved = await call("POST", base, { body: { domain_id: ADMIN_DOMAIN_RESERVED } });
    expect(reserved.status).toBe(422);
    expect(reserved.body["detail"]).toBe(ADMIN_RESERVED_TEXT);
    const retire = (id: string): Promise<Reply> =>
      call("POST", `${base}/${encodeURIComponent(id)}/retire`, { ifMatch: '"domain-1"' });
    expect((await retire(ADMIN_DOMAIN_FINANCE)).body["status"]).toBe("retired");
    expect((await retire(ADMIN_DOMAIN_STALE)).status).toBe(409);
    expect((await retire(ADMIN_DOMAIN_CONTROL)).status).toBe(422);
  });

  it("serves system status, checklist and the six settings keys", async () => {
    expect(
      (await call("GET", "/api/v1/admin/system/status")).body["components"].length,
    ).toBeGreaterThan(0);
    expect(
      (await call("GET", "/api/v1/admin/system/checklist")).body["items"].length,
    ).toBeGreaterThan(0);
    const settings = await call("GET", "/api/v1/admin/system/settings");
    expect(settings.body["items"].map((i: { key: string }) => i.key)).toEqual([
      ...ADMIN_SETTING_KEYS,
    ]);
  });

  it("pages audit search by cursor, filters, and requires a capped range", async () => {
    const search = "/api/v1/audit/search";
    expect((await call("GET", search)).status).toBe(422);
    expect(
      (await call("GET", `${search}?since=2026-01-01T00:00:00Z&until=2026-12-01T00:00:00Z`)).status,
    ).toBe(422);
    const first = await call("GET", `${search}?${RANGE}&page_size=25`);
    expect(first.body["items"]).toHaveLength(25);
    expect(first.body["next_cursor"]).toBe("25");
    const second = await call("GET", `${search}?${RANGE}&page_size=25&cursor=25`);
    expect(second.body["items"]).toHaveLength(ADMIN_AUDIT_COUNT - 25);
    expect(second.body["next_cursor"]).toBeNull();
    const denied = await call("GET", `${search}?${RANGE}&kind=denied`);
    expect(
      denied.body["items"].every((i: { record: { kind: string } }) => i.record.kind === "denied"),
    ).toBe(true);
    expect((await call("GET", "/api/v1/audit/denials")).body["items"].length).toBeGreaterThan(0);
    expect(
      (await call("GET", "/api/v1/audit/siem/status", { role: "auditor" })).body["state"],
    ).toBe("ok");
  });

  it("exports ndjson and csv for an admin and refuses an auditor", async () => {
    const csv = await call("GET", `/api/v1/audit/export?${RANGE}&format=csv`);
    expect(csv.headers["x-neurosphere-export-rows"]).toBe(String(ADMIN_AUDIT_COUNT));
    expect(csv.text.startsWith("domain_id,")).toBe(true);
    const nd = await call("GET", `/api/v1/audit/export?${RANGE}&format=ndjson`);
    expect(nd.text.trim().split("\n")).toHaveLength(ADMIN_AUDIT_COUNT);
    expect((await call("GET", `/api/v1/audit/export?${RANGE}`, { role: "auditor" })).status).toBe(
      403,
    );
  });
});
