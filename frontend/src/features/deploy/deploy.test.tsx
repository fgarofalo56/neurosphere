import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { QueryProvider, createApiClient } from "../../api/index.js";
import { CapabilitiesPage } from "./CapabilitiesPage";
import { DeployPage } from "./DeployPage";
import { capabilitiesPath, deployPlanPath, deployScanPath } from "./paths";
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

function renderUi(ui: React.ReactElement) {
  const client = createApiClient({
    baseUrl: API,
    getToken: () => Promise.resolve("test-credential"),
    fetchImpl: (input, init) => activeFetch(input, init),
    maxRetries: 0,
  });
  return render(
    <QueryProvider client={client}>
      <MemoryRouter>{ui}</MemoryRouter>
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
