import type { AccountInfo, IPublicClientApplication } from "@azure/msal-browser";
import { MsalProvider } from "@azure/msal-react";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { QueryProvider, createApiClient } from "../../api/index.js";
import { createStubMsalInstance } from "../../../tests/e2e-support/stubMsal";
import { CompliancePage } from "./CompliancePage";
import { ControlDetailPage } from "./ControlDetailPage";
import { countText, type EvidenceBundle, type Observation } from "./data";
import { STRINGS } from "./strings";

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
const DOMAIN = "commercial:test:catalog:domain:finance";
const FRAMEWORK = "nist_ai_rmf";
const SOURCE = "https://airc.nist.gov/airmf-resources/airmf/5-sec-core/";

const obs = (over: Partial<Observation> = {}): Observation => ({
  source_id: "catalog_ownership",
  status: "observed",
  reason_code: null,
  window_start: "2026-10-17T00:00:00Z",
  window_end: "2026-11-16T00:00:00Z",
  latest_at: "2026-11-10T09:30:00Z",
  truncated: false,
  measures: [{ name: "records", value: 4 }],
  ...over,
});

function control(id: string, summary: string, support: string, sources: string[]) {
  return {
    control: {
      control_id: id,
      framework_id: FRAMEWORK,
      title: `Title of ${id}`,
      source_url: SOURCE,
      source_retrieved: "2026-11-16",
      framework_version: "1.0",
    },
    support_status: support,
    evidence_sources: sources,
    summary,
  };
}

function bundle(over: Partial<EvidenceBundle> = {}): EvidenceBundle {
  return {
    framework_id: FRAMEWORK,
    framework_version: "1.0",
    library_version: "1.0.0",
    domain_id: DOMAIN,
    generated_at: "2026-11-16T00:00:00Z",
    window_start: "2026-10-17T00:00:00Z",
    window_end: "2026-11-16T00:00:00Z",
    controls: [
      control("nist-ai-rmf.govern-2", "evidence_present", "implemented_tested", [
        "catalog_ownership",
      ]),
      control("nist-ai-rmf.map-3", "evidence_partial", "implemented_tested", ["cost_attribution"]),
      control("nist-ai-rmf.govern-3", "customer_responsibility", "customer", []),
    ] as unknown as EvidenceBundle["controls"],
    observations: [
      obs(),
      obs({
        source_id: "cost_attribution",
        status: "not_collected",
        reason_code: "cost_center_absent",
        latest_at: null,
        measures: [{ name: "records", value: null }],
      }),
    ],
    digest: `sha256:${"a".repeat(64)}`,
    ...over,
  };
}

function account(): AccountInfo {
  return {
    homeAccountId: "home-compliance",
    environment: "login.example.invalid",
    tenantId: "test-tenant",
    username: "someone@example.invalid",
    localAccountId: "local",
    name: "Test User",
    idTokenClaims: { roles: ["Auditor"] },
  };
}

function msal(): IPublicClientApplication {
  const acc = account();
  const base = createStubMsalInstance() as unknown as Record<string, unknown>;
  return {
    ...base,
    getAllAccounts: () => [acc],
    getActiveAccount: () => acc,
  } as unknown as IPublicClientApplication;
}

const json = (b: unknown, status = 200): Response =>
  new Response(JSON.stringify(b), {
    status,
    headers: { "content-type": status === 200 ? "application/json" : "application/problem+json" },
  });

const problem = (status: number, reason: string): Response =>
  json({ code: status === 403 ? "forbidden" : "dependency_transient", reason, status }, status);

const DOMAINS = {
  items: [{ domain_id: DOMAIN, display_name: "Finance", display_name_source: "catalog" }],
};
const FRAMEWORKS = {
  library_version: "1.0.0",
  frameworks: [
    {
      framework_id: FRAMEWORK,
      title: "NIST AI Risk Management Framework",
      framework_version: "1.0",
      source_url: SOURCE,
      source_retrieved: "2026-11-16",
      control_count: 3,
    },
  ],
};

let activeFetch: typeof fetch = () => Promise.reject(new Error("useApi() was not called"));
const seen: URL[] = [];

/** Strict fake API: the audit domain list, the frameworks and one bundle; anything else rejects. */
function useApi(answer: { bundle?: () => Response; frameworks?: () => Response } = {}): void {
  seen.length = 0;
  activeFetch = (input) => {
    const url = new URL(typeof input === "string" ? input : (input as Request).url);
    seen.push(url);
    if (url.pathname === "/api/v1/audit/domains") return Promise.resolve(json(DOMAINS));
    if (url.pathname === "/api/v1/compliance/frameworks") {
      return Promise.resolve(answer.frameworks?.() ?? json(FRAMEWORKS));
    }
    if (url.pathname === `/api/v1/compliance/domains/${encodeURIComponent(DOMAIN)}/bundle`) {
      return Promise.resolve(answer.bundle?.() ?? json(bundle()));
    }
    return Promise.reject(new Error(`unexpected ${url.pathname}`));
  };
}

function renderAt(element: React.ReactElement, path: string) {
  const client = createApiClient({
    baseUrl: API,
    getToken: () => Promise.resolve("test-credential"),
    fetchImpl: (input, init) => activeFetch(input, init),
    maxRetries: 0,
  });
  return render(
    <MsalProvider instance={msal()}>
      <QueryProvider client={client}>
        <MemoryRouter initialEntries={[path]}>{element}</MemoryRouter>
      </QueryProvider>
    </MsalProvider>,
  );
}

const PAGE = `/compliance?compliance_domain=${encodeURIComponent(DOMAIN)}&framework=${FRAMEWORK}`;

describe("strings", () => {
  const CLAIM = /\b(compliant|certified|passed|failed|supported|covered|coverage|score)\b|\d\s?%/i;

  function flatten(node: unknown): string[] {
    if (typeof node === "string") return [node];
    if (typeof node === "object" && node !== null) return Object.values(node).flatMap(flatten);
    return [];
  }

  it("carries no affirmative claim word and no percentage", () => {
    for (const text of flatten(STRINGS)) expect(text).not.toMatch(CLAIM);
  });

  it("never says authorized except negated by the disclaimer", () => {
    const hits = flatten(STRINGS).filter((t) => /authori[sz]ed/i.test(t));
    expect(hits).toEqual([STRINGS.disclaimer]);
    expect(STRINGS.disclaimer).toMatch(/^Not FedRAMP authorized; the authorizing official decides/);
  });
});

describe("countText", () => {
  it("renders unknown as the word, never 0", () => {
    expect(countText(null, "unknown")).toBe("unknown");
    expect(countText(0, "unknown")).toBe("0");
  });
});

describe("CompliancePage", () => {
  it("lists mapped controls with support status and evidence summary", async () => {
    useApi();
    renderAt(<CompliancePage />, PAGE);
    const row = await screen.findByTestId("control-nist-ai-rmf.govern-2");
    expect(within(row).getByText("implemented and tested")).toBeTruthy();
    expect(within(row).getByText("evidence present")).toBeTruthy();
    expect(
      within(screen.getByTestId("control-nist-ai-rmf.map-3")).getByText("evidence partial"),
    ).toBeTruthy();
    expect(
      within(screen.getByTestId("control-nist-ai-rmf.govern-3")).getByText(
        "customer responsibility",
      ),
    ).toBeTruthy();
    expect(screen.getByTestId("disclaimer").textContent).toBe(STRINGS.disclaimer);
    expect(screen.getByTestId("bundle-digest").textContent).toContain("sha256:");
    // The page asks only for the framework; the customer comes from the server scope.
    const bundleCall = seen.find((u) => u.pathname.endsWith("/bundle"));
    expect([...(bundleCall?.searchParams.keys() ?? [])]).toEqual(["framework_id"]);
  });

  it("shows unknown observation counts as the word unknown", async () => {
    useApi();
    renderAt(<CompliancePage />, PAGE);
    const row = await screen.findByTestId("observation-cost_attribution");
    expect(within(row).getAllByText("unknown").length).toBeGreaterThanOrEqual(1);
    expect(within(row).getByText("not collected")).toBeTruthy();
  });

  it("downloads the bundle through a blob, with no token in a URL", async () => {
    useApi();
    const create = vi.fn(() => "blob:test");
    vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: create, revokeObjectURL: vi.fn() }));
    renderAt(<CompliancePage />, PAGE);
    fireEvent.click(await screen.findByRole("button", { name: STRINGS.download }));
    await waitFor(() => expect(create).toHaveBeenCalledTimes(1));
    expect(seen.every((u) => !u.href.includes("test-credential"))).toBe(true);
  });

  it("shows the forbidden state on a 403", async () => {
    useApi({ bundle: () => problem(403, "permission_missing") });
    renderAt(<CompliancePage />, PAGE);
    expect(await screen.findByTestId("forbidden-state")).toBeTruthy();
  });

  it("shows an error state with retry on a 503", async () => {
    useApi({ bundle: () => problem(503, "compliance_library_unavailable") });
    renderAt(<CompliancePage />, PAGE);
    const state = await screen.findByTestId("error-state");
    expect(within(state).getByRole("button", { name: /try again/i })).toBeTruthy();
  });

  it("shows an empty state when the bundle has no controls", async () => {
    useApi({ bundle: () => json(bundle({ controls: [], observations: [] })) });
    renderAt(<CompliancePage />, PAGE);
    expect(await screen.findByTestId("empty-state")).toBeTruthy();
  });

  it("shows the domain-unavailable state when no domain is readable", async () => {
    useApi();
    const base = activeFetch;
    activeFetch = (input, init) => {
      const url = new URL(typeof input === "string" ? input : (input as Request).url);
      return url.pathname === "/api/v1/audit/domains"
        ? Promise.resolve(json({ items: [] }))
        : base(input, init);
    };
    renderAt(<CompliancePage />, "/compliance");
    expect(await screen.findByTestId("compliance-domain-unavailable")).toBeTruthy();
  });
});

describe("ControlDetailPage", () => {
  const DETAIL = `/compliance/control?compliance_domain=${encodeURIComponent(DOMAIN)}&framework=${FRAMEWORK}&control=`;

  it("shows the source link and the observations behind the control", async () => {
    useApi();
    renderAt(<ControlDetailPage />, `${DETAIL}nist-ai-rmf.govern-2`);
    const detail = await screen.findByTestId("control-detail");
    const link = within(detail).getByRole("link", { name: SOURCE });
    expect(link.getAttribute("href")).toBe(SOURCE);
    expect(link.getAttribute("rel")).toContain("noopener");
    expect(within(detail).getByTestId("observation-catalog_ownership")).toBeTruthy();
  });

  it("explains a customer responsibility control and lists no source", async () => {
    useApi();
    renderAt(<ControlDetailPage />, `${DETAIL}nist-ai-rmf.govern-3`);
    expect(await screen.findByTestId("customer-note")).toBeTruthy();
    expect(screen.getByTestId("no-sources")).toBeTruthy();
  });

  it("says so when the control is not in the bundle", async () => {
    useApi();
    renderAt(<ControlDetailPage />, `${DETAIL}nist-ai-rmf.nope`);
    expect(await screen.findByTestId("control-missing")).toBeTruthy();
  });

  it("shows the forbidden state on a 403", async () => {
    useApi({ bundle: () => problem(403, "permission_missing") });
    renderAt(<ControlDetailPage />, `${DETAIL}nist-ai-rmf.govern-2`);
    expect(await screen.findByTestId("forbidden-state")).toBeTruthy();
  });
});
