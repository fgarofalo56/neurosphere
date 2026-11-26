import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it } from "vitest";
import { fakeFetch, problem, renderAdmin, stubResizeObserver } from "../shared/test-support";
import { ADMIN_AREAS } from "../shared/areas";
import { adminCoreRoutes } from "../routes";
import { CapturePage } from "./CapturePage";
import { ADMIN_CAPTURE_ROUTE, capturePaths } from "./paths";
import { OFF_REASON_TEXT, offReasonText } from "./strings";
import type { CapturePolicyView, CaptureStatus } from "./types";

beforeAll(stubResizeObserver);
afterEach(cleanup);

// Synthetic values only. A field the API never sends must never be rendered.
const LEAK = "NSCANARY-synthetic-leak";
const AUDIT_ID = "approval-audit-synthetic-1";

function policy(over: Partial<CapturePolicyView> = {}): CapturePolicyView {
  return {
    policy_id: "support-capture",
    display_name: "Support capture",
    version: 3,
    previous_version: 2,
    domain_id: "commercial:contoso:catalog:domain:support",
    source_ids: ["src-chat"],
    parts: ["prompt", "response"],
    detector_set_version: "ns-detectors-1",
    customer_dictionary_ids: [],
    redaction_mode: "redact_all_detections",
    kept_categories: ["email_address"],
    sampling: { rate: 0.25, max_per_minute: 60 },
    max_part_chars: 8192,
    retention_class: "interaction_default",
    retention_days: 30,
    state: "active",
    approved_intent_id: "intent-synthetic-1",
    approved_audit_id: AUDIT_ID,
    effective_from: "2026-11-21T08:00:00Z",
    ...over,
  };
}

function status(over: Partial<CaptureStatus> = {}): CaptureStatus {
  return {
    state: "off",
    off_reason: "setting_off",
    configured: true,
    domain_id: null,
    policies: { total: 2, proposed: 1, active: 1, suspended: 0, retired: 0 },
    policies_truncated: false,
    counters: null,
    counters_scope: "customer",
    ...over,
  };
}

function api(opts: {
  status?: unknown;
  statusCode?: number;
  policies?: unknown;
  policiesCode?: number;
  detail?: unknown;
}) {
  return fakeFetch((req) => {
    const path = req.url.pathname;
    if (path === capturePaths.status()) {
      if (opts.statusCode !== undefined && opts.statusCode >= 400) {
        return problem(opts.statusCode, "forbidden", "customer_scope_required");
      }
      return { body: opts.status ?? status() };
    }
    if (path === capturePaths.policies()) {
      if (opts.policiesCode !== undefined && opts.policiesCode >= 400) {
        return problem(opts.policiesCode, "forbidden", "customer_scope_required");
      }
      return {
        body: opts.policies ?? {
          items: [policy(), policy({ policy_id: "ops-capture", state: "proposed", approved_audit_id: null })],
          truncated: false,
          configured: true,
          reason: null,
        },
      };
    }
    if (path.startsWith(`${capturePaths.policies()}/`)) {
      return { body: opts.detail ?? { ...policy(), prompt: LEAK } };
    }
    return undefined;
  });
}

describe("CapturePage", () => {
  it("shows the off reason in plain words and the policy counts", async () => {
    const { impl } = api({});
    renderAdmin(<CapturePage />, impl);
    const reason = await screen.findByTestId("capture-off-reason");
    expect(reason).toHaveTextContent(OFF_REASON_TEXT.setting_off ?? "");
    expect(reason).toHaveTextContent("setting_off");
    expect(screen.getByTestId("capture-policy-counts")).toHaveTextContent("2 policies: 1 active");
    expect(screen.getByTestId("capture-no-counters")).toBeInTheDocument();
    expect(screen.getByTestId("capture-change-note")).toHaveTextContent("capture_policy_change");
    expect(screen.getByTestId("capture-change-note")).toHaveTextContent("PRP-108");
  });

  it("lists each policy with scope, parts, modes, sampling, state and approval audit id", async () => {
    const { impl, calls } = api({});
    renderAdmin(<CapturePage />, impl);
    const rows = await screen.findAllByTestId("capture-policy-row");
    expect(rows).toHaveLength(2);
    const first = within(rows[0] as HTMLElement);
    expect(first.getByText("commercial:contoso:catalog:domain:support")).toBeInTheDocument();
    expect(first.getByText("src-chat")).toBeInTheDocument();
    expect(first.getByText("prompt, response")).toBeInTheDocument();
    expect(first.getByText("redact_all_detections")).toBeInTheDocument();
    expect(first.getByText("25% of events, at most 60 per minute")).toBeInTheDocument();
    expect(first.getByText("Active")).toBeInTheDocument();
    expect(first.getByText(AUDIT_ID)).toBeInTheDocument();
    expect(within(rows[1] as HTMLElement).getByText("Proposed")).toBeInTheDocument();
    // Read-only: every request is a GET.
    expect(calls.every((c) => c.method === "GET")).toBe(true);
  });

  it("opens the detail and never renders a field the view does not name", async () => {
    const { impl, calls } = api({});
    renderAdmin(<CapturePage />, impl);
    fireEvent.click(await screen.findByRole("button", { name: "View support-capture" }));
    const detail = await screen.findByTestId("capture-policy-detail");
    expect(within(detail).getByTestId("capture-detail-approval")).toHaveTextContent(AUDIT_ID);
    expect(within(detail).getByText("email_address")).toBeInTheDocument();
    expect(within(detail).getByText("30 days (interaction_default)")).toBeInTheDocument();
    expect(document.body).not.toHaveTextContent(LEAK);
    expect(calls.some((c) => c.url.pathname === capturePaths.policy("support-capture"))).toBe(
      true,
    );
    fireEvent.click(screen.getByRole("button", { name: "Close detail" }));
    await waitFor(() => expect(screen.queryByTestId("capture-policy-detail")).toBeNull());
  });

  it("shows counters with failed reasons when capture is on", async () => {
    const { impl } = api({
      status: status({
        state: "active",
        off_reason: null,
        counters: {
          captured: 7,
          capture_skipped_no_policy: 2,
          capture_skipped_item_cap: 0,
          skipped_reasons: { domain_mismatch: 2 },
          capture_failed: { key_wrap_failed: 1 },
          capture_failed_total: 1,
          capture_shed: 3,
          shed_reasons: { queue_full: 3 },
          audit_write_failed: 0,
          failure_record_failed: 0,
          cleanup_failed: 0,
          in_flight: 0,
        },
      }),
    });
    renderAdmin(<CapturePage />, impl);
    expect(await screen.findByTestId("counter-captured")).toHaveTextContent("7");
    expect(screen.getByTestId("counter-shed")).toHaveTextContent("3");
    expect(screen.getByTestId("counter-failed")).toHaveTextContent("1");
    expect(screen.getByTestId("failed-reasons")).toHaveTextContent("key_wrap_failed: 1");
    expect(screen.getByTestId("shed-reasons")).toHaveTextContent("queue_full: 3");
    expect(screen.queryByTestId("capture-off-reason")).toBeNull();
    expect(screen.getByTestId("capture-state")).toHaveTextContent("Capture is on.");
  });

  it("shows the not-configured view as an empty state, not an error", async () => {
    const { impl } = api({
      status: status({ off_reason: "capture_not_configured", configured: false }),
      policies: { items: [], truncated: false, configured: false, reason: "capture_not_configured" },
    });
    renderAdmin(<CapturePage />, impl);
    expect(await screen.findByTestId("empty-state")).toHaveTextContent("not set up");
    expect(await screen.findByTestId("capture-off-reason")).toHaveTextContent(
      offReasonText("capture_not_configured"),
    );
  });

  it("shows the forbidden state once when the API denies the page", async () => {
    const { impl } = api({ statusCode: 403, policiesCode: 403 });
    renderAdmin(<CapturePage />, impl);
    expect(await screen.findByTestId("forbidden-state")).toBeInTheDocument();
    expect(await screen.findByTestId("panel-denied")).toBeInTheDocument();
    expect(screen.getAllByTestId("forbidden-state")).toHaveLength(1);
  });

  it("falls back to a generic sentence for an unknown reason code", () => {
    expect(offReasonText("some_future_reason")).toBe("Interaction capture is off.");
  });

  it("is registered as an admin area and route", () => {
    expect(ADMIN_AREAS.some((a) => a.to === `/${ADMIN_CAPTURE_ROUTE}`)).toBe(true);
    expect(adminCoreRoutes.some((r) => r.path === ADMIN_CAPTURE_ROUTE)).toBe(true);
  });
});
