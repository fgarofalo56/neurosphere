import type { FeatureMockHandler } from "./context.ts";

/**
 * PRP-31 item 7 mock: `POST /api/v1/deploy/scan`, `POST /api/v1/deploy/plan` and
 * `GET /api/v1/capabilities`. Synthetic data only. Subscription ids are obviously fake GUIDs
 * assembled from parts so no scanner reads them as a credential.
 */
const guid = (tail: string): string => ["aaaaaaaa", "0000", "4000", "8000", tail].join("-");
export const DEPLOY_SUB_VISIBLE = guid("000000000001");
export const DEPLOY_SUB_HIDDEN = guid("000000000002");

export const DEPLOY_VISIBILITY_NOTE =
  "Results reflect only what the calling identity can read. A subscription reported " +
  "not_visible may still contain resources; absence of results is not absence of resources.";

export const DEPLOY_APIM_ID = `/subscriptions/${DEPLOY_SUB_VISIBLE}/resourceGroups/rg-shared/providers/Microsoft.ApiManagement/service/apim-shared`;
export const DEPLOY_VAULT_ID = `/subscriptions/${DEPLOY_SUB_VISIBLE}/resourceGroups/rg-ns/providers/Microsoft.KeyVault/vaults/kv-ns`;

// PRP-08 item 13: the apply routes. The domain path segment selects the variant, so a spec can
// reach each state with `?domain_id=`: not configured (503 apply_not_configured), denied (403) or
// a refused apply (422 plan_hash_mismatch). Any other domain behaves like an enabled deployment
// whose apply only DRAFTS an intent (state "drafted", no execution): nothing is ever "applied".
export const DEPLOY_APPLY_OFF_DOMAIN = "ns-apply-not-configured";
export const DEPLOY_APPLY_DENIED_DOMAIN = "ns-apply-denied";
export const DEPLOY_APPLY_REFUSED_DOMAIN = "ns-apply-refused";
export const DEPLOY_PLAN_ID = `plan-${"a1b2c3d4".repeat(4)}`;
export const DEPLOY_PLAN_HASH = `sha256:${"0123456789abcdef".repeat(4)}`;
export const DEPLOY_RESOURCES_DIGEST = `sha256:${"fedcba9876543210".repeat(4)}`;

const SOURCE =
  "https://learn.microsoft.com/azure/azure-government/compare-azure-government-global-azure";
const GOV_REGION = /^(usgov|usdod)/;

interface ScanBody {
  consent?: { consent_id?: string; consented_by?: string; consented_subscriptions?: string[] };
  subscription_ids?: string[];
}

interface Resource {
  category: string;
  type: string;
  id: string;
  name: string;
  location: string;
  sku: string | null;
  subscription_id: string;
  tags: Record<string, string>;
}

const SERVICES = [
  "api_management",
  "model_endpoint",
  "key_vault",
  "monitoring",
  "event_hubs",
  "storage",
  "analytics_workspace",
  "cosmos_db",
  "ai_search",
  "container_registry",
  "kubernetes",
  "app_service",
];
const CATEGORY: Record<string, string> = {
  apim: "api_management",
  key_vault: "key_vault",
  model_endpoint: "model_endpoint",
  monitoring: "monitoring",
  event_hubs: "event_hubs",
  storage: "storage",
  analytics_workspace: "analytics_workspace",
};

function scanFor(body: ScanBody) {
  const consented = new Set(body.consent?.consented_subscriptions ?? []);
  const subs = (body.subscription_ids ?? []).map((id) => {
    if (!consented.has(id))
      return {
        subscription_id: id,
        status: "not_visible",
        resources: [],
        note: "No consent recorded for this subscription.",
      };
    if (id === DEPLOY_SUB_HIDDEN) {
      return {
        subscription_id: id,
        status: "not_visible",
        resources: [],
        note: "The calling identity cannot read this subscription.",
      };
    }
    const resources: Resource[] = [
      {
        category: "apim",
        type: "Microsoft.ApiManagement/service",
        id: DEPLOY_APIM_ID,
        name: "apim-shared",
        location: "eastus",
        sku: "Standard",
        subscription_id: id,
        tags: {},
      },
      {
        category: "key_vault",
        type: "Microsoft.KeyVault/vaults",
        id: DEPLOY_VAULT_ID,
        name: "kv-ns",
        location: "eastus",
        sku: "standard",
        subscription_id: id,
        tags: { "neurosphere-created": "true" },
      },
    ];
    return { subscription_id: id, status: "visible", resources, note: null };
  });
  return {
    visibility_limited: true,
    visibility_note: DEPLOY_VISIBILITY_NOTE,
    consent_id: body.consent?.consent_id ?? "",
    scanned_at: "2026-10-15T12:00:00Z",
    subscriptions: subs,
  };
}

interface PlanBody {
  profile?: { cloud?: string; regions?: string[] };
  scan?: { subscriptions?: { resources?: Resource[] }[] } | null;
  choices?: Record<string, { decision: string; resource_id?: string; fallback?: string }>;
  consents?: { granted: boolean; resource_ids: string[]; owner_principal?: string }[];
}

function planFor(body: PlanBody) {
  const gov = body.profile?.cloud === "government";
  const found = (body.scan?.subscriptions ?? []).flatMap((s) => s.resources ?? []);
  const consents = body.consents ?? [];
  const items = SERVICES.map((service) => {
    const candidate = found.find((r) => CATEGORY[r.category] === service);
    const choice = body.choices?.[service];
    let status: string = choice?.decision ?? (candidate ? "reuse" : "create");
    let existing: string | null = null;
    let shared = false;
    let created = false;
    if (status === "reuse") {
      const wanted = choice?.resource_id ?? candidate?.id;
      const res = found.find((r) => r.id.toLowerCase() === (wanted ?? "").toLowerCase());
      if (res === undefined) status = choice?.fallback ?? "create";
      else {
        existing = res.id;
        created = res.tags["neurosphere-created"] === "true";
        shared = !created;
        const ok = consents.some(
          (c) => c.granted && c.resource_ids.some((x) => x.toLowerCase() === res.id.toLowerCase()),
        );
        if (shared && !ok) status = "needs_consent";
      }
    }
    let disabledReason: string | null = null;
    if (gov && service === "model_endpoint") {
      status = "disabled";
      disabledReason =
        "Model endpoints are not verified for this Government region. The plan does not route to Commercial.";
    }
    const create = status === "create";
    return {
      service,
      kind: "service",
      status,
      existing_resource_id: existing,
      shared,
      neurosphere_created: created,
      checks: [
        { name: "sku", outcome: "pass", reason: "SKU is listed for the region" },
        { name: "quota", outcome: "unknown", reason: "Quota was not queried" },
      ],
      notes: [],
      disabled_reason: disabledReason,
      reason_code: disabledReason === null ? null : "capability_unavailable",
      source_url: disabledReason === null ? null : SOURCE,
      owner_consent: null,
      cost_implication: create
        ? {
            basis: "estimated",
            monthly_amount: "42.00",
            currency: "USD",
            price_version: "mock-1",
            summary: null,
          }
        : status === "reuse"
          ? {
              basis: "no_incremental_cost",
              monthly_amount: null,
              currency: null,
              price_version: null,
              summary: "Reuses an existing resource",
            }
          : {
              basis: "unknown",
              monthly_amount: null,
              currency: null,
              price_version: null,
              summary: null,
            },
    };
  });
  return {
    plan: {
      plan_id: DEPLOY_PLAN_ID,
      deployment_id: "deploy-mock",
      profile: body.profile,
      items,
      capability_warnings: gov ? ["Analytics availability is unverified for this region."] : [],
      consents: [],
      created_at: "2026-10-15T12:05:00Z",
    },
    manifest: {
      schema_version: "1.0.0",
      deployment_id: "deploy-mock",
      service_plan: items
        .filter((i) => i.status !== "disabled")
        .map((i) => ({ service: i.service, status: i.status })),
    },
  };
}

interface Row {
  id: string;
  service: string;
  feature: string;
  cloud: "commercial" | "government";
  region: string;
  sku: string | null;
  availability: string;
  ga_status: string;
  authorization_scope: string;
  source_url: string;
  observed_on: string;
  notes: string | null;
}
const row = (
  r: Partial<Row> & Pick<Row, "id" | "service" | "feature" | "cloud" | "region">,
): Row => ({
  sku: null,
  availability: "available",
  ga_status: "ga",
  authorization_scope: "none_claimed",
  source_url: SOURCE,
  observed_on: "2026-09-21",
  notes: null,
  ...r,
});
const MATRIX: Row[] = [
  row({
    id: "ai_search.base.commercial.eastus.any",
    service: "ai_search",
    feature: "base",
    cloud: "commercial",
    region: "eastus",
  }),
  row({
    id: "foundry.model_gpt_4o.commercial.eastus.any",
    service: "foundry",
    feature: "model_gpt_4o",
    cloud: "commercial",
    region: "eastus",
    availability: "preview",
    ga_status: "preview",
    notes: "Preview limits apply.",
  }),
  row({
    id: "ai_search.base.government.usgovvirginia.any",
    service: "ai_search",
    feature: "base",
    cloud: "government",
    region: "usgovvirginia",
    authorization_scope: "Audit-scope text cited from the source, 2026-09-21",
  }),
  row({
    id: "foundry.model_gpt_4o.government.usgovvirginia.any",
    service: "foundry",
    feature: "model_gpt_4o",
    cloud: "government",
    region: "usgovvirginia",
    availability: "unverified",
    ga_status: "unverified",
    notes: "The source does not state availability.",
  }),
  row({
    id: "fabric.base.government.usgovvirginia.any",
    service: "fabric",
    feature: "base",
    cloud: "government",
    region: "usgovvirginia",
    availability: "unavailable",
    ga_status: "not_applicable",
  }),
];

function speaks(r: Row, region: string): boolean {
  if (r.region === region || r.region === "global") return true;
  if (r.region !== "*") return false;
  return r.cloud === "government" ? GOV_REGION.test(region) : !GOV_REGION.test(region);
}

interface MockPlanItem {
  service: string;
  status: string;
  existing_resource_id: string | null;
}
interface ApproveBody {
  plan?: { plan_id?: string; deployment_id?: string; items?: MockPlanItem[] };
  target?: { region?: string; capacity_sku?: string };
}

function plannedResources(body: ApproveBody) {
  const region = body.target?.region ?? "eastus";
  return (body.plan?.items ?? [])
    .filter((i) => i.status === "create" || i.status === "reuse")
    .map((i) => ({
      service: i.service,
      kind: "arm_resource",
      disposition: i.status,
      name: `ns-${i.service.replace(/_/g, "-")}`,
      region,
      sku: i.status === "create" ? (body.target?.capacity_sku ?? "F2") : null,
      resource_id: i.status === "reuse" ? i.existing_resource_id : null,
    }));
}

/** A freshly drafted intent: never executed, so the UI must not call it applied. */
function draftedAction(kind: string, targetId: string, version: string, dryRun: boolean) {
  return {
    intent: {
      schema_version: "1.0.0",
      intent_id: "11111111-2222-4333-8444-555555555555",
      action_kind: kind,
      actor: { principal_pseudonym: "p-mock", principal_kind: "user", on_behalf_of: null },
      target: { canonical_id: targetId, entity_type: "deployment" },
      target_version: version,
      proposed_diff: {
        format: "json_patch",
        operations: [
          {
            op: "add",
            path: "/resources/0",
            value: { service: "key_vault", disposition: "create" },
          },
        ],
      },
      prerequisite_results: [],
      evidence: [],
      confirmation_hash: null,
      confirmation_expires_at: null,
      idempotency_key: "mock-key-mock-key-0001",
      channel: "button",
      state: "drafted",
      status_reason: null,
      dry_run: dryRun,
      correlation_id: "corr-mock",
      created_at: "2026-10-15T12:10:00Z",
      state_changed_at: "2026-10-15T12:10:00Z",
    },
    advisory: false,
    requires_approval: true,
    self_approval_forbidden: true,
    review_item_id: null,
    execution: null,
  };
}

const APPLY_ROUTE =
  /^\/api\/v1\/deploy\/apply\/domains\/([^/]+)\/(plans\/approve|plans\/apply|uninstall\/preview)$/;

function handleApply(ctx: Parameters<FeatureMockHandler>[0], domain: string, op: string): void {
  const send = (status: number, body: unknown): void => {
    ctx.res.writeHead(status, { "content-type": "application/json", ...ctx.cors });
    ctx.res.end(JSON.stringify(body));
  };
  if (domain === DEPLOY_APPLY_OFF_DOMAIN) {
    ctx.problem(503, "dependency_transient", "apply_not_configured", "Apply is not configured.");
    return;
  }
  if (domain === DEPLOY_APPLY_DENIED_DOMAIN) {
    ctx.problem(403, "forbidden", "insufficient_permission", "config.manage is required.");
    return;
  }
  void ctx.readBody().then((raw) => {
    if (op === "plans/approve") {
      const body = JSON.parse(raw) as ApproveBody;
      if ((body.plan?.items ?? []).some((i) => i.status === "needs_consent")) {
        ctx.problem(
          422,
          "invalid_schema",
          "plan_has_unresolved_items",
          "The plan has items waiting for owner consent.",
        );
        return;
      }
      send(201, {
        plan_id: body.plan?.plan_id ?? DEPLOY_PLAN_ID,
        plan_hash: DEPLOY_PLAN_HASH,
        resources_digest: DEPLOY_RESOURCES_DIGEST,
        deployment_id: body.plan?.deployment_id ?? "deploy-mock",
        cloud: "commercial",
        resources: plannedResources(body),
        approved_at: "2026-10-15T12:08:00Z",
        expires_at: "2026-10-15T13:08:00Z",
      });
      return;
    }
    if (op === "plans/apply") {
      const body = JSON.parse(raw) as { plan_id?: string; plan_hash?: string };
      if (domain === DEPLOY_APPLY_REFUSED_DOMAIN || body.plan_hash !== DEPLOY_PLAN_HASH) {
        ctx.problem(
          422,
          "invalid_schema",
          "plan_hash_mismatch",
          "The plan changed since it was approved.",
        );
        return;
      }
      send(201, {
        plan_id: body.plan_id ?? DEPLOY_PLAN_ID,
        plan_hash: DEPLOY_PLAN_HASH,
        resources: [],
        action: draftedAction(
          "deploy_plan_apply",
          "commercial:mock:deploy:plan",
          DEPLOY_PLAN_HASH,
          false,
        ),
      });
      return;
    }
    const body = JSON.parse(raw) as { deployment_id?: string };
    if (body.deployment_id !== "deploy-mock") {
      ctx.problem(
        422,
        "invalid_schema",
        "deployment_not_found",
        "No register rows for this deployment.",
      );
      return;
    }
    const digest = `sha256:${"abcdef0123456789".repeat(4)}`;
    send(201, {
      deployment_id: body.deployment_id,
      dry_run: true,
      register_digest: digest,
      removable: [
        {
          resource_id:
            "/subscriptions/x/resourceGroups/rg-ns/providers/Microsoft.KeyVault/vaults/kv-ns",
          service: "key_vault",
          ownership: "created",
          reason: "Created by NeuroSphere for this deployment",
        },
      ],
      untouched: [
        {
          resource_id: DEPLOY_APIM_ID,
          service: "api_management",
          ownership: "reused",
          reason: "Reused existing resource: never removed",
        },
        {
          resource_id:
            "/subscriptions/x/resourceGroups/rg-shared/providers/Microsoft.Storage/storageAccounts/stshared",
          service: "storage",
          ownership: "shared",
          reason: "Shared with other workloads: never removed",
        },
      ],
      action: draftedAction("deploy_uninstall", "commercial:mock:deploy:deploy-mock", digest, true),
    });
  });
}

export const handle: FeatureMockHandler = (ctx) => {
  // Registry tests pass an empty context to prove placeholders stay inert; stay inert too.
  const url = (ctx as { url?: URL }).url;
  if (url === undefined) return false;
  const method = ctx.req.method;
  const send = (body: unknown): void => {
    ctx.res.writeHead(200, { "content-type": "application/json", ...ctx.cors });
    ctx.res.end(JSON.stringify(body));
  };

  if (url.pathname === "/api/v1/capabilities" && method === "GET") {
    const cloud = url.searchParams.get("cloud");
    const region = url.searchParams.get("region");
    const items = MATRIX.filter(
      (r) => (cloud === null || r.cloud === cloud) && (region === null || speaks(r, region)),
    );
    send({ matrix_version: "sha256:mock0000mock0000", observed_at: "2026-09-21", items });
    return true;
  }

  if (url.pathname === "/api/v1/deploy/scan" && method === "POST") {
    void ctx.readBody().then((raw) => {
      const body = JSON.parse(raw) as ScanBody;
      if (body.consent === undefined || body.consent === null) {
        ctx.problem(403, "forbidden", "consent_required", "A consent record is required");
        return;
      }
      send(scanFor(body));
    });
    return true;
  }

  if (url.pathname === "/api/v1/deploy/plan" && method === "POST") {
    void ctx.readBody().then((raw) => send(planFor(JSON.parse(raw) as PlanBody)));
    return true;
  }

  const apply = APPLY_ROUTE.exec(url.pathname);
  if (apply !== null && method === "POST") {
    handleApply(ctx, decodeURIComponent(apply[1] ?? ""), apply[2] ?? "");
    return true;
  }
  return false;
};
