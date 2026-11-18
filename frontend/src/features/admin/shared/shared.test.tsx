import type { ProblemDetails } from "@neurosphere/contracts";
import { renderHook, waitFor, cleanup, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, describe, expect, it } from "vitest";
import { axe } from "vitest-axe";
import { DependencyTransientError, ForbiddenError, StaleVersionError } from "../../../api/index.js";
import { QueryProvider, createApiClient } from "../../../api/index.js";
import { ME_ACCESS_PATH } from "../identity/hooks";
import { ADMIN_AREAS } from "./areas";
import { AdminConsoleHome } from "./AdminConsoleHome";
import { QueryErrorState, changeErrorText } from "./AdminStates";
import { ADMIN_STRINGS } from "./strings";
import { fakeFetch, problem, renderAdmin, stubResizeObserver } from "./test-support";
import { AdminTransportProvider, adminDownload, useEtagMutation } from "./transport";
import { identityPaths, principalHref } from "./adminPaths";

beforeAll(stubResizeObserver);
afterEach(cleanup);

describe("useEtagMutation", () => {
  function wrapperFor(fetchImpl: typeof fetch) {
    const getToken = (): Promise<string> => Promise.resolve("t");
    const client = createApiClient({
      baseUrl: "http://api.test",
      getToken,
      fetchImpl,
      maxRetries: 0,
    });
    return ({ children }: { children: React.ReactNode }) => (
      <QueryProvider client={client}>
        <AdminTransportProvider transport={{ baseUrl: "http://api.test", getToken, fetchImpl }}>
          {children}
        </AdminTransportProvider>
      </QueryProvider>
    );
  }

  it("sends If-Match verbatim and returns the new ETag", async () => {
    const { impl, calls } = fakeFetch(() => ({ body: { ok: true }, headers: { ETag: '"v2"' } }));
    const { result } = renderHook(
      () =>
        useEtagMutation<{ etag: string }, { ok: boolean }>((v) => ({
          method: "PUT",
          path: identityPaths.role("psn-a", "r1"),
          body: { reason: "x" },
          ifMatch: v.etag,
        })),
      { wrapper: wrapperFor(impl) },
    );
    result.current.mutate({ etag: '"v1"' });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(calls[0]?.headers.get("If-Match")).toBe('"v1"');
    expect(calls[0]?.headers.get("Authorization")).toBe("Bearer t");
    expect(result.current.data?.etag).toBe('"v2"');
  });

  it("maps 409 to a stale-version error with reload guidance and does not retry", async () => {
    const { impl, calls } = fakeFetch(() => problem(409, "stale_version", "etag_mismatch"));
    const { result } = renderHook(
      () => useEtagMutation<null, unknown>(() => ({ method: "PUT", path: "/x", ifMatch: '"old"' })),
      { wrapper: wrapperFor(impl) },
    );
    result.current.mutate(null);
    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error).toBeInstanceOf(StaleVersionError);
    expect(changeErrorText(result.current.error as StaleVersionError)).toContain(
      ADMIN_STRINGS.stale,
    );
    expect(calls).toHaveLength(1);
  });
});

describe("QueryErrorState", () => {
  function forbiddenError(detail: string | undefined, reason: string): ForbiddenError {
    const body = problem(403, "forbidden", reason).body as Record<string, unknown>;
    return new ForbiddenError({
      status: 403,
      retryable: false,
      correlationId: "corr-test",
      problem: { ...body, detail } as unknown as ProblemDetails,
    });
  }
  const ACCESS = {
    mapping_configured: true,
    groups_overage: false,
    roles: [
      {
        role: "viewer",
        source: "policy_store",
        mapping_entry_id: null,
        domain_count: 1,
        customer_control: false,
        expires_at: null,
      },
      {
        role: "admin",
        source: "entra_app_role",
        mapping_entry_id: "ns-admins",
        domain_count: 4,
        customer_control: true,
        expires_at: "2026-11-18T15:00:00Z",
      },
    ],
  };

  it("names the permission and says when it is needed on the whole deployment", () => {
    const { impl } = fakeFetch(() => undefined);
    renderAdmin(
      <QueryErrorState
        error={forbiddenError(
          "this change applies to the whole deployment and needs deployment-scoped policy.manage",
          "customer_scope_required",
        )}
      />,
      impl,
    );
    const state = screen.getByTestId("forbidden-state");
    expect(state.textContent).toContain(ADMIN_STRINGS.forbidden);
    expect(screen.getByTestId("forbidden-detail").textContent).toContain("policy.manage");
    expect(screen.getByTestId("forbidden-scope").textContent).toBe(
      ADMIN_STRINGS.forbiddenDeployment,
    );
    expect(state.textContent).toContain("(Reference corr-test)");
    expect(screen.queryByTestId("forbidden-access-link")).toBeNull();
  });

  it("says a domain-level permission is not deployment-wide and links an access anchor", () => {
    const { impl } = fakeFetch(() => undefined);
    renderAdmin(
      <QueryErrorState
        error={forbiddenError("this operation needs `audit.read`", "insufficient_scope")}
        accessAnchor="my-access"
      />,
      impl,
    );
    expect(screen.getByTestId("forbidden-detail").textContent).toBe(
      "this operation needs `audit.read`. ",
    );
    expect(screen.getByTestId("forbidden-scope").textContent).toBe(ADMIN_STRINGS.forbiddenDomain);
    expect(screen.getByTestId("forbidden-access-link").getAttribute("href")).toBe("#my-access");
  });

  it("keeps the old text when the problem has no detail", () => {
    const { impl } = fakeFetch(() => undefined);
    renderAdmin(<QueryErrorState error={forbiddenError(undefined, "x")} />, impl);
    expect(screen.queryByTestId("forbidden-detail")).toBeNull();
    expect(screen.getByTestId("forbidden-state").textContent).toContain(
      ADMIN_STRINGS.forbiddenDetail,
    );
  });

  it("loads the caller's own access only when the disclosure is opened", async () => {
    const { impl, calls } = fakeFetch((req) =>
      req.url.pathname === ME_ACCESS_PATH ? { body: ACCESS } : undefined,
    );
    const { container } = renderAdmin(
      <QueryErrorState error={forbiddenError("this operation needs `policy.manage`", "x")} />,
      impl,
    );
    const toggle = screen.getByRole("button", { name: "Your access", hidden: true });
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    expect(calls).toHaveLength(0);
    await userEvent.click(toggle);
    expect(toggle.getAttribute("aria-expanded")).toBe("true");
    const items = await screen.findAllByTestId("access-disclosure-role");
    expect(calls.map((c) => c.url.pathname)).toEqual([ME_ACCESS_PATH]);
    expect(items.map((i) => i.textContent)).toEqual([
      "viewer, Policy store, 1 domain, no expiry",
      "admin, Entra app role, mapping entry ns-admins, 4 domains, Whole deployment, expires 2026-11-18T15:00:00Z",
    ]);
    expect(screen.queryByTestId("access-disclosure-overage")).toBeNull();
    const violations = (await axe(container)).violations.map((v) => `${v.id}: ${v.help}`);
    expect(violations).toEqual([]);
  });

  it("shows no roles, the overage notice and a read failure in the disclosure", async () => {
    const empty = fakeFetch(() => ({ body: { ...ACCESS, roles: [], groups_overage: true } }));
    renderAdmin(<QueryErrorState error={forbiddenError("d", "x")} />, empty.impl);
    await userEvent.click(screen.getByRole("button", { name: "Your access", hidden: true }));
    expect((await screen.findByTestId("access-disclosure-none")).textContent).toBe(
      ADMIN_STRINGS.access.none,
    );
    expect(screen.getByTestId("access-disclosure-overage").textContent).toBe(
      ADMIN_STRINGS.access.overage,
    );
    cleanup();
    const down = fakeFetch(() => problem(503, "dependency_transient", "down"));
    renderAdmin(<QueryErrorState error={forbiddenError("d", "x")} />, down.impl);
    await userEvent.click(screen.getByRole("button", { name: "Your access", hidden: true }));
    await screen.findByTestId("access-disclosure-error");
  });

  it("keeps the retryable outage state without a disclosure", async () => {
    const { impl } = fakeFetch(() => undefined);
    let retried = 0;
    const err = new DependencyTransientError({
      status: 503,
      retryable: true,
      correlationId: "",
    });
    renderAdmin(<QueryErrorState error={err} onRetry={() => (retried += 1)} />, impl);
    expect(screen.getByTestId("unavailable-state").textContent).toContain(
      ADMIN_STRINGS.unavailableDetail,
    );
    expect(screen.queryByTestId("access-disclosure")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: ADMIN_STRINGS.retry, hidden: true }));
    expect(retried).toBe(1);
  });
});

describe("adminDownload", () => {
  it("keeps the token in the header, never the URL, and reads the row headers", async () => {
    const { impl, calls } = fakeFetch(() => ({
      raw: "a,b\n",
      headers: {
        "Content-Disposition": 'attachment; filename="audit-export.csv"',
        "X-NeuroSphere-Export-Rows": "12",
        "X-NeuroSphere-Export-Truncated": "true",
      },
    }));
    const out = await adminDownload(
      {
        baseUrl: "http://api.test",
        getToken: () => Promise.resolve("secret-token"),
        fetchImpl: impl,
      },
      { path: "/api/v1/audit/export", query: { format: "csv" } },
      "fallback.csv",
    );
    expect(out.filename).toBe("audit-export.csv");
    expect(out.rows).toBe(12);
    expect(out.truncated).toBe(true);
    expect(calls[0]?.url.toString()).not.toContain("secret-token");
    expect(calls[0]?.headers.get("Authorization")).toBe("Bearer secret-token");
  });
});

describe("registries", () => {
  it("lists each area once and builds the principal link from a query parameter", () => {
    expect(new Set(ADMIN_AREAS.map((a) => a.id)).size).toBe(ADMIN_AREAS.length);
    expect(principalHref("psn-a b")).toBe("/admin/identity/principal?principal_id=psn-a+b");
  });
});

describe("AdminConsoleHome", () => {
  it("shows the checklist and restart summaries from the API", async () => {
    const { impl } = fakeFetch((req) => {
      if (req.url.pathname.endsWith("/checklist")) {
        return {
          body: {
            items: [
              {
                item_id: "a",
                component: "c",
                status: "complete",
                reason: null,
                doc_path: null,
                required: true,
              },
              {
                item_id: "b",
                component: "c",
                status: "missing",
                reason: "x",
                doc_path: null,
                required: true,
              },
              {
                item_id: "c",
                component: "c",
                status: "not_applicable",
                reason: null,
                doc_path: null,
                required: false,
              },
            ],
          },
        };
      }
      if (req.url.pathname.endsWith("/settings")) {
        return {
          body: {
            items: [
              { key: "k1", source: "stored", restart_required: true },
              { key: "k2", source: "env", restart_required: false },
            ],
            stored_settings: { status: "loaded", reason: null, invalid_keys: [] },
          },
        };
      }
      return undefined;
    });
    renderAdmin(<AdminConsoleHome title="Admin workspace" />, impl);
    await waitFor(() =>
      expect(screen.getByTestId("checklist-summary").textContent).toBe(
        "1 of 2 checklist items complete",
      ),
    );
    expect(screen.getByTestId("restart-summary").textContent).toBe("1 setting needs a restart");
  });

  it("shows unknown when the status routes fail", async () => {
    const { impl } = fakeFetch(() => problem(503, "dependency_transient", "down"));
    renderAdmin(<AdminConsoleHome title="Admin workspace" />, impl);
    await waitFor(() =>
      expect(screen.getByTestId("checklist-summary").textContent).toBe(
        ADMIN_STRINGS.summaryUnknown,
      ),
    );
    expect(screen.getByTestId("restart-summary").textContent).toBe(ADMIN_STRINGS.summaryUnknown);
  });
});
