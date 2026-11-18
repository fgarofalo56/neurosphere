import type { FeatureMockContext, FeatureMockHandler } from "./context.ts";

/**
 * PRP-138 read views: `GET /api/v1/me/access` (any authenticated caller, own roles only) and
 * `GET /api/v1/admin/identity/role-mapping` (deployment-scoped `policy.manage`). Persona gate (a
 * stand-in for the API's checks): the admin persona sees an active mapping and an admin role that
 * came from an Entra app role; every other persona gets 403 `customer_scope_required` on the
 * mapping view and its own policy-store role from `/me/access`. Every id is SYNTHETIC.
 */

export const ME_ACCESS_PATH = "/api/v1/me/access";
export const ROLE_MAPPING_PATH = "/api/v1/admin/identity/role-mapping";

export const ROLE_MAPPING_TENANT = "11111111-1111-1111-1111-111111111111";
export const ROLE_MAPPING_AUDIENCE = "22222222-2222-2222-2222-222222222222";
export const ROLE_MAPPING_DENIED_DETAIL =
  "this operation needs `policy.manage` on the whole deployment (the customer control domain)";

/** Persona (fake token role) to the NeuroSphere role the stored policy gives it. */
const PERSONA_ROLES: Record<string, string> = {
  viewer: "viewer",
  analyst: "analyst",
  steward: "domain_steward",
  auditor: "security_auditor",
};

/** Expiry of the mapped role: the token's expiry, an hour after the fixed mock clock. */
const TOKEN_EXPIRY = "2026-11-18T15:00:00Z";

function json(ctx: FeatureMockContext, status: number, body: unknown, type: string): void {
  ctx.res.writeHead(status, { "content-type": type, ...ctx.cors });
  ctx.res.end(JSON.stringify(body));
}

function forbidden(ctx: FeatureMockContext): void {
  json(
    ctx,
    403,
    {
      schema_version: "1.0.0",
      type: "https://neurosphere.invalid/problems/forbidden",
      title: "forbidden",
      status: 403,
      detail: ROLE_MAPPING_DENIED_DETAIL,
      instance: ctx.url.pathname,
      code: "forbidden",
      reason: "customer_scope_required",
      retryable: false,
      correlation_id: ctx.correlationId,
    },
    "application/problem+json",
  );
}

function mapping(): Record<string, unknown> {
  return {
    active: true,
    tenant_id: ROLE_MAPPING_TENANT,
    audience: ROLE_MAPPING_AUDIENCE,
    cloud: "commercial",
    entries: [
      {
        id: "ns-admins",
        claim: "roles",
        value: "admin",
        role: "admin",
        domain_mode: "all",
        domain_ids: [],
        customer_control: true,
      },
      {
        id: "finance-analysts",
        claim: "groups",
        value: "33333333-3333-3333-3333-333333333333",
        role: "analyst",
        domain_mode: "explicit",
        domain_ids: ["commercial:e2e:catalog:domain:finance"],
        customer_control: false,
      },
    ],
  };
}

function access(role: string | undefined): Record<string, unknown> {
  if (role === "admin") {
    return {
      mapping_configured: true,
      groups_overage: false,
      roles: [
        {
          role: "admin",
          source: "entra_app_role",
          mapping_entry_id: "ns-admins",
          domain_count: 4,
          customer_control: true,
          expires_at: TOKEN_EXPIRY,
        },
      ],
    };
  }
  const stored = role === undefined ? undefined : PERSONA_ROLES[role];
  return {
    mapping_configured: true,
    groups_overage: false,
    roles:
      stored === undefined
        ? []
        : [
            {
              role: stored,
              source: "policy_store",
              mapping_entry_id: null,
              domain_count: 1,
              customer_control: false,
              expires_at: null,
            },
          ],
  };
}

export const handle: FeatureMockHandler = (ctx) => {
  // The registry test passes an empty context; a handler must pass on anything it cannot read.
  const requestUrl = (ctx as { url?: URL }).url;
  if (requestUrl === undefined) return false;
  const path = requestUrl.pathname;
  if (path !== ME_ACCESS_PATH && path !== ROLE_MAPPING_PATH) return false;
  if (!ctx.authorized) {
    json(ctx, 401, { error: "missing or unrecognised token" }, "application/json");
    return true;
  }
  if (ctx.req.method !== "GET") {
    json(ctx, 405, { error: "method not allowed" }, "application/json");
    return true;
  }
  if (path === ME_ACCESS_PATH) {
    json(ctx, 200, access(ctx.role), "application/json");
    return true;
  }
  if (ctx.role !== "admin") {
    forbidden(ctx);
    return true;
  }
  json(ctx, 200, mapping(), "application/json");
  return true;
};
