import { act, cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { axe } from "vitest-axe";
import { QueryProvider, createApiClient } from "../../../api/index.js";
import { ConfirmationDialog } from "../components";
import fixture from "../__fixtures__/button-intent-request.json";
import { actionsNavItems, actionsRoutes, buildDraftIntentRequest } from "../index";
import type { ActionIntent, ActionView, EmergencyDisableView } from "../types";

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
  vi.useRealTimers();
});

const DOMAIN = "commercial:contoso:catalog:domain:finance";
const TARGET = "commercial:contoso:foundry:model_deployment:support-gpt";
const HASH = `sha256:${"a".repeat(64)}`;
const INTENT_ID = "11111111-1111-4111-8111-111111111111";
const BASE = `/api/v1/actions/domains/${encodeURIComponent(DOMAIN)}/intents`;
const DETAIL_PATH = `/actions/detail?domain_id=${encodeURIComponent(DOMAIN)}&intent_id=${INTENT_ID}`;

function intent(over: Partial<ActionIntent> = {}): ActionIntent {
  return {
    schema_version: "1.0",
    intent_id: INTENT_ID,
    action_kind: "model_deployment_swap",
    actor: { principal_pseudonym: "p-maker", principal_kind: "user", on_behalf_of: null },
    target: { canonical_id: TARGET, entity_type: "model_deployment" },
    target_version: "etag-7",
    proposed_diff: {
      format: "json_patch",
      operations: [
        { op: "replace", path: "/properties/model/name", value: "gpt-4.1-mini" },
        { op: "replace", path: "/properties/model/version", value: "2026-04-14" },
      ],
    },
    prerequisite_results: [
      {
        check_id: "actor_permission",
        status: "passed",
        detail: null,
        evaluated_at: "2026-10-20T10:00:00Z",
        evidence_ids: [],
      },
    ],
    evidence: [],
    confirmation_hash: HASH,
    confirmation_expires_at: new Date(Date.now() + 10 * 60_000).toISOString(),
    idempotency_key: "button-swap-0001-fixture",
    channel: "button",
    state: "awaiting_confirmation",
    status_reason: null,
    dry_run: false,
    correlation_id: "c-1",
    created_at: "2026-10-20T10:00:00Z",
    state_changed_at: "2026-10-20T10:01:00Z",
    ...over,
  };
}

function view(over: Partial<ActionView> = {}, intentOver: Partial<ActionIntent> = {}): ActionView {
  return {
    intent: intent(intentOver),
    advisory: false,
    requires_approval: false,
    self_approval_forbidden: false,
    review_item_id: null,
    execution: null,
    ...over,
  };
}

interface Reply {
  status: number;
  body: unknown;
}
type Routes = Record<string, Reply | (() => Reply)>;

const NOT_DISABLED: EmergencyDisableView = {
  disabled: false,
  reason: null,
  changed_by: null,
  changed_at: null,
};

function problem(status: number, code: string, reason?: string): Reply {
  return {
    status,
    body: {
      type: "about:blank",
      title: code,
      status,
      code,
      retryable: false,
      correlation_id: "corr-1",
      ...(reason !== undefined && { reason }),
    },
  };
}

interface Call {
  method: string;
  path: string;
  body: unknown;
}

function setup(path: string, routes: Routes) {
  const calls: Call[] = [];
  const fetchImpl = vi.fn<typeof fetch>((input, init) => {
    const url = new URL(String(input));
    const method = init?.method ?? "GET";
    const body = typeof init?.body === "string" ? (JSON.parse(init.body) as unknown) : undefined;
    calls.push({ method, path: url.pathname, body });
    const route =
      routes[`${method} ${url.pathname}`] ??
      (url.pathname === "/api/v1/actions/emergency-disable"
        ? { status: 200, body: NOT_DISABLED }
        : undefined);
    if (route === undefined) {
      return Promise.resolve(new Response(JSON.stringify({ status: 404 }), { status: 404 }));
    }
    const reply = typeof route === "function" ? route() : route;
    return Promise.resolve(new Response(JSON.stringify(reply.body), { status: reply.status }));
  });
  const client = createApiClient({
    baseUrl: "http://api.test",
    getToken: () => Promise.resolve("t"),
    fetchImpl,
    maxRetries: 0,
  });
  const router = createMemoryRouter(actionsRoutes, { initialEntries: [path] });
  const utils = render(
    <QueryProvider client={client}>
      <RouterProvider router={router} />
    </QueryProvider>,
  );
  return { calls, fetchImpl, ...utils };
}

describe("exports", () => {
  it("exports the routes and nav item", () => {
    expect(actionsRoutes.map((r) => r.path)).toEqual([
      "actions",
      "actions/detail",
      "actions/propose",
    ]);
    expect(actionsNavItems()).toEqual([{ to: "/actions", label: "Actions" }]);
  });
});

describe("buildDraftIntentRequest", () => {
  const input = {
    canonicalId: TARGET,
    targetVersion: "etag-7",
    newModelName: "gpt-4.1-mini",
    newModelVersion: "2026-04-14",
    idempotencyKey: "button-swap-0001-fixture",
  } as const;

  it("equals the shared fixture item 7 posts against the REST body", () => {
    expect(buildDraftIntentRequest(input)).toEqual(fixture);
  });

  it("carries the button channel and no identity or scope fields", () => {
    const request = buildDraftIntentRequest(input);
    expect(request.channel).toBe("button");
    const text = JSON.stringify(request);
    for (const forbidden of [
      "actor",
      "principal",
      "customer_id",
      "domain_id",
      "confirmation_hash",
    ]) {
      expect(text).not.toContain(forbidden);
    }
  });

  it("omits the version operation when no model version is given", () => {
    const request = buildDraftIntentRequest({ ...input, newModelVersion: "  " });
    expect(request.proposed_diff.operations).toHaveLength(1);
  });
});

describe("confirmation dialog", () => {
  it("shows the exact target, version, every diff operation and the expiry", async () => {
    const v = view();
    setup(DETAIL_PATH, { [`GET ${BASE}/${INTENT_ID}`]: { status: 200, body: v } });
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Review and confirm" }));
    const dialog = await screen.findByRole("alertdialog");
    expect(within(dialog).getByTestId("confirm-target").textContent).toBe(TARGET);
    expect(within(dialog).getByTestId("confirm-version").textContent).toBe("etag-7");
    const ops = within(dialog).getAllByTestId("diff-op");
    expect(ops).toHaveLength(2);
    expect(ops[0]?.textContent).toContain("/properties/model/name");
    expect(ops[0]?.textContent).toContain('"gpt-4.1-mini"');
    expect(ops[1]?.textContent).toContain("/properties/model/version");
    expect(within(dialog).getByTestId("confirm-expiry").textContent).toBe(
      v.intent.confirmation_expires_at,
    );
    expect(within(dialog).getByTestId("confirm-countdown").textContent).toMatch(/^\d+:\d{2}$/);
  });

  it("returns focus to the Review and confirm trigger on Escape and on Cancel", async () => {
    setup(DETAIL_PATH, { [`GET ${BASE}/${INTENT_ID}`]: { status: 200, body: view() } });
    const user = userEvent.setup();
    const trigger = await screen.findByRole("button", { name: "Review and confirm" });
    await user.click(trigger);
    await screen.findByRole("alertdialog");
    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
    await waitFor(() => expect(document.activeElement).toBe(trigger));

    await user.click(trigger);
    await user.click(await screen.findByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
    await waitFor(() => expect(document.activeElement).toBe(trigger));
  });

  it("submits the server-issued hash and nothing recomputed", async () => {
    const after = view({}, { state: "executing" });
    const { calls } = setup(DETAIL_PATH, {
      [`GET ${BASE}/${INTENT_ID}`]: { status: 200, body: view() },
      [`POST ${BASE}/${INTENT_ID}/confirm`]: { status: 200, body: after },
    });
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Review and confirm" }));
    await user.click(await screen.findByRole("button", { name: "Confirm and run" }));
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
    const post = calls.find((c) => c.method === "POST");
    expect(post?.path).toBe(`${BASE}/${INTENT_ID}/confirm`);
    expect(post?.body).toEqual({ confirmation_hash: HASH });
    expect(screen.getByTestId("state-badge").textContent).toBe("executing");
  });

  it("cannot be submitted once expired", async () => {
    const expired = view(
      {},
      { confirmation_expires_at: new Date(Date.now() - 1000).toISOString() },
    );
    const { calls } = setup(DETAIL_PATH, {
      [`GET ${BASE}/${INTENT_ID}`]: { status: 200, body: expired },
    });
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Review and confirm" }));
    const submit = await screen.findByRole("button", { name: "Confirm and run" });
    expect((submit as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByTestId("confirm-status").textContent).toContain("has expired");
    await user.click(submit);
    expect(calls.some((c) => c.method === "POST")).toBe(false);
  });

  it("counts down silently and disables submit when the expiry passes", () => {
    vi.useFakeTimers({
      now: new Date("2026-10-20T10:00:00Z"),
      toFake: ["Date", "setInterval", "clearInterval"],
    });
    const onSubmit = vi.fn();
    render(
      <ConfirmationDialog
        intent={intent({ confirmation_expires_at: "2026-10-20T10:00:03Z" })}
        requiresApproval={false}
        submitting={false}
        error={null}
        onSubmit={onSubmit}
        onClose={() => undefined}
      />,
    );
    const countdown = screen.getByTestId("confirm-countdown");
    expect(countdown.textContent).toBe("0:03");
    // The ticking element is not a live region; only the status line announces changes.
    expect(countdown.closest("[aria-live]")).toBeNull();
    expect(screen.getByTestId("confirm-status").getAttribute("aria-live")).toBe("polite");
    expect(screen.getByTestId("confirm-status").textContent).toBe("Confirmation is valid.");
    expect(
      (screen.getByRole("button", { name: "Confirm and run" }) as HTMLButtonElement).disabled,
    ).toBe(false);
    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(countdown.textContent).toBe("0:02");
    expect(screen.getByTestId("confirm-status").textContent).toBe("Confirmation is valid.");
    act(() => {
      vi.advanceTimersByTime(2500);
    });
    expect(countdown.textContent).toBe("0:00");
    expect(
      (screen.getByRole("button", { name: "Confirm and run" }) as HTMLButtonElement).disabled,
    ).toBe(true);
    expect(screen.getByTestId("confirm-status").textContent).toContain("has expired");
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it.each([
    ["confirmation_expired", "This confirmation expired. Re-validate"],
    ["target_version_changed", "The target changed since you validated it. Re-validate"],
  ])("shows a re-validate message for stale_version %s", async (reason, text) => {
    setup(DETAIL_PATH, {
      [`GET ${BASE}/${INTENT_ID}`]: { status: 200, body: view() },
      [`POST ${BASE}/${INTENT_ID}/confirm`]: problem(409, "stale_version", reason),
    });
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Review and confirm" }));
    await user.click(await screen.findByRole("button", { name: "Confirm and run" }));
    const alert = await screen.findByTestId("action-error");
    expect(alert.textContent).toContain(text);
    expect(alert.textContent).toContain("corr-1");
    // Not treated as success: the dialog is still open and the state unchanged.
    expect(screen.getByRole("alertdialog")).toBeTruthy();
  });

  it("shows a clear message and never success on a 403", async () => {
    setup(DETAIL_PATH, {
      [`GET ${BASE}/${INTENT_ID}`]: { status: 200, body: view() },
      [`POST ${BASE}/${INTENT_ID}/confirm`]: problem(403, "forbidden"),
    });
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Review and confirm" }));
    await user.click(await screen.findByRole("button", { name: "Confirm and run" }));
    expect((await screen.findByTestId("action-error")).textContent).toContain(
      "You do not have permission to run this action",
    );
  });
});

describe("advisory intents", () => {
  it("say advisory only and offer no confirm or execute control", async () => {
    setup(DETAIL_PATH, {
      [`GET ${BASE}/${INTENT_ID}`]: { status: 200, body: view({ advisory: true }) },
    });
    const note = await screen.findByTestId("advisory-note");
    expect(note.textContent).toBe(
      "Advisory only — no supported write connector; nothing will be changed",
    );
    expect(screen.queryByRole("button", { name: /confirm|execute|validate|run/i })).toBeNull();
  });
});

describe("status views", () => {
  it("shows execution phase, canary, verification and rollback", async () => {
    setup(DETAIL_PATH, {
      [`GET ${BASE}/${INTENT_ID}`]: {
        status: 200,
        body: view(
          {
            execution: {
              phase: "done",
              canary: "failed",
              verify_matched: false,
              rolled_back: true,
            },
          },
          { state: "rolled_back", status_reason: "canary_failed", confirmation_hash: HASH },
        ),
      },
    });
    await screen.findByTestId("execution");
    expect(screen.getByTestId("execution-phase").textContent).toBe("done");
    expect(screen.getByTestId("execution-canary").textContent).toBe("failed");
    expect(screen.getByTestId("execution-verify").textContent).toBe(
      "Did not match the proposed state",
    );
    expect(screen.getByTestId("execution-rollback").textContent).toBe("Rolled back");
    expect(screen.getByTestId("status-reason").textContent).toBe("canary_failed");
    expect(screen.getByTestId("prerequisite").textContent).toContain("actor_permission: passed");
    expect(screen.queryByRole("button", { name: /confirm/i })).toBeNull();
  });

  it("lists intents for a domain with their state", async () => {
    const { calls } = setup(`/actions?domain_id=${encodeURIComponent(DOMAIN)}&state=executing`, {
      [`GET ${BASE}`]: {
        status: 200,
        body: { items: [view({}, { state: "executing" })], next_cursor: null },
      },
    });
    const row = await screen.findByTestId("action-row");
    expect(row.textContent).toContain(TARGET);
    expect(within(row).getByTestId("state-badge").textContent).toBe("executing");
    const listCall = calls.find((c) => c.path === BASE);
    expect(listCall?.path).toBe(BASE);
  });

  it("shows the emergency-disable banner when execution is disabled", async () => {
    setup(`/actions?domain_id=${encodeURIComponent(DOMAIN)}`, {
      "GET /api/v1/actions/emergency-disable": {
        status: 200,
        body: {
          disabled: true,
          reason: "incident_response",
          changed_by: "p-admin",
          changed_at: "2026-10-20T09:00:00Z",
        },
      },
      [`GET ${BASE}`]: { status: 200, body: { items: [], next_cursor: null } },
    });
    const banner = await screen.findByTestId("emergency-banner");
    expect(banner.textContent).toContain("Action execution is disabled");
    expect(banner.textContent).toContain("incident_response");
  });

  it("shows a retryable state on 503, never an empty list", async () => {
    setup(`/actions?domain_id=${encodeURIComponent(DOMAIN)}`, {
      [`GET ${BASE}`]: problem(503, "dependency_transient"),
    });
    const state = await screen.findByTestId("unavailable-state");
    expect(within(state).getByRole("button", { name: "Retry" })).toBeTruthy();
    expect(screen.queryByTestId("empty-state")).toBeNull();
  });

  it("has no axe violations on the detail page", async () => {
    const { container } = setup(DETAIL_PATH, {
      [`GET ${BASE}/${INTENT_ID}`]: { status: 200, body: view() },
    });
    await screen.findByTestId("action-detail");
    const results = await axe(container);
    expect(results.violations.map((x) => `${x.id}: ${x.help}`)).toEqual([]);
  });
});

describe("propose model swap (button flow)", () => {
  it("drafts on the button channel, validates, confirms with the server hash", async () => {
    const drafted = view(
      {},
      { state: "drafted", confirmation_hash: null, confirmation_expires_at: null },
    );
    const validated = view(
      {},
      { state: "validated", confirmation_hash: null, confirmation_expires_at: null },
    );
    const awaiting = view();
    const executing = view({}, { state: "executing" });
    const { calls } = setup(`/actions/propose?domain_id=${encodeURIComponent(DOMAIN)}`, {
      [`POST ${BASE}`]: { status: 201, body: drafted },
      [`POST ${BASE}/${INTENT_ID}/validate`]: { status: 200, body: validated },
      [`POST ${BASE}/${INTENT_ID}/confirmation`]: { status: 200, body: awaiting },
      [`POST ${BASE}/${INTENT_ID}/confirm`]: { status: 200, body: executing },
    });
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Target model deployment (canonical id)"), TARGET);
    await user.type(screen.getByLabelText("Target version (ETag)"), "etag-7");
    await user.type(screen.getByLabelText("New model name"), "gpt-4.1-mini");
    await user.type(screen.getByLabelText("New model version (optional)"), "2026-04-14");
    await user.click(screen.getByRole("button", { name: "Draft model swap" }));

    await user.click(await screen.findByRole("button", { name: "Validate" }));
    await user.click(await screen.findByRole("button", { name: "Request confirmation" }));
    // The dialog opens by itself once the server issues the confirmation.
    const dialog = await screen.findByRole("alertdialog");
    expect(within(dialog).getByTestId("confirm-target").textContent).toBe(TARGET);
    await user.click(within(dialog).getByRole("button", { name: "Confirm and run" }));
    await waitFor(() => expect(screen.getByTestId("state-badge").textContent).toBe("executing"));

    const draft = calls.find((c) => c.method === "POST" && c.path === BASE);
    const body = draft?.body as Record<string, unknown>;
    expect(body["channel"]).toBe("button");
    expect(body["action_kind"]).toBe("model_deployment_swap");
    expect(body["target"]).toEqual({ canonical_id: TARGET, entity_type: "model_deployment" });
    expect(body["idempotency_key"]).toMatch(/^[A-Za-z0-9._:-]{16,128}$/);
    expect(JSON.stringify(body)).not.toContain("actor");
    // Same request as the fixture apart from the per-attempt idempotency key.
    const withoutKey = (o: Record<string, unknown>): Record<string, unknown> =>
      Object.fromEntries(Object.entries(o).filter(([k]) => k !== "idempotency_key"));
    expect(withoutKey(body)).toEqual(withoutKey(fixture));
    const confirm = calls.find((c) => c.path.endsWith("/confirm"));
    expect(confirm?.body).toEqual({ confirmation_hash: HASH });
  });
});
