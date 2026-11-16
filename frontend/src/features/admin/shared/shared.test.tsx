import { renderHook, waitFor, cleanup, screen } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it } from "vitest";
import { StaleVersionError } from "../../../api/index.js";
import { QueryProvider, createApiClient } from "../../../api/index.js";
import { ADMIN_AREAS } from "./areas";
import { AdminConsoleHome } from "./AdminConsoleHome";
import { changeErrorText } from "./AdminStates";
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
