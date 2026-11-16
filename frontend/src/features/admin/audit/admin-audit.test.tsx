import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { auditPaths } from "../shared/adminPaths";
import {
  fakeFetch,
  problem,
  renderAdmin,
  stubResizeObserver,
  type FakeHandler,
} from "../shared/test-support";
import { AdminAuditPage } from "./AdminAuditPage";
import { filterQuery, rangeProblem, type AuditRecordView } from "./hooks";

beforeAll(stubResizeObserver);
beforeEach(() => {
  URL.createObjectURL = vi.fn(() => "blob:test");
  URL.revokeObjectURL = vi.fn();
});
afterEach(cleanup);

function record(i: number, kind: AuditRecordView["kind"] = "after"): AuditRecordView {
  return {
    audit_id: `00000000-0000-4000-8000-${String(i).padStart(12, "0")}`,
    chain_id: "e2e.finance",
    sequence: i,
    kind,
    recorded_at: "2026-10-20T10:00:00.000000Z",
    actor: { principal_pseudonym: `psn-mock-${i}`, principal_kind: "user" },
    correlation_id: `corr-${i}`,
    operation: kind === "denied" ? "graph.query" : "action.execute",
    outcome: kind === "after" ? { result: "succeeded", verified: true } : null,
    denial: kind === "denied" ? { code: "forbidden", reason: "domain_out_of_scope" } : null,
  };
}

const SIEM = {
  sink: "eventhubs",
  state: "ok",
  reason: null,
  consecutive_failures: 2,
  last_success_at: "2026-11-02T07:59:00Z",
  last_failure_reason: "sink_timeout",
};

function routes(extra: FakeHandler = () => undefined) {
  return fakeFetch((req) => {
    const out = extra(req);
    if (out !== undefined) return out;
    const path = req.url.pathname;
    if (path === auditPaths.siem()) return { body: SIEM };
    if (path === auditPaths.denials()) {
      return { body: { items: [record(9, "denied")], next_cursor: null } };
    }
    if (path === auditPaths.search()) {
      const first = req.url.searchParams.get("cursor") === null;
      return {
        body: {
          items: [
            {
              domain_id: first ? "commercial:e2e:catalog:domain:finance" : "dom-2",
              record: record(first ? 1 : 2),
            },
          ],
          domains: [],
          next_cursor: first ? "c2" : null,
        },
      };
    }
    return undefined;
  });
}

describe("AdminAuditPage", () => {
  it("searches with a required capped range and pages by the server cursor", async () => {
    const { impl, calls } = routes();
    renderAdmin(<AdminAuditPage />, impl);
    expect(await screen.findAllByTestId("audit-row")).toHaveLength(1);
    const first = calls.find((c) => c.url.pathname === auditPaths.search());
    expect(first?.url.searchParams.get("since")).toMatch(/Z$/);
    expect(first?.url.searchParams.get("until")).toMatch(/Z$/);
    expect(first?.url.searchParams.get("page_size")).toBe("25");
    await userEvent.click(screen.getByRole("button", { name: "Next page" }));
    await waitFor(() => expect(screen.getByText("psn-mock-2")).toBeTruthy());
    expect(calls.at(-1)?.url.searchParams.get("cursor")).toBe("c2");
    expect(screen.queryByRole("button", { name: "Next page" })).toBeNull();
  });

  it("sends each filter under its API query name and blocks a range over 31 days", async () => {
    const { impl, calls } = routes();
    renderAdmin(<AdminAuditPage />, impl);
    await screen.findAllByTestId("audit-row");
    await userEvent.type(
      screen.getByLabelText("Domain id"),
      "commercial:e2e:catalog:domain:finance",
    );
    await userEvent.type(screen.getByLabelText("Operation"), "action.execute");
    await userEvent.selectOptions(screen.getByLabelText("Kind"), "denied");
    await userEvent.selectOptions(screen.getByLabelText("Outcome"), "failed");
    await userEvent.type(screen.getByLabelText("Actor pseudonym"), "psn-mock-1");
    await userEvent.type(screen.getByLabelText("Correlation id"), "corr-1");
    await userEvent.click(screen.getByRole("button", { name: "Search" }));
    await waitFor(() => {
      const q = calls.filter((c) => c.url.pathname === auditPaths.search()).at(-1)
        ?.url.searchParams;
      expect(q?.get("domain")).toBe("commercial:e2e:catalog:domain:finance");
      expect(q?.get("operation")).toBe("action.execute");
      expect(q?.get("kind")).toBe("denied");
      expect(q?.get("outcome")).toBe("failed");
      expect(q?.get("actor")).toBe("psn-mock-1");
      expect(q?.get("correlation_id")).toBe("corr-1");
    });
    fireEvent.change(screen.getByLabelText(/From/), { target: { value: "2020-01-01T00:00" } });
    expect(screen.getByText("The time range is capped at 31 days.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Search" }).hasAttribute("disabled")).toBe(true);
  });

  it("shows the denials tab and the SIEM status", async () => {
    const { impl, calls } = routes();
    renderAdmin(<AdminAuditPage />, impl);
    await screen.findByTestId("siem-status");
    expect(screen.getByTestId("siem-failures").textContent).toBe("2");
    expect(screen.getByTestId("siem-status").textContent).toContain("sink_timeout");
    await userEvent.click(screen.getByRole("tab", { name: "Denials" }));
    expect(await screen.findByText("forbidden: domain_out_of_scope")).toBeTruthy();
    expect(calls.some((c) => c.url.pathname === auditPaths.denials())).toBe(true);
  });

  it("shows an unknown failure count as unknown, not 0", async () => {
    const { impl } = routes((req) =>
      req.url.pathname === auditPaths.siem()
        ? { body: { sink: "none", state: "disabled" } }
        : undefined,
    );
    renderAdmin(<AdminAuditPage />, impl);
    await screen.findByTestId("siem-status");
    expect(screen.getByTestId("siem-failures").textContent).toBe("unknown");
    expect(screen.getByText("Never")).toBeTruthy();
  });

  it("exports through the bearer-token client with format and filters, never a token in the URL", async () => {
    const { impl, calls } = routes((req) =>
      req.url.pathname === auditPaths.export()
        ? {
            raw: "domain_id,sequence\n",
            headers: {
              "content-type": "text/csv",
              "Content-Disposition": 'attachment; filename="audit-export.csv"',
              "X-NeuroSphere-Export-Rows": "31",
              "X-NeuroSphere-Export-Truncated": "true",
            },
          }
        : undefined,
    );
    renderAdmin(<AdminAuditPage />, impl);
    expect(screen.getByTestId("export-cap").textContent).toContain("10,000");
    expect(screen.getByTestId("export-notice")).toBeTruthy();
    await userEvent.click(await screen.findByRole("button", { name: "Export CSV" }));
    await screen.findByTestId("export-done");
    expect(screen.getByTestId("export-done").textContent).toBe(
      "Downloaded audit-export.csv with 31 rows.",
    );
    expect(screen.getByTestId("export-truncated")).toBeTruthy();
    const call = calls.find((c) => c.url.pathname === auditPaths.export());
    expect(call?.url.searchParams.get("format")).toBe("csv");
    expect(call?.url.searchParams.get("since")).toMatch(/Z$/);
    expect(call?.url.toString()).not.toContain("test-token");
    expect(call?.headers.get("Authorization")).toBe("Bearer test-token");
    expect(URL.createObjectURL).toHaveBeenCalled();
  });

  it("disables export with an explanation when the API answers 403", async () => {
    const { impl } = routes((req) =>
      req.url.pathname === auditPaths.export()
        ? problem(403, "forbidden", "permission_missing")
        : undefined,
    );
    renderAdmin(<AdminAuditPage />, impl);
    await userEvent.click(await screen.findByRole("button", { name: "Export NDJSON" }));
    await screen.findByTestId("export-forbidden");
    expect(screen.getByRole("button", { name: "Export NDJSON" }).hasAttribute("disabled")).toBe(
      true,
    );
    expect(screen.getByRole("button", { name: "Export CSV" }).hasAttribute("disabled")).toBe(true);
    // Search still works.
    expect(screen.getAllByTestId("audit-row").length).toBeGreaterThan(0);
  });

  it("shows the API's 422 text for a bad export range", async () => {
    const { impl } = routes((req) =>
      req.url.pathname === auditPaths.export()
        ? problem(422, "invalid_schema", "the time range is capped at 31 days")
        : undefined,
    );
    renderAdmin(<AdminAuditPage />, impl);
    await userEvent.click(await screen.findByRole("button", { name: "Export NDJSON" }));
    expect((await screen.findByTestId("export-error")).textContent).toContain(
      "the time range is capped at 31 days",
    );
  });

  it("renders empty, forbidden and error states for the results", async () => {
    renderAdmin(
      <AdminAuditPage />,
      routes((req) =>
        req.url.pathname === auditPaths.search()
          ? { body: { items: [], domains: [], next_cursor: null } }
          : undefined,
      ).impl,
    );
    await screen.findByTestId("empty-state");
    cleanup();
    renderAdmin(
      <AdminAuditPage />,
      routes((req) =>
        req.url.pathname === auditPaths.search() ? problem(403, "forbidden", "x") : undefined,
      ).impl,
    );
    await screen.findByTestId("forbidden-state");
    cleanup();
    renderAdmin(
      <AdminAuditPage />,
      routes((req) =>
        req.url.pathname === auditPaths.search()
          ? problem(503, "dependency_transient", "down")
          : undefined,
      ).impl,
    );
    await screen.findByTestId("unavailable-state");
  });
});

describe("filter helpers", () => {
  it("omits empty filters and validates the range", () => {
    expect(
      filterQuery({
        since: "a",
        until: "b",
        domain: " d ",
        operation: "",
        kind: "",
        outcome: "",
        actor: "",
        correlationId: "c",
      }),
    ).toEqual({ since: "a", until: "b", domain: "d", correlation_id: "c" });
    expect(rangeProblem("2026-10-01T00:00", "2026-10-02T00:00")).toBeUndefined();
    expect(rangeProblem("2026-10-02T00:00", "2026-10-01T00:00")).toContain("after");
    expect(rangeProblem("", "")).toContain("Choose");
    expect(rangeProblem("2026-01-01T00:00", "2026-12-01T00:00")).toContain("31 days");
  });
});
