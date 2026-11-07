import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { QueryProvider, createApiClient } from "../../api/index.js";
import { CapabilitiesPage } from "./CapabilitiesPage";
import { DeployPage } from "./DeployPage";
import { outcomeText } from "./ApplyStep";
import {
  applyPlanPath,
  approvePlanPath,
  capabilitiesPath,
  deployPlanPath,
  deployScanPath,
  uninstallPreviewPath,
} from "./paths";
import { STRINGS } from "./strings";
import { isEmailShaped } from "./validate";

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
  vi.restoreAllMocks();
});

const API = "http://api.test";
const guid = (tail: string): string => ["bbbbbbbb", "0000", "4000", "8000", tail].join("-");
const SUB_OK = guid("000000000001");
const SUB_HIDDEN = guid("000000000002");
const NOTE =
  "Results reflect only what the calling identity can read. A subscription reported " +
  "not_visible may still contain resources; absence of results is not absence of resources.";
const APIM_ID = `/subscriptions/${SUB_OK}/resourceGroups/rg-x/providers/Microsoft.ApiManagement/service/apim-x`;
const DISABLED_REASON = "Not verified for this Government region (verbatim reason text).";

let activeFetch: typeof fetch = () => Promise.reject(new Error("useApi() was not called"));

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

interface Seen {
  readonly urls: URL[];
  readonly bodies: unknown[];
}

/** Strict fake API: an unmatched request rejects, so the page cannot call anything unplanned. */
function useApi(handlers: Record<string, (url: URL, body: unknown) => Response>): Seen {
  const seen: Seen = { urls: [], bodies: [] };
  activeFetch = async (input, init) => {
    const raw = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    const url = new URL(raw);
    seen.urls.push(url);
    const body: unknown = typeof init?.body === "string" ? JSON.parse(init.body) : undefined;
    seen.bodies.push(body);
    const handler = handlers[url.pathname];
    if (handler === undefined) throw new Error(`unhandled request: ${url.pathname}`);
    return handler(url, body);
  };
  return seen;
}

function renderUi(ui: React.ReactElement, entry = "/") {
  const client = createApiClient({
    baseUrl: API,
    getToken: () => Promise.resolve("test-credential"),
    fetchImpl: (input, init) => activeFetch(input, init),
    maxRetries: 0,
  });
  return render(
    <QueryProvider client={client}>
      <MemoryRouter initialEntries={[entry]}>{ui}</MemoryRouter>
    </QueryProvider>,
  );
}

const SCAN = {
  visibility_limited: true,
  visibility_note: NOTE,
  consent_id: "consent-1",
  scanned_at: "2026-10-15T12:00:00Z",
  subscriptions: [
    {
      subscription_id: SUB_OK,
      status: "visible",
      resources: [
        {
          category: "apim",
          type: "Microsoft.ApiManagement/service",
          id: APIM_ID,
          name: "apim-x",
          location: "eastus",
          sku: "Standard",
          subscription_id: SUB_OK,
          tags: {},
        },
      ],
      note: null,
    },
    { subscription_id: SUB_HIDDEN, status: "not_visible", resources: [], note: "no access" },
  ],
};

function planItem(over: Record<string, unknown>) {
  return {
    service: "api_management",
    kind: "service",
    status: "reuse",
    existing_resource_id: APIM_ID,
    shared: true,
    neurosphere_created: false,
    checks: [{ name: "sku", outcome: "pass", reason: "SKU listed" }],
    notes: [],
    disabled_reason: null,
    source_url: null,
    cost_implication: { basis: "no_incremental_cost", summary: "Reuses an existing resource" },
    ...over,
  };
}

const PLAN = {
  plan: {
    plan_id: "plan-1",
    deployment_id: "deploy-1",
    items: [
      planItem({}),
      planItem({
        service: "model_endpoint",
        status: "disabled",
        existing_resource_id: null,
        shared: false,
        disabled_reason: DISABLED_REASON,
        source_url: "https://example.invalid/source",
        cost_implication: { basis: "unknown" },
      }),
      planItem({
        service: "key_vault",
        status: "reuse",
        shared: false,
        neurosphere_created: true,
        cost_implication: { basis: "estimated", monthly_amount: "42.00", currency: "USD" },
      }),
    ],
    capability_warnings: [],
    created_at: "2026-10-15T12:05:00Z",
  },
  manifest: { deployment_id: "deploy-1" },
};

function typeInto(label: RegExp, value: string): void {
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
}

function fillScanForm(attestation = "ticket-4711"): void {
  typeInto(/Subscription ids/, `${SUB_OK}\n${SUB_HIDDEN}`);
  typeInto(/Consent record id/, "consent-1");
  typeInto(/Attestation reference/, attestation);
}

describe("isEmailShaped", () => {
  it("flags anything with an at sign", () => {
    expect(isEmailShaped("someone@example.invalid")).toBe(true);
    expect(isEmailShaped("ticket-4711")).toBe(false);
  });
});

describe("DeployPage", () => {
  it("labels the attestation field and rejects an email-shaped value without calling the API", async () => {
    const seen = useApi({});
    renderUi(<DeployPage />);
    expect(screen.getByText(/pseudonymous id or ticket reference/i)).toBeTruthy();
    fillScanForm("someone@example.invalid");
    expect(await screen.findByText(STRINGS.attestationEmail)).toBeTruthy();
    fireEvent.click(screen.getByTestId("scan-run"));
    await waitFor(() =>
      expect(screen.getAllByText(STRINGS.attestationEmail).length).toBeGreaterThan(0),
    );
    expect(seen.urls).toHaveLength(0);
  });

  it("sends the consent record, shows the visibility note verbatim and keeps nothing in storage", async () => {
    const setItem = vi.spyOn(Storage.prototype, "setItem");
    const seen = useApi({ [deployScanPath()]: () => json(SCAN) });
    renderUi(<DeployPage />);
    fillScanForm();
    fireEvent.click(screen.getByTestId("scan-run"));
    const note = await screen.findByTestId("visibility-note");
    expect(note.textContent).toContain(NOTE);
    const subs = screen.getAllByTestId("scan-sub");
    expect(subs.map((s) => s.getAttribute("data-status"))).toEqual(["visible", "not_visible"]);
    expect(screen.getAllByTestId("scan-resource")).toHaveLength(1);
    expect(seen.bodies[0]).toEqual({
      consent: {
        consent_id: "consent-1",
        consented_by: "ticket-4711",
        consented_subscriptions: [SUB_OK, SUB_HIDDEN],
      },
      subscription_ids: [SUB_OK, SUB_HIDDEN],
    });
    expect(JSON.stringify(seen.bodies)).not.toMatch(/domain_id|customer_id/);
    expect(setItem).not.toHaveBeenCalled();
  });

  it("shows the visibility note on a scan with no visible subscription", async () => {
    useApi({
      [deployScanPath()]: () => json({ ...SCAN, subscriptions: [{ ...SCAN.subscriptions[1] }] }),
    });
    renderUi(<DeployPage />);
    fillScanForm();
    fireEvent.click(screen.getByTestId("scan-run"));
    expect((await screen.findByTestId("visibility-note")).textContent).toContain(NOTE);
    expect(screen.getByTestId("scan-no-resources")).toBeTruthy();
  });

  it("runs scan, choices and plan; shows badges, disabled reason and source; has no apply control", async () => {
    const createObjectURL = vi.fn(() => "blob:mock");
    const revokeObjectURL = vi.fn();
    Object.assign(URL, { createObjectURL, revokeObjectURL });
    const seen = useApi({
      [deployScanPath()]: () => json(SCAN),
      [deployPlanPath()]: () => json(PLAN),
    });
    renderUi(<DeployPage />);
    fillScanForm();
    fireEvent.click(screen.getByTestId("scan-run"));
    await screen.findByTestId("visibility-note");
    fireEvent.click(screen.getByTestId("step-next"));
    expect(screen.getByTestId("step-title").textContent).toBe(STRINGS.stepOf(2, "Choices"));

    // Choose reuse for API management with the discovered candidate.
    const row = screen
      .getAllByTestId("choice-row")
      .find((r) => r.getAttribute("data-service") === "api_management");
    if (row === undefined) throw new Error("no api_management row");
    fireEvent.click(within(row).getByRole("radio", { name: "reuse" }));
    fireEvent.click(within(row).getByRole("button", { name: STRINGS.useCandidate("apim-x") }));

    fireEvent.click(screen.getByTestId("step-next"));
    fireEvent.click(screen.getByTestId("plan-build"));
    const rows = await screen.findAllByTestId("plan-row");
    expect(rows).toHaveLength(3);
    expect(screen.getByText(DISABLED_REASON)).toBeTruthy();
    expect(screen.getByText(STRINGS.shared)).toBeTruthy();
    expect(screen.getByText(STRINGS.neurosphereCreated)).toBeTruthy();
    expect(screen.getByRole("link", { name: STRINGS.sourceLink }).getAttribute("href")).toBe(
      "https://example.invalid/source",
    );
    expect(screen.getByText(/no_incremental_cost/)).toBeTruthy();
    expect(screen.getByText(/estimated 42.00 USD\/month/)).toBeTruthy();
    expect(screen.getByText(/unknown: unknown/)).toBeTruthy();

    const planBody = seen.bodies[1] as {
      choices: Record<string, unknown>;
      profile: { cloud: string };
    };
    expect(planBody.choices).toEqual({
      api_management: {
        decision: "reuse",
        fallback: "create",
        resource_id: APIM_ID,
        sku: "Standard",
      },
    });
    expect(JSON.stringify(seen.bodies)).not.toMatch(/domain_id|customer_id/);

    const anchorClick = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    fireEvent.click(screen.getByTestId("manifest-download"));
    expect(anchorClick).toHaveBeenCalledTimes(1);
    expect(createObjectURL).toHaveBeenCalledTimes(1);

    // The plan is advisory: no control may apply, provision or delete anything.
    const forbidden = /apply|provision|delete|execute|deploy now/i;
    for (const b of screen.getAllByRole("button")) {
      expect(b.textContent ?? "").not.toMatch(forbidden);
    }
  });

  it("switching to Government replaces the regions; no Commercial region stays selectable", async () => {
    useApi({ [deployScanPath()]: () => json(SCAN) });
    renderUi(<DeployPage />);
    fillScanForm();
    fireEvent.click(screen.getByTestId("scan-run"));
    await screen.findByTestId("visibility-note");
    fireEvent.click(screen.getByTestId("step-next"));
    expect(screen.getByRole("radio", { name: "eastus" })).toBeTruthy();
    fireEvent.click(screen.getByRole("radio", { name: "government" }));
    expect(screen.queryByRole("radio", { name: "eastus" })).toBeNull();
    expect(screen.getByRole("radio", { name: "usgovvirginia" })).toBeTruthy();
  });
});

const DOMAIN = "commercial:contoso:catalog:domain:finance";
const DOMAIN_ENTRY = `/?domain_id=${encodeURIComponent(DOMAIN)}`;
const PLAN_ID = `plan-${"a1b2c3d4".repeat(4)}`;
const PLAN_HASH = `sha256:${"0123456789abcdef".repeat(4)}`;
const DIGEST = `sha256:${"fedcba9876543210".repeat(4)}`;
const SUB_TARGET = guid("000000000099");
const CONSENT_REASON = "Reusing a shared resource needs a granted owner consent.";

function problem(status: number, code: string, reason: string, title: string): Response {
  return json({ code, reason, title, correlation_id: "corr-1", retryable: false }, status);
}

const APPLY_PLAN = {
  ...PLAN,
  plan: {
    ...PLAN.plan,
    plan_id: PLAN_ID,
    profile: {
      cloud: "commercial",
      regions: ["eastus"],
      hosting: "aks",
      analytics: "fabric",
      features: [],
      allow_preview: false,
    },
    consents: [],
  },
};

const APPROVED = {
  plan_id: PLAN_ID,
  plan_hash: PLAN_HASH,
  resources_digest: DIGEST,
  deployment_id: "deploy-1",
  cloud: "commercial",
  resources: [
    {
      service: "key_vault",
      kind: "arm_resource",
      disposition: "reuse",
      name: "kv-ns",
      region: "eastus",
      sku: null,
      resource_id: "/subscriptions/x/vaults/kv-ns",
    },
    {
      service: "storage",
      kind: "arm_resource",
      disposition: "create",
      name: "ns-storage",
      region: "eastus",
      sku: "Standard",
      resource_id: null,
    },
  ],
  approved_at: "2026-10-15T12:08:00Z",
  expires_at: "2026-10-15T13:08:00Z",
};

function actionView(over: { state?: string; execution?: unknown; reason?: string | null } = {}) {
  return {
    intent: {
      intent_id: "11111111-2222-4333-8444-555555555555",
      action_kind: "deploy_plan_apply",
      target: { canonical_id: "commercial:contoso:deploy:plan", entity_type: "deployment" },
      target_version: PLAN_HASH,
      proposed_diff: {
        format: "json_patch",
        operations: [{ op: "add", path: "/resources/0", value: { service: "storage" } }],
      },
      state: over.state ?? "drafted",
      status_reason: over.reason ?? null,
      dry_run: false,
    },
    advisory: false,
    requires_approval: true,
    self_approval_forbidden: true,
    review_item_id: null,
    execution: over.execution ?? null,
  };
}

const APPLIED = { plan_id: PLAN_ID, plan_hash: PLAN_HASH, resources: [], action: actionView() };

/** Scan -> choices -> plan, then to step 4. */
async function reachApplyStep(): Promise<void> {
  fillScanForm();
  fireEvent.click(screen.getByTestId("scan-run"));
  await screen.findByTestId("visibility-note");
  fireEvent.click(screen.getByTestId("step-next"));
  fireEvent.click(screen.getByTestId("step-next"));
  fireEvent.click(screen.getByTestId("plan-build"));
  await screen.findAllByTestId("plan-row");
  fireEvent.click(screen.getByTestId("step-next"));
}

function fillTarget(): void {
  typeInto(/Subscription id(?!s)/, SUB_TARGET);
  typeInto(/Resource group/, "rg-ns");
  typeInto(/Fabric capacity SKU/, "F2");
}

function baseHandlers(extra: Record<string, (url: URL, body: unknown) => Response>) {
  return {
    [deployScanPath()]: () => json(SCAN),
    [deployPlanPath()]: () => json(APPLY_PLAN),
    ...extra,
  };
}

describe("outcomeText", () => {
  it("claims applied only for a succeeded intent whose verification matched", () => {
    const base = actionView({ state: "succeeded" });
    expect(
      outcomeText({
        ...base,
        execution: { phase: "done", canary: null, verify_matched: true, rolled_back: false },
      } as never).applied,
    ).toBe(true);
    expect(outcomeText({ ...base, execution: null } as never).applied).toBe(false);
    expect(
      outcomeText({
        ...base,
        execution: { phase: "done", canary: null, verify_matched: false, rolled_back: false },
      } as never).applied,
    ).toBe(false);
    expect(outcomeText(actionView({ state: "drafted" }) as never).applied).toBe(false);
    expect(
      outcomeText(actionView({ state: "failed", reason: "stale_version" }) as never).text,
    ).toContain("stale_version");
  });
});

describe("DeployPage step 4: approve, apply, uninstall preview", () => {
  it("needs a plan and a domain before offering anything", async () => {
    useApi({});
    renderUi(<DeployPage />);
    expect(screen.getByTestId("apply-domain-required")).toBeTruthy();
    cleanup();
    renderUi(<DeployPage />, DOMAIN_ENTRY);
    expect(screen.getByTestId("apply-plan-required")).toBeTruthy();
    // The uninstall preview stays available without a plan.
    expect(screen.getByTestId("uninstall-run")).toBeTruthy();
  });

  it("lists disabled and consent-pending items with their reasons and blocks approval", async () => {
    const waiting = {
      ...APPLY_PLAN,
      plan: {
        ...APPLY_PLAN.plan,
        items: [
          ...APPLY_PLAN.plan.items,
          planItem({
            service: "storage",
            status: "needs_consent",
            disabled_reason: CONSENT_REASON,
          }),
        ],
      },
    };
    const seen = useApi({
      [deployScanPath()]: () => json(SCAN),
      [deployPlanPath()]: () => json(waiting),
    });
    renderUi(<DeployPage />, DOMAIN_ENTRY);
    await reachApplyStep();
    const items = screen.getAllByTestId("apply-blocked-item");
    expect(items.map((i) => i.getAttribute("data-status")).sort()).toEqual([
      "disabled",
      "needs_consent",
    ]);
    const blockedList = screen.getByTestId("apply-blocked");
    expect(blockedList.textContent).toContain(DISABLED_REASON);
    expect(blockedList.textContent).toContain(CONSENT_REASON);
    const approve = screen.getByTestId("approve-run") as HTMLButtonElement;
    expect(approve.disabled).toBe(true);
    expect(screen.getByTestId("approve-blocked")).toBeTruthy();
    fireEvent.click(approve);
    expect(seen.urls.map((u) => u.pathname)).not.toContain(approvePlanPath(DOMAIN));
  });

  it("validates the target before calling the API", async () => {
    const seen = useApi(baseHandlers({}));
    renderUi(<DeployPage />, DOMAIN_ENTRY);
    await reachApplyStep();
    const calls = seen.urls.length;
    fireEvent.click(screen.getByTestId("approve-run"));
    expect(await screen.findByText(STRINGS.invalidSubscriptionId)).toBeTruthy();
    expect(seen.urls.length).toBe(calls);
  });

  it("shows the approval from the API, drafts the apply and never calls a draft applied", async () => {
    const seen = useApi(
      baseHandlers({
        [approvePlanPath(DOMAIN)]: () => json(APPROVED, 201),
        [applyPlanPath(DOMAIN)]: () => json(APPLIED, 201),
      }),
    );
    renderUi(<DeployPage />, DOMAIN_ENTRY);
    await reachApplyStep();
    expect(screen.getByTestId("approval-status").textContent).toBe(STRINGS.notApproved);
    expect((screen.getByTestId("apply-run") as HTMLButtonElement).disabled).toBe(true);

    fillTarget();
    fireEvent.click(screen.getByTestId("approve-run"));
    await waitFor(() =>
      expect(screen.getByTestId("approval-status").textContent).toBe(STRINGS.approvedStatus),
    );
    const state = screen.getByTestId("approval-state");
    expect(state.textContent).toContain(PLAN_HASH);
    expect(state.textContent).toContain(DIGEST);
    expect(state.textContent).toContain(SUB_TARGET);
    const resources = screen.getAllByTestId("approved-resource");
    expect(resources.map((r) => r.getAttribute("data-disposition"))).toEqual(["reuse", "create"]);

    const approveBody = seen.bodies.at(-1) as {
      plan: { plan_id: string };
      target: Record<string, string>;
    };
    expect(approveBody.plan.plan_id).toBe(PLAN_ID);
    expect(approveBody.target).toEqual({
      subscription_id: SUB_TARGET,
      resource_group: "rg-ns",
      region: "eastus",
      capacity_sku: "F2",
    });
    expect(seen.urls.at(-1)?.pathname).toBe(approvePlanPath(DOMAIN));
    expect(JSON.stringify(seen.bodies)).not.toMatch(/domain_id|customer_id/);

    fireEvent.click(screen.getByTestId("apply-run"));
    const result = await screen.findByTestId("apply-result");
    expect(seen.bodies.at(-1)).toMatchObject({
      plan_id: PLAN_ID,
      plan_hash: PLAN_HASH,
      channel: "button",
    });
    expect(seen.urls.at(-1)?.pathname).toBe(applyPlanPath(DOMAIN));
    expect(result.textContent).toContain(PLAN_HASH);
    expect(result.textContent).toContain("commercial:contoso:deploy:plan");
    expect(screen.getByTestId("apply-diff").textContent).toContain("add /resources/0");
    const outcome = screen.getByTestId("apply-outcome");
    expect(outcome.getAttribute("data-applied")).toBe("false");
    expect(outcome.textContent).toMatch(/Not applied/);
    expect(screen.queryByText(STRINGS.outcomeApplied)).toBeNull();
  });

  it("shows applied only when the executor state says succeeded and verified", async () => {
    const done = {
      ...APPLIED,
      action: actionView({
        state: "succeeded",
        execution: { phase: "done", canary: null, verify_matched: true, rolled_back: false },
      }),
    };
    useApi(
      baseHandlers({
        [approvePlanPath(DOMAIN)]: () => json(APPROVED, 201),
        [applyPlanPath(DOMAIN)]: () => json(done, 201),
      }),
    );
    renderUi(<DeployPage />, DOMAIN_ENTRY);
    await reachApplyStep();
    fillTarget();
    fireEvent.click(screen.getByTestId("approve-run"));
    await waitFor(() =>
      expect((screen.getByTestId("apply-run") as HTMLButtonElement).disabled).toBe(false),
    );
    fireEvent.click(screen.getByTestId("apply-run"));
    const outcome = await screen.findByTestId("apply-outcome");
    expect(outcome.getAttribute("data-applied")).toBe("true");
    expect(outcome.textContent).toBe(STRINGS.outcomeApplied);
  });

  it("shows a refused apply with the API reason and no success", async () => {
    useApi(
      baseHandlers({
        [approvePlanPath(DOMAIN)]: () => json(APPROVED, 201),
        [applyPlanPath(DOMAIN)]: () =>
          problem(403, "forbidden", "plan_not_approved", "The plan is not approved"),
      }),
    );
    renderUi(<DeployPage />, DOMAIN_ENTRY);
    await reachApplyStep();
    fillTarget();
    fireEvent.click(screen.getByTestId("approve-run"));
    await waitFor(() =>
      expect((screen.getByTestId("apply-run") as HTMLButtonElement).disabled).toBe(false),
    );
    fireEvent.click(screen.getByTestId("apply-run"));
    const denied = await screen.findByTestId("apply-forbidden");
    expect(denied.textContent).toContain("plan_not_approved");
    expect(denied.textContent).toContain("corr-1");
    expect(screen.queryByTestId("apply-result")).toBeNull();
    expect(screen.queryByTestId("apply-outcome")).toBeNull();
  });

  it("shows a changed plan hash refusal", async () => {
    useApi(
      baseHandlers({
        [approvePlanPath(DOMAIN)]: () => json(APPROVED, 201),
        [applyPlanPath(DOMAIN)]: () =>
          problem(422, "invalid_schema", "plan_hash_mismatch", "The plan changed"),
      }),
    );
    renderUi(<DeployPage />, DOMAIN_ENTRY);
    await reachApplyStep();
    fillTarget();
    fireEvent.click(screen.getByTestId("approve-run"));
    await waitFor(() =>
      expect((screen.getByTestId("apply-run") as HTMLButtonElement).disabled).toBe(false),
    );
    fireEvent.click(screen.getByTestId("apply-run"));
    const refused = await screen.findByTestId("apply-error");
    expect(refused.textContent).toContain("plan_hash_mismatch");
  });

  it("shows 503 apply_not_configured as not enabled in this deployment", async () => {
    useApi(
      baseHandlers({
        [approvePlanPath(DOMAIN)]: () =>
          problem(503, "dependency_transient", "apply_not_configured", "Apply is not configured."),
      }),
    );
    renderUi(<DeployPage />, DOMAIN_ENTRY);
    await reachApplyStep();
    fillTarget();
    fireEvent.click(screen.getByTestId("approve-run"));
    const off = await screen.findByTestId("apply-not-enabled");
    expect(off.textContent).toContain(STRINGS.notEnabledTitle);
    expect(screen.getByTestId("approval-status").textContent).toBe(STRINGS.notApproved);
    expect(screen.queryByTestId("approve-error")).toBeNull();
  });

  it("shows a 403 as a denial; the UI grants nothing", async () => {
    useApi(
      baseHandlers({
        [approvePlanPath(DOMAIN)]: () =>
          problem(403, "forbidden", "insufficient_permission", "config.manage is required"),
      }),
    );
    renderUi(<DeployPage />, DOMAIN_ENTRY);
    await reachApplyStep();
    fillTarget();
    fireEvent.click(screen.getByTestId("approve-run"));
    const denied = await screen.findByTestId("apply-forbidden");
    expect(denied.textContent).toContain("insufficient_permission");
    expect(screen.getByTestId("approval-status").textContent).toBe(STRINGS.notApproved);
  });

  it("previews an uninstall: reused and shared stay untouched and nothing can be deleted", async () => {
    const entry = (over: Record<string, unknown>) => ({
      resource_id: "/subscriptions/x/r",
      service: "storage",
      ownership: "created",
      reason: "r",
      ...over,
    });
    const view = {
      deployment_id: "deploy-1",
      dry_run: true,
      register_digest: DIGEST,
      removable: [entry({ resource_id: "/subscriptions/x/created", reason: "Created by us" })],
      untouched: [
        entry({ resource_id: "/subscriptions/x/reused", ownership: "reused", reason: "Reused" }),
        entry({ resource_id: "/subscriptions/x/shared", ownership: "shared", reason: "Shared" }),
      ],
      action: actionView(),
    };
    const seen = useApi({ [uninstallPreviewPath(DOMAIN)]: () => json(view, 201) });
    renderUi(<DeployPage />, DOMAIN_ENTRY);
    expect(screen.getByText(STRINGS.uninstallTitle)).toBeTruthy();
    typeInto(/Deployment id to preview/, "deploy-1");
    fireEvent.click(screen.getByTestId("uninstall-run"));
    const result = await screen.findByTestId("uninstall-result");
    expect(seen.bodies[0]).toMatchObject({
      deployment_id: "deploy-1",
      channel: "button",
      verify_live: false,
    });
    expect(JSON.stringify(seen.bodies[0])).not.toMatch(/dry_run/);
    expect(result.textContent).toContain(STRINGS.uninstallDryRun);
    expect(screen.getAllByTestId("uninstall-removable")).toHaveLength(1);
    const untouched = screen.getAllByTestId("uninstall-untouched");
    expect(untouched.map((r) => r.getAttribute("data-ownership"))).toEqual(["reused", "shared"]);
    // No control may delete or remove anything.
    for (const b of within(screen.getByTestId("uninstall")).getAllByRole("button", {
      hidden: true,
    })) {
      expect(b.textContent ?? "").not.toMatch(/delete|remove|destroy|uninstall now/i);
    }
  });

  it("shows apply_not_configured for the uninstall preview too", async () => {
    useApi({
      [uninstallPreviewPath(DOMAIN)]: () =>
        problem(503, "dependency_transient", "apply_not_configured", "Apply is not configured."),
    });
    renderUi(<DeployPage />, DOMAIN_ENTRY);
    typeInto(/Deployment id to preview/, "deploy-1");
    fireEvent.click(screen.getByTestId("uninstall-run"));
    expect(await screen.findByTestId("apply-not-enabled")).toBeTruthy();
    expect(screen.queryByTestId("uninstall-result")).toBeNull();
  });
});

const CAP_ROWS = [
  {
    id: "ai_search.base.government.usgovvirginia.any",
    service: "ai_search",
    feature: "base",
    cloud: "government",
    region: "usgovvirginia",
    sku: null,
    availability: "available",
    ga_status: "ga",
    authorization_scope: "none_claimed",
    source_url: "https://example.invalid/a",
    observed_on: "2026-09-21",
    notes: null,
  },
  {
    id: "foundry.model.government.usgovvirginia.any",
    service: "foundry",
    feature: "model",
    cloud: "government",
    region: "usgovvirginia",
    sku: null,
    availability: "unverified",
    ga_status: "unverified",
    authorization_scope: "none_claimed",
    source_url: "https://example.invalid/b",
    observed_on: "2026-09-21",
    notes: "The source does not say.",
  },
  {
    id: "fabric.base.commercial.eastus.any",
    service: "fabric",
    feature: "base",
    cloud: "commercial",
    region: "eastus",
    sku: null,
    availability: "available",
    ga_status: "ga",
    authorization_scope: "none_claimed",
    source_url: "https://example.invalid/c",
    observed_on: "2026-09-21",
    notes: null,
  },
];

describe("CapabilitiesPage", () => {
  it("shows availability, GA status and scope separately; unverified rows are disabled with a reason", async () => {
    const seen = useApi({
      [capabilitiesPath()]: () =>
        json({
          matrix_version: "sha256:abc",
          observed_at: "2026-09-21",
          items: CAP_ROWS.slice(0, 2),
        }),
    });
    renderUi(<CapabilitiesPage />);
    fireEvent.click(screen.getByRole("radio", { name: "government" }));
    fireEvent.click(screen.getByTestId("cap-apply"));
    const rows = await screen.findAllByTestId("cap-row");
    expect(rows).toHaveLength(2);
    const header = screen.getAllByRole("columnheader").map((h) => h.textContent);
    expect(header).toEqual(
      expect.arrayContaining(["Availability", "GA status", STRINGS.capColumns.scope]),
    );
    const states = rows.map((r) => r.getAttribute("data-enabled"));
    expect(states).toEqual(["true", "false"]);
    expect(seen.urls[0]?.searchParams.get("cloud")).toBe("commercial");
    expect(seen.urls.at(-1)?.searchParams.get("cloud")).toBe("government");
  });

  it("marks only an available row of the selected cloud as enabled", async () => {
    useApi({
      [capabilitiesPath()]: (url) =>
        json({
          matrix_version: "sha256:abc",
          observed_at: "2026-09-21",
          items: url.searchParams.get("cloud") === "government" ? CAP_ROWS.slice(0, 2) : [],
        }),
    });
    renderUi(<CapabilitiesPage />);
    await screen.findByTestId("cap-empty");
    fireEvent.click(screen.getByRole("radio", { name: "government" }));
    fireEvent.click(screen.getByTestId("cap-apply"));
    const rows = await screen.findAllByTestId("cap-row");
    expect(rows.map((r) => r.getAttribute("data-enabled"))).toEqual(["true", "false"]);
    expect(screen.getByText(/Availability is unverified. The source does not say./)).toBeTruthy();
  });

  it("never shows a Commercial-only row for a Government filter, even if the API returned one", async () => {
    useApi({
      [capabilitiesPath()]: () =>
        json({ matrix_version: "sha256:abc", observed_at: "2026-09-21", items: CAP_ROWS }),
    });
    renderUi(<CapabilitiesPage />);
    fireEvent.click(screen.getByRole("radio", { name: "government" }));
    fireEvent.click(screen.getByTestId("cap-apply"));
    await waitFor(() => {
      const ids = screen.queryAllByTestId("cap-row").map((r) => r.textContent ?? "");
      expect(ids.length).toBe(2);
      expect(ids.some((t) => t.includes("fabric"))).toBe(false);
    });
  });

  it("rejects a malformed region without calling the API again", async () => {
    const seen = useApi({
      [capabilitiesPath()]: () =>
        json({ matrix_version: "sha256:abc", observed_at: "2026-09-21", items: [] }),
    });
    renderUi(<CapabilitiesPage />);
    await screen.findByTestId("cap-empty");
    const calls = seen.urls.length;
    fireEvent.change(screen.getByLabelText(/Region/), { target: { value: "East US!" } });
    expect(screen.getByText(STRINGS.capRegionInvalid)).toBeTruthy();
    fireEvent.click(screen.getByTestId("cap-apply"));
    expect(seen.urls.length).toBe(calls);
  });
});
