import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { ConfirmationDialog } from "../components";
import { PlanPreview, digestPrefix, parsePlan } from "../PlanPreview";
import { STRINGS } from "../strings";
import type { ActionIntent, ProposedDiff } from "../types";

class ResizeObserverStub {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}

beforeAll(() => {
  vi.stubGlobal("ResizeObserver", ResizeObserverStub);
});

afterEach(() => {
  cleanup();
});

const DIGEST = `${"ab12cd34ef56".repeat(5)}abcd`;
const HASH = `sha256:${"a".repeat(64)}`;

const PLAN_DIFF: ProposedDiff = {
  format: "json_patch",
  operations: [
    { op: "test", path: "/plan_digest", value: DIGEST },
    { op: "add", path: "/resources/backends~1b-support", value: {} },
    { op: "add", path: "/resources/apis~1finance~1operations~1get", value: {} },
    { op: "add", path: "/publication", value: {} },
  ],
};

describe("parsePlan", () => {
  it("reads the digest and one row per resource operation, in diff order", () => {
    const plan = parsePlan(PLAN_DIFF);
    expect(plan.digest).toBe(DIGEST);
    expect(plan.rows.map((r) => [r.resourceType, r.name, r.operation, r.expected])).toEqual([
      ["backend", "backends/b-support", "add", null],
      ["api_operation", "apis/finance/operations/get", "add", null],
    ]);
  });

  it("takes expected create or found only from reported steps, never invents it", () => {
    const plan = parsePlan(PLAN_DIFF, [
      { resource_type: "backend", name: "backends/b-support", expected: "found" },
    ]);
    expect(plan.rows[0]?.expected).toBe("found");
    expect(plan.rows[1]?.expected).toBeNull();
  });

  it("has no plan for a diff without a digest or resources", () => {
    const plan = parsePlan({
      format: "json_patch",
      operations: [{ op: "replace", path: "/properties/model/name", value: "x" }],
    });
    expect(plan).toEqual({ digest: null, rows: [] });
  });

  it("ignores a digest that is not a test operation with a string value", () => {
    const plan = parsePlan({
      format: "json_patch",
      operations: [{ op: "add", path: "/plan_digest", value: DIGEST }],
    });
    expect(plan.digest).toBeNull();
  });
});

describe("digestPrefix", () => {
  it("keeps the first 12 hex characters and drops a sha256 label", () => {
    expect(digestPrefix(DIGEST)).toBe("ab12cd34ef56");
    expect(digestPrefix(`sha256:${DIGEST}`)).toBe("ab12cd34ef56");
  });
});

describe("PlanPreview", () => {
  function renderPlan(diff: ProposedDiff, steps?: Parameters<typeof PlanPreview>[0]["steps"]) {
    return render(
      <dl>
        <PlanPreview diff={diff} steps={steps} />
      </dl>,
    );
  }

  it("renders nothing for a change with no plan", () => {
    renderPlan({
      format: "json_patch",
      operations: [{ op: "replace", path: "/properties/model/name", value: "x" }],
    });
    expect(screen.queryByTestId("plan-preview")).toBeNull();
  });

  it("shows the digest prefix and each step with its resource type and name", () => {
    renderPlan(PLAN_DIFF);
    expect(screen.getByTestId("plan-digest").textContent).toContain("ab12cd34ef56");
    const steps = screen.getAllByTestId("plan-step");
    expect(steps).toHaveLength(2);
    expect(within(steps[0]!).getByTestId("plan-step-type").textContent).toBe("backend");
    expect(within(steps[0]!).getByTestId("plan-step-name").textContent).toBe("backends/b-support");
  });

  it("says plainly that the expected outcome is not reported when the API gives none", () => {
    renderPlan(PLAN_DIFF);
    for (const cell of screen.getAllByTestId("plan-step-expected")) {
      expect(cell.textContent).toBe(STRINGS.plan.notReported);
    }
  });

  it("shows create or found per step when the API reports them", () => {
    renderPlan(PLAN_DIFF, [
      { resource_type: "backend", name: "backends/b-support", expected: "create" },
      { resource_type: "api_operation", name: "apis/finance/operations/get", expected: "found" },
    ]);
    const cells = screen.getAllByTestId("plan-step-expected");
    expect(cells.map((c) => c.textContent)).toEqual(["create", "found"]);
  });
});

describe("confirmation dialog with a plan", () => {
  it("shows the plan beside the exact diff", async () => {
    const intent: ActionIntent = {
      schema_version: "1.0",
      intent_id: "11111111-1111-4111-8111-111111111111",
      action_kind: "grant_publish",
      actor: { principal_pseudonym: "p-maker", principal_kind: "user", on_behalf_of: null },
      target: { canonical_id: "commercial:e2e:catalog:grant:g", entity_type: "grant" },
      target_version: "unpublished",
      proposed_diff: PLAN_DIFF,
      prerequisite_results: [],
      evidence: [],
      confirmation_hash: HASH,
      confirmation_expires_at: new Date(Date.now() + 600_000).toISOString(),
      idempotency_key: "button-plan-0000001",
      channel: "button",
      state: "awaiting_confirmation",
      status_reason: null,
      dry_run: false,
      correlation_id: "c-1",
      created_at: "2026-10-20T10:00:00Z",
      state_changed_at: "2026-10-20T10:01:00Z",
    };
    render(
      <ConfirmationDialog
        intent={intent}
        requiresApproval
        submitting={false}
        error={null}
        onSubmit={() => undefined}
        onClose={() => undefined}
      />,
    );
    const dialog = await screen.findByRole("alertdialog", { hidden: true });
    expect(within(dialog).getByTestId("plan-preview")).toBeTruthy();
    expect(within(dialog).getByTestId("plan-digest").textContent).toContain("ab12cd34ef56");
    expect(within(dialog).getAllByTestId("plan-step")).toHaveLength(2);
    // The exact diff is still listed in full.
    expect(within(dialog).getAllByTestId("diff-op")).toHaveLength(4);
  });
});
