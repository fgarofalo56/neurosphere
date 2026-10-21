import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { axe } from "vitest-axe";
import { QueryProvider, createApiClient } from "../../../api/index.js";
import { reviewNavItems, reviewRoutes } from "../index";
import type { ApprovalDecision, ActionIntent, ReviewItemView } from "../types";

class ResizeObserverStub {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}

beforeAll(() => {
  vi.stubGlobal("ResizeObserver", ResizeObserverStub);
});

afterEach(cleanup);

const DOMAIN = "commercial:contoso:catalog:domain:finance";
const ITEMS = `/api/v1/review/domains/${encodeURIComponent(DOMAIN)}/items`;
const ITEM_ID = "22222222-2222-4222-8222-222222222222";
const INTENT_ID = "11111111-1111-4111-8111-111111111111";
const INTENT = `/api/v1/actions/domains/${encodeURIComponent(DOMAIN)}/intents/${INTENT_ID}`;
const HASH = `sha256:${"b".repeat(64)}`;
const ITEM_PATH = `/review/item?domain_id=${encodeURIComponent(DOMAIN)}&item_id=${ITEM_ID}`;
const QUEUE_PATH = `/review?domain_id=${encodeURIComponent(DOMAIN)}`;

function decision(id: string, kind: "approved" | "rejected", reason: string): ApprovalDecision {
  return {
    schema_version: "1.0",
    decision_id: id,
    review_item_id: ITEM_ID,
    review_kind: "maker_checker",
    intent_id: INTENT_ID,
    approved_confirmation_hash: HASH,
    reviewer: { principal_pseudonym: `rev-${id}`, principal_kind: "user", on_behalf_of: null },
    maker: { principal_pseudonym: "p-maker", principal_kind: "user", on_behalf_of: null },
    self_approval_allowed: false,
    decision: kind,
    reason,
    policy_version: "p-1",
    decided_at: "2026-10-20T11:00:00Z",
    correlation_id: "c-1",
  };
}

function item(over: Partial<ReviewItemView> = {}): ReviewItemView {
  return {
    item_id: ITEM_ID,
    kind: "maker_checker",
    state: "pending",
    domain_id: DOMAIN,
    subject_ref: "commercial:contoso:foundry:model_deployment:support-gpt",
    intent_id: INTENT_ID,
    assignee_pseudonym: null,
    sla_due_at: "2099-01-01T00:00:00Z",
    escalation_level: 0,
    created_at: "2026-10-20T10:00:00Z",
    decisions: [],
    effective_decision_id: null,
    superseded_decision_ids: [],
    ...over,
  };
}

function intentView(): { intent: ActionIntent; advisory: boolean } {
  return {
    advisory: false,
    intent: {
      schema_version: "1.0",
      intent_id: INTENT_ID,
      action_kind: "model_deployment_swap",
      actor: { principal_pseudonym: "p-maker", principal_kind: "user", on_behalf_of: null },
      target: {
        canonical_id: "commercial:contoso:foundry:model_deployment:support-gpt",
        entity_type: "model_deployment",
      },
      target_version: "etag-7",
      proposed_diff: {
        format: "json_patch",
        operations: [{ op: "replace", path: "/properties/model/name", value: "gpt-4.1-mini" }],
      },
      prerequisite_results: [],
      evidence: [],
      confirmation_hash: HASH,
      confirmation_expires_at: "2099-01-01T00:00:00Z",
      idempotency_key: "button-swap-0001-fixture",
      channel: "button",
      state: "awaiting_approval",
      status_reason: null,
      dry_run: false,
      correlation_id: "c-1",
      created_at: "2026-10-20T10:00:00Z",
      state_changed_at: "2026-10-20T10:01:00Z",
    },
  };
}

interface Reply {
  status: number;
  body: unknown;
}

function problem(status: number, code: string): Reply {
  return {
    status,
    body: {
      type: "about:blank",
      title: code,
      status,
      code,
      retryable: status === 503,
      correlation_id: "corr-9",
    },
  };
}

interface Call {
  method: string;
  path: string;
  search: string;
  body: unknown;
}

function setup(path: string, routes: Record<string, Reply | ((c: Call) => Reply)>) {
  const calls: Call[] = [];
  const fetchImpl = vi.fn<typeof fetch>((input, init) => {
    const url = new URL(String(input));
    const call: Call = {
      method: init?.method ?? "GET",
      path: url.pathname,
      search: url.search,
      body: typeof init?.body === "string" ? (JSON.parse(init.body) as unknown) : undefined,
    };
    calls.push(call);
    const route = routes[`${call.method} ${call.path}`];
    if (route === undefined) {
      return Promise.resolve(new Response(JSON.stringify({ status: 404 }), { status: 404 }));
    }
    const reply = typeof route === "function" ? route(call) : route;
    return Promise.resolve(new Response(JSON.stringify(reply.body), { status: reply.status }));
  });
  const client = createApiClient({
    baseUrl: "http://api.test",
    getToken: () => Promise.resolve("t"),
    fetchImpl,
    maxRetries: 0,
  });
  const router = createMemoryRouter(reviewRoutes, { initialEntries: [path] });
  const utils = render(
    <QueryProvider client={client}>
      <RouterProvider router={router} />
    </QueryProvider>,
  );
  return { calls, ...utils };
}

describe("exports", () => {
  it("exports the routes and nav item", () => {
    expect(reviewRoutes.map((r) => r.path)).toEqual(["review", "review/item"]);
    expect(reviewNavItems()).toEqual([{ to: "/review", label: "Review" }]);
  });
});

describe("reviewer queue", () => {
  const rows = [
    item({ assignee_pseudonym: "rev-1", escalation_level: 2, sla_due_at: "2020-01-01T00:00:00Z" }),
    item({
      item_id: "33333333-3333-4333-8333-333333333333",
      kind: "relationship",
      intent_id: null,
      subject_ref: "commercial:contoso:catalog:agent:triage",
    }),
  ];

  it("renders items with SLA due, overdue marker and escalation level", async () => {
    setup(QUEUE_PATH, {
      [`GET ${ITEMS}`]: { status: 200, body: { items: rows, next_cursor: null } },
    });
    const rendered = await screen.findAllByTestId("review-row");
    expect(rendered).toHaveLength(2);
    const first = rendered[0];
    expect(first && within(first).getByTestId("sla-due").textContent).toBe(
      "2020-01-01T00:00:00Z (overdue)",
    );
    expect(first && within(first).getByTestId("escalation-level").textContent).toBe("2");
    expect(first?.textContent).toContain("rev-1");
    expect(rendered[1]?.textContent).toContain("unassigned");
  });

  it("filters by kind and state through the API query", async () => {
    const { calls } = setup(QUEUE_PATH, {
      [`GET ${ITEMS}`]: (c) => ({
        status: 200,
        body: {
          items: new URLSearchParams(c.search).get("kind") === "relationship" ? [rows[1]] : rows,
          next_cursor: null,
        },
      }),
    });
    expect(await screen.findAllByTestId("review-row")).toHaveLength(2);
    const user = userEvent.setup();
    await user.selectOptions(screen.getByLabelText("Kind"), "relationship");
    await user.selectOptions(screen.getByLabelText("State"), "pending");
    await user.click(screen.getByRole("button", { name: "Apply filters" }));
    await waitFor(() => expect(screen.getAllByTestId("review-row")).toHaveLength(1));
    const last = calls[calls.length - 1];
    const q = new URLSearchParams(last?.search);
    expect(q.get("kind")).toBe("relationship");
    expect(q.get("state")).toBe("pending");
    expect(q.has("domain_id")).toBe(false);
  });

  it("shows a retryable service-unavailable state on 503, not an empty queue", async () => {
    setup(QUEUE_PATH, { [`GET ${ITEMS}`]: problem(503, "dependency_transient") });
    const state = await screen.findByTestId("unavailable-state");
    expect(state.textContent).toContain("Service unavailable");
    expect(within(state).getByRole("button", { name: "Retry" })).toBeTruthy();
    expect(screen.queryByTestId("empty-state")).toBeNull();
  });
});

describe("review item", () => {
  it("marks superseded decisions apart from the effective one", async () => {
    const decisions = [
      decision("aaaaaaaa-0000-4000-8000-000000000001", "approved", "looks right"),
      decision("aaaaaaaa-0000-4000-8000-000000000002", "rejected", "lost the race"),
    ];
    setup(ITEM_PATH, {
      [`GET ${ITEMS}/${ITEM_ID}`]: {
        status: 200,
        body: item({
          state: "approved",
          decisions,
          effective_decision_id: "aaaaaaaa-0000-4000-8000-000000000001",
          superseded_decision_ids: ["aaaaaaaa-0000-4000-8000-000000000002"],
        }),
      },
      [`GET ${INTENT}`]: { status: 200, body: intentView() },
    });
    const rendered = await screen.findAllByTestId("decision");
    expect(rendered).toHaveLength(2);
    expect(within(rendered[0] as HTMLElement).getByTestId("decision-effective").textContent).toBe(
      "Effective",
    );
    expect(within(rendered[0] as HTMLElement).queryByTestId("decision-superseded")).toBeNull();
    expect(within(rendered[1] as HTMLElement).getByTestId("decision-superseded").textContent).toBe(
      "Superseded",
    );
    expect(within(rendered[1] as HTMLElement).queryByTestId("decision-effective")).toBeNull();
    // A closed item offers no way to decide again.
    expect(screen.queryByRole("button", { name: "Approve" })).toBeNull();
    expect(screen.getByTestId("item-final")).toBeTruthy();
  });

  it("shows the exact change and approves with the server confirmation hash", async () => {
    const decided = item({
      state: "approved",
      decisions: [decision("aaaaaaaa-0000-4000-8000-000000000001", "approved", "ok")],
      effective_decision_id: "aaaaaaaa-0000-4000-8000-000000000001",
    });
    const { calls } = setup(ITEM_PATH, {
      [`GET ${ITEMS}/${ITEM_ID}`]: { status: 200, body: item() },
      [`GET ${INTENT}`]: { status: 200, body: intentView() },
      [`POST ${ITEMS}/${ITEM_ID}/decisions`]: { status: 200, body: decided },
    });
    expect((await screen.findByTestId("review-target")).textContent).toContain("support-gpt");
    expect(screen.getByTestId("review-version").textContent).toBe("etag-7");
    expect(screen.getByTestId("review-diff").textContent).toContain("/properties/model/name");
    const user = userEvent.setup();
    const approve = screen.getByRole("button", { name: "Approve" });
    await waitFor(() => expect((approve as HTMLButtonElement).disabled).toBe(true));
    await user.type(screen.getByLabelText("Reason for your decision"), "ok");
    await waitFor(() => expect((approve as HTMLButtonElement).disabled).toBe(false));
    await user.click(approve);
    await screen.findByTestId("item-final");
    const post = calls.find((c) => c.method === "POST");
    expect(post?.path).toBe(`${ITEMS}/${ITEM_ID}/decisions`);
    expect(post?.body).toEqual({ decision: "approved", reason: "ok", confirmation_hash: HASH });
  });

  it("sends no confirmation hash for insight reviews", async () => {
    const { calls } = setup(ITEM_PATH, {
      [`GET ${ITEMS}/${ITEM_ID}`]: {
        status: 200,
        body: item({ kind: "relationship", intent_id: null }),
      },
      [`POST ${ITEMS}/${ITEM_ID}/decisions`]: {
        status: 200,
        body: item({ kind: "relationship", intent_id: null, state: "rejected" }),
      },
    });
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("Reason for your decision"), "wrong link");
    await user.click(screen.getByRole("button", { name: "Reject" }));
    await screen.findByTestId("item-final");
    expect(calls.find((c) => c.method === "POST")?.body).toEqual({
      decision: "rejected",
      reason: "wrong link",
    });
  });

  it("claims an item with a null assignee", async () => {
    const { calls } = setup(ITEM_PATH, {
      [`GET ${ITEMS}/${ITEM_ID}`]: {
        status: 200,
        body: item({ kind: "relationship", intent_id: null }),
      },
      [`POST ${ITEMS}/${ITEM_ID}/assignment`]: {
        status: 200,
        body: item({
          kind: "relationship",
          intent_id: null,
          state: "assigned",
          assignee_pseudonym: "me-1",
        }),
      },
    });
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Claim this item" }));
    await waitFor(() => expect(screen.getByTestId("item-assignee").textContent).toBe("me-1"));
    expect(calls.find((c) => c.method === "POST")?.body).toEqual({ assignee_principal_id: null });
  });

  it("explains a 403 on approve and does not show success", async () => {
    setup(ITEM_PATH, {
      [`GET ${ITEMS}/${ITEM_ID}`]: { status: 200, body: item() },
      [`GET ${INTENT}`]: { status: 200, body: intentView() },
      [`POST ${ITEMS}/${ITEM_ID}/decisions`]: problem(403, "forbidden"),
    });
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("Reason for your decision"), "fine");
    const approve = screen.getByRole("button", { name: "Approve" });
    await waitFor(() => expect((approve as HTMLButtonElement).disabled).toBe(false));
    await user.click(approve);
    const error = await screen.findByTestId("mutation-error");
    expect(error.textContent).toContain("You don't have permission to approve this item");
    expect(screen.queryByTestId("item-final")).toBeNull();
    expect(screen.getByTestId("review-item").textContent).toContain("pending");
  });

  it("explains a 403 when a deep link cannot even load the item", async () => {
    setup(ITEM_PATH, { [`GET ${ITEMS}/${ITEM_ID}`]: problem(403, "forbidden") });
    const state = await screen.findByTestId("forbidden-state");
    expect(state.textContent).toContain("You don't have permission to approve this item");
    expect(screen.queryByRole("button", { name: "Approve" })).toBeNull();
  });

  it("shows a retryable state on 503 when loading the item", async () => {
    setup(ITEM_PATH, { [`GET ${ITEMS}/${ITEM_ID}`]: problem(503, "dependency_transient") });
    const state = await screen.findByTestId("unavailable-state");
    expect(within(state).getByRole("button", { name: "Retry" })).toBeTruthy();
  });

  it("has no axe violations on the item page", async () => {
    const { container } = setup(ITEM_PATH, {
      [`GET ${ITEMS}/${ITEM_ID}`]: { status: 200, body: item() },
      [`GET ${INTENT}`]: { status: 200, body: intentView() },
    });
    await screen.findByTestId("review-item");
    await screen.findByTestId("intent-under-review");
    const results = await axe(container);
    expect(results.violations.map((x) => `${x.id}: ${x.help}`)).toEqual([]);
  });
});
