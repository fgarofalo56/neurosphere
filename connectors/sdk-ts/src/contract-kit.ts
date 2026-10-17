// Contract check: checkConnectorContract returns violations and never throws.
//
// Duck-typed on purpose: a connector that lacks health or coverage entirely is reported as a
// violation, not a crash. Makes no network calls.

import { manifestIssues } from "./manifest.js";

/** One contract failure. `code` is stable; `message` never contains secret values. */
export interface Violation {
  readonly code: string;
  readonly message: string;
}

const STATES = new Set(["healthy", "degraded", "rate_limited", "failing", "unknown"]);

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

async function call(
  connector: Record<string, unknown>,
  method: string,
): Promise<{ result: unknown; violation: Violation | null }> {
  const fn = connector[method];
  if (typeof fn !== "function") {
    return {
      result: undefined,
      violation: { code: `${method}_missing`, message: `connector has no async ${method}()` },
    };
  }
  try {
    return { result: await (fn as () => unknown).call(connector), violation: null };
  } catch (error) {
    const kind = error instanceof Error ? error.name : "error";
    return {
      result: undefined,
      violation: { code: `${method}_raised`, message: `${method}() raised ${kind}` },
    };
  }
}

/** Check manifest, health, rate-limit, coverage and freshness reporting. */
export async function checkConnectorContract(connector: unknown): Promise<Violation[]> {
  const out: Violation[] = [];
  if (!isObject(connector)) {
    return [{ code: "manifest_missing", message: "connector exposes no manifest" }];
  }

  const manifest = connector["manifest"];
  if (manifest === undefined || manifest === null) {
    out.push({ code: "manifest_missing", message: "connector exposes no manifest" });
  } else if (!isObject(manifest)) {
    out.push({ code: "manifest_type", message: "manifest must be a ConnectorManifest object" });
  } else {
    for (const issue of manifestIssues(manifest)) {
      out.push({ code: "manifest_invalid", message: `${issue.pointer || "/"}: ${issue.detail}` });
    }
    try {
      JSON.stringify(manifest);
    } catch {
      out.push({ code: "manifest_not_serializable", message: "manifest is not JSON-serializable" });
    }
  }

  const health = await call(connector, "health");
  if (health.violation) {
    out.push(health.violation);
  } else if (
    !isObject(health.result) ||
    typeof health.result["state"] !== "string" ||
    !STATES.has(health.result["state"]) ||
    !isObject(health.result["rateLimit"]) ||
    !isObject(health.result["freshness"]) ||
    !isObject(health.result["coverage"])
  ) {
    out.push({ code: "health_type", message: "health() must return a HealthReport" });
  } else if (health.result["rateLimit"]["limited"] === true && health.result["state"] !== "rate_limited") {
    out.push({
      code: "health_rate_limit",
      message: "limited but state is not rate_limited",
    });
  }

  const coverage = await call(connector, "coverage");
  if (coverage.violation) {
    out.push(coverage.violation);
  } else if (!isObject(coverage.result) || !("expectedSources" in coverage.result)) {
    out.push({ code: "coverage_type", message: "coverage() must return a CoverageReport" });
  }

  const freshness = await call(connector, "freshness");
  if (freshness.violation) {
    out.push(freshness.violation);
  } else if (!isObject(freshness.result) || !("lagMs" in freshness.result)) {
    out.push({ code: "freshness_type", message: "freshness() must return a FreshnessReport" });
  } else if (
    freshness.result["lagMs"] === 0 &&
    !freshness.result["watermark"] &&
    !freshness.result["observedAt"]
  ) {
    out.push({
      code: "freshness_unknown_as_zero",
      message: "lagMs=0 with no observation",
    });
  }
  return out;
}
