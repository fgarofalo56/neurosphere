import {
  AUDIT_DOMAIN_EMPTY,
  AUDIT_DOMAIN_FINANCE,
  AUDIT_DOMAIN_HR,
  AUDIT_DOMAIN_UNCONFIGURED,
} from "./audit.ts";
import type { FeatureMockContext, FeatureMockHandler } from "./context.ts";

/**
 * PRP-56 compliance mock: GET /api/v1/compliance/frameworks, /frameworks/{id} and
 * /domains/{d}/bundle. Shapes follow services/api/neurosphere_api/compliance and the
 * compliance/v1 contracts. Every number and id is SYNTHETIC. Like the real API, only an Auditor
 * token holds evidence.read (Admin does not). The finance domain answers a mix of
 * evidence_present, evidence_partial, no_evidence and customer_responsibility controls; the
 * archive domain answers a bundle with no controls (empty); the offline domain answers 503.
 */

export const COMPLIANCE_FRAMEWORKS_PATH = "/api/v1/compliance/frameworks";
const BUNDLE_PATH = /^\/api\/v1\/compliance\/domains\/([^/]+)\/bundle$/;
const FRAMEWORK_PATH = /^\/api\/v1\/compliance\/frameworks\/([^/]+)$/;
const KNOWN_DOMAINS = [AUDIT_DOMAIN_FINANCE, AUDIT_DOMAIN_HR, AUDIT_DOMAIN_EMPTY];

const WINDOW_START = "2026-10-17T00:00:00Z";
const WINDOW_END = "2026-11-16T00:00:00Z";
const RETRIEVED = "2026-11-16";

type Summary = "evidence_present" | "evidence_partial" | "no_evidence" | "customer_responsibility";

interface ControlSeed {
  readonly id: string;
  readonly title: string;
  readonly support: string;
  readonly sources: readonly string[];
  readonly summary: Summary;
}

const FRAMEWORKS: Record<
  string,
  { title: string; version: string; url: string; controls: readonly ControlSeed[] }
> = {
  nist_ai_rmf: {
    title: "NIST AI Risk Management Framework (Core categories)",
    version: "1.0",
    url: "https://airc.nist.gov/airmf-resources/airmf/5-sec-core/",
    controls: [
      {
        id: "nist-ai-rmf.govern-2",
        title: "Accountable, trained teams and individuals for AI risk work",
        support: "implemented_tested",
        sources: ["catalog_ownership"],
        summary: "evidence_present",
      },
      {
        id: "nist-ai-rmf.map-3",
        title: "Weighing capabilities, goals and benefits against costs and benchmarks",
        support: "implemented_tested",
        sources: ["cost_attribution", "evaluation_results"],
        summary: "evidence_partial",
      },
      {
        id: "nist-ai-rmf.manage-1",
        title: "Prioritizing and responding to assessed AI risks",
        support: "implemented_tested",
        sources: ["hitl_decisions"],
        summary: "no_evidence",
      },
      {
        id: "nist-ai-rmf.govern-3",
        title: "Diversity, equity, inclusion and accessibility in AI risk decisions",
        support: "customer",
        sources: [],
        summary: "customer_responsibility",
      },
    ],
  },
  hipaa_technical_safeguards: {
    title: "HIPAA Security Rule technical safeguards (45 CFR 164.312)",
    version: "ecfr-2025-01-01",
    url: "https://www.ecfr.gov/current/title-45/part-164/section-164.312",
    controls: [
      {
        id: "hipaa.164.312.b",
        title: "Audit controls standard",
        support: "implemented_tested",
        sources: ["audit_chain"],
        summary: "evidence_present",
      },
      {
        id: "hipaa.164.312.e.1",
        title: "Transmission security standard",
        support: "customer",
        sources: [],
        summary: "customer_responsibility",
      },
    ],
  },
};

const OBSERVATIONS = [
  {
    source_id: "catalog_ownership",
    status: "observed",
    reason_code: null,
    latest_at: "2026-11-10T09:30:00Z",
    truncated: false,
    measures: [
      { name: "records", value: 4 },
      { name: "owners_overdue", value: 1 },
    ],
  },
  {
    source_id: "audit_chain",
    status: "observed",
    reason_code: null,
    latest_at: "2026-11-15T18:00:00Z",
    truncated: false,
    measures: [
      { name: "records", value: 120 },
      { name: "chain_intact", value: 1 },
    ],
  },
  {
    source_id: "hitl_decisions",
    status: "observed",
    reason_code: null,
    latest_at: null,
    truncated: false,
    measures: [{ name: "records", value: 0 }],
  },
  {
    source_id: "evaluation_results",
    status: "partial",
    reason_code: "capped",
    latest_at: "2026-11-12T01:42:00Z",
    truncated: true,
    measures: [{ name: "records", value: 2000 }],
  },
  {
    source_id: "cost_attribution",
    status: "not_collected",
    reason_code: "cost_center_absent",
    latest_at: null,
    truncated: false,
    measures: [{ name: "records", value: null }],
  },
] as const;

function json(
  ctx: FeatureMockContext,
  status: number,
  body: unknown,
  contentType = "application/json",
): void {
  ctx.res.writeHead(status, { "content-type": contentType, ...ctx.cors });
  ctx.res.end(JSON.stringify(body));
}

function problem(ctx: FeatureMockContext, status: number, code: string, reason: string): void {
  json(
    ctx,
    status,
    {
      schema_version: "1.0.0",
      type: `https://neurosphere.invalid/problems/${code.replaceAll("_", "-")}`,
      title: status === 503 ? "Dependency unavailable" : status === 404 ? "Not found" : "Forbidden",
      status,
      detail: reason,
      instance: ctx.url.pathname,
      code,
      reason,
      retryable: false,
      correlation_id: ctx.correlationId,
    },
    "application/problem+json",
  );
}

function bundle(domain: string, frameworkId: string): unknown {
  const fw = FRAMEWORKS[frameworkId];
  if (fw === undefined) return undefined;
  const empty = domain === AUDIT_DOMAIN_EMPTY;
  const wanted = new Set(fw.controls.flatMap((c) => c.sources));
  return {
    schema_version: "1.0.0",
    framework_id: frameworkId,
    framework_version: fw.version,
    library_version: "1.0.0",
    domain_id: domain,
    generated_at: WINDOW_END,
    window_start: WINDOW_START,
    window_end: WINDOW_END,
    controls: empty
      ? []
      : fw.controls.map((c) => ({
          control: {
            schema_version: "1.0.0",
            control_id: c.id,
            framework_id: frameworkId,
            title: c.title,
            source_url: fw.url,
            source_retrieved: RETRIEVED,
            framework_version: fw.version,
          },
          support_status: c.support,
          evidence_sources: c.sources,
          summary: c.summary,
        })),
    observations: OBSERVATIONS.filter((o) => wanted.has(o.source_id)).map((o) => ({
      schema_version: "1.0.0",
      ...o,
      window_start: WINDOW_START,
      window_end: WINDOW_END,
    })),
    digest: `sha256:${(frameworkId.length % 10).toString().repeat(64)}`,
  };
}

export const handle: FeatureMockHandler = (ctx) => {
  // The registry test passes an empty context; a handler must pass on anything it cannot read.
  const requestUrl = (ctx as { url?: URL }).url;
  if (requestUrl === undefined) return false;
  const path = requestUrl.pathname;
  const bundleMatch = BUNDLE_PATH.exec(path);
  const frameworkMatch = FRAMEWORK_PATH.exec(path);
  if (path !== COMPLIANCE_FRAMEWORKS_PATH && bundleMatch === null && frameworkMatch === null) {
    return false;
  }
  if (ctx.req.method !== "GET") {
    json(ctx, 405, { error: "method not allowed" });
    return true;
  }
  if (!ctx.authorized) {
    json(ctx, 401, { error: "missing or unrecognised token" });
    return true;
  }
  // evidence.read is held by the Security Auditor only; Admin does not hold it.
  if (ctx.role !== "auditor") {
    problem(ctx, 403, "forbidden", "permission_missing");
    return true;
  }
  if (path === COMPLIANCE_FRAMEWORKS_PATH) {
    json(ctx, 200, {
      library_version: "1.0.0",
      frameworks: Object.entries(FRAMEWORKS).map(([id, fw]) => ({
        framework_id: id,
        title: fw.title,
        framework_version: fw.version,
        source_url: fw.url,
        source_retrieved: RETRIEVED,
        control_count: fw.controls.length,
      })),
    });
    return true;
  }
  if (frameworkMatch !== null) {
    const id = decodeURIComponent(frameworkMatch[1] ?? "");
    const fw = FRAMEWORKS[id];
    if (fw === undefined) {
      problem(ctx, 404, "not_found", "framework_not_found");
      return true;
    }
    json(ctx, 200, {
      library_version: "1.0.0",
      framework_id: id,
      title: fw.title,
      framework_version: fw.version,
      source_url: fw.url,
      source_retrieved: RETRIEVED,
      controls: fw.controls.map((c) => ({
        control_id: c.id,
        title: c.title,
        source_url: fw.url,
        source_retrieved: RETRIEVED,
        support_status: c.support,
        evidence_sources: c.sources,
      })),
    });
    return true;
  }
  const domain = decodeURIComponent(bundleMatch?.[1] ?? "");
  if (domain === AUDIT_DOMAIN_UNCONFIGURED) {
    problem(ctx, 503, "dependency_transient", "compliance_library_unavailable");
    return true;
  }
  if (!KNOWN_DOMAINS.includes(domain)) {
    problem(ctx, 403, "forbidden", "domain_out_of_scope");
    return true;
  }
  const body = bundle(domain, ctx.url.searchParams.get("framework_id") ?? "");
  if (body === undefined) {
    problem(ctx, 404, "not_found", "framework_not_found");
    return true;
  }
  json(ctx, 200, body);
  return true;
};
