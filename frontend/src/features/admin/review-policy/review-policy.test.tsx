import { cleanup, fireEvent, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, describe, expect, it } from "vitest";
import { fakeFetch, problem, renderAdmin, stubResizeObserver, type FakeRequest } from "../shared/test-support";
import { describeSeconds, joinSeconds, splitSeconds } from "./duration";
import { ReviewPolicyPage } from "./ReviewPolicyPage";

beforeAll(stubResizeObserver);
afterEach(cleanup);

function policy(sla: number) {
  return {
    self_approval_forbidden: true,
    approver_permission: "action.approve",
    assignment_timeout_seconds: 3600,
    sla_seconds: sla,
    escalation_step_seconds: 7200,
    max_escalations: 2,
    expiry_seconds: 259_200,
  };
}
const DOC = {
  schema_version: "1.0.0",
  policy_version: "policy-1",
  kind_defaults: [{ review_kind: "maker_checker", policy: policy(14_400) }],
  action_overrides: [
    { review_kind: "maker_checker", action_kind: "model_swap", policy: policy(5415) },
  ],
};
const VIEW = { source: "stored", version: 1, policy_version: "policy-1", document: DOC };

function handler(extra?: (req: FakeRequest) => ReturnType<Parameters<typeof fakeFetch>[0]>) {
  return (req: FakeRequest) =>
    extra?.(req) ?? { body: VIEW, headers: { ETag: '"policy-1"' } };
}

describe("duration helpers", () => {
  it("round-trip whole seconds through hours and minutes", () => {
    for (const s of [1, 59, 60, 3599, 3600, 5415, 259_200, 7_776_000]) {
      expect(joinSeconds(splitSeconds(s))).toBe(s);
    }
    expect(describeSeconds(5415)).toBe("1 h 30 min 15 s");
  });
});

describe("ReviewPolicyPage", () => {
  it("shows kind defaults, overrides and the effective policy", async () => {
    const { impl } = fakeFetch(handler());
    renderAdmin(<ReviewPolicyPage />, impl);
    expect(await screen.findAllByTestId("kind-default")).toHaveLength(1);
    expect(screen.getAllByTestId("action-override")).toHaveLength(1);
    const preview = screen.getByTestId("effective-policy").textContent ?? "";
    expect(preview).toContain("maker_checker/model_swap");
    expect(preview).toContain("SLA 4 h 0 min");
    expect(preview).toContain("SLA 1 h 30 min 15 s");
  });

  it("sends whole seconds with If-Match after confirming the diff", async () => {
    const { impl, calls } = fakeFetch(
      handler((req) =>
        req.method === "PUT" ? { body: { ...VIEW, version: 2, before: DOC, changes: [] } } : undefined,
      ),
    );
    renderAdmin(<ReviewPolicyPage />, impl);
    const hours = await screen.findByLabelText("maker_checker: SLA hours", { selector: "input" });
    fireEvent.change(hours, { target: { value: "6" } });
    await userEvent.click(screen.getByRole("button", { name: "Save review policy" }));
    const dlg = within(await screen.findByTestId("change-confirm-dialog"));
    expect(dlg.getByTestId("change-diff").textContent).toContain("default maker_checker");
    await userEvent.click(dlg.getByRole("button", { name: "Confirm change", hidden: true }));
    expect(await screen.findByTestId("policy-saved")).toBeTruthy();
    const put = calls.find((c) => c.method === "PUT");
    expect(put?.headers.get("If-Match")).toBe('"policy-1"');
    const sent = put?.body as typeof DOC;
    expect(sent.kind_defaults[0]?.policy.sla_seconds).toBe(21_600);
    // The override keeps its odd remainder exactly.
    expect(sent.action_overrides[0]?.policy.sla_seconds).toBe(5415);
  });

  it("shows the API validation text and a stale message", async () => {
    const bad = fakeFetch(
      handler((req) =>
        req.method === "PUT"
          ? problem(422, "invalid_schema", "expiry_seconds must not be shorter than sla_seconds")
          : undefined,
      ),
    );
    renderAdmin(<ReviewPolicyPage />, bad.impl);
    fireEvent.change(await screen.findByLabelText("maker_checker: SLA hours", { selector: "input" }), {
      target: { value: "5" },
    });
    await userEvent.click(screen.getByRole("button", { name: "Save review policy" }));
    const dlg = within(await screen.findByTestId("change-confirm-dialog"));
    await userEvent.click(dlg.getByRole("button", { name: "Confirm change", hidden: true }));
    expect((await screen.findByTestId("policy-error")).textContent).toContain("shorter than sla");
    cleanup();
    const stale = fakeFetch(
      handler((req) => (req.method === "PUT" ? problem(409, "stale_version", "etag_mismatch") : undefined)),
    );
    renderAdmin(<ReviewPolicyPage />, stale.impl);
    fireEvent.change(await screen.findByLabelText("maker_checker: SLA hours", { selector: "input" }), {
      target: { value: "5" },
    });
    await userEvent.click(screen.getByRole("button", { name: "Save review policy" }));
    const dlg2 = within(await screen.findByTestId("change-confirm-dialog"));
    await userEvent.click(dlg2.getByRole("button", { name: "Confirm change", hidden: true }));
    expect((await screen.findByTestId("policy-error")).textContent).toContain("Reload");
  });

  it("adds and removes an override", async () => {
    const { impl } = fakeFetch(handler());
    renderAdmin(<ReviewPolicyPage />, impl);
    await screen.findAllByTestId("kind-default");
    fireEvent.change(screen.getByLabelText("Override action kind"), { target: { value: "grant" } });
    await userEvent.click(screen.getByRole("button", { name: "Add override" }));
    expect(screen.getAllByTestId("action-override")).toHaveLength(2);
    await userEvent.click(screen.getByRole("button", { name: "Remove override maker_checker/grant" }));
    expect(screen.getAllByTestId("action-override")).toHaveLength(1);
  });

  it("shows forbidden and error states", async () => {
    const denied = fakeFetch(() => problem(403, "forbidden", "permission_missing"));
    renderAdmin(<ReviewPolicyPage />, denied.impl);
    expect(await screen.findByTestId("forbidden-state")).toBeTruthy();
  });
});
