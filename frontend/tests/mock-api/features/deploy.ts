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
      plan_id: "plan-mock-0001",
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
  return false;
};
