import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider, type RouteObject } from "react-router";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { QueryProvider, createApiClient } from "../../api/index.js";
import {
  SaveReportDialog,
  buildSaveReportRequest,
  reportViewHref,
  reportsNavItems,
  reportsRoutes,
} from "./index";
import { reportPath, reportRunPath, reportSharesPath, reportsPath } from "./paths";
import { STRINGS } from "./strings";
import type { ChartPlan, ReportListResponse, ReportView, RunView, StructuredQuery } from "./types";

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

const DOMAIN = "commercial:contoso:catalog:domain:finance";
const REPORT_ID = "rpt-0001";
const BOB = "commercial:contoso:entra:person:psn_bob0000000000001";
const ETAG = '"etag-1"';

const PLAN = {
  schema_version: "1.0.0",
  citations: [{ evidence_id: "ev:agents", as_of: "2026-10-10T11:58:00Z" }],
  spec: {
    title: "Agent versions",
    data: { values: [{ display_name: "Agent fin-1", version: 3 }] },
    mark: "bar",
    encoding: {
      x: { field: "display_name", type: "nominal" },
      y: { field: "version", type: "quantitative" },
    },
  },
} as ChartPlan;

const QUERY = {
  schema_version: "1.0.0",
  operation: "list",
  entity: "agent",
  budget: { timeout_ms: 2000, limit: 20, max_depth: 0 },
} as StructuredQuery;

function report(over: Partial<ReportView> = {}): ReportView {
  return {
    id: REPORT_ID,
    domain_id: DOMAIN,
    owner: "commercial:contoso:entra:person:psn_alice000000000001",
    title: "Agents by version",
    chart_plan: PLAN,
    query_spec: QUERY,
    metric: "cost",
    shares: [],
    publication: {
      state: "none",
      requested_by: null,
      requested_at: null,
      decided_by: null,
      decided_at: null,
      reason: null,
    },
    created_at: "2026-10-21T12:00:00Z",
    updated_at: "2026-10-21T12:00:00Z",
    etag: ETAG,
    is_owner: true,
    can_decide_publication: false,
    ...over,
  };
}

function run(over: Partial<RunView> = {}): RunView {
  return {
    report_id: REPORT_ID,
    status: "ok",
    chart_plan: PLAN,
    citations: [
      {
        record_id: "commercial:contoso:foundry:agent:fin-1",
        kind: "agent",
        source: "catalog",
        as_of: "2026-10-21T08:00:00Z",
        freshness: "fresh",
      },
    ],
    truncated: false,
    ran_at: "2026-10-21T12:30:00Z",
    etag: ETAG,
    ...over,
  };
}

interface Reply {
  status: number;
  body: unknown;
}
type Routes = Record<string, Reply | (() => Reply)>;

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
  search: string;
  body: unknown;
  ifMatch: string | null;
}

function setup(path: string, routes: Routes, extraRoutes: RouteObject[] = []) {
  const calls: Call[] = [];
  const fetchImpl = vi.fn<typeof fetch>((input, init) => {
    const url = new URL(String(input));
    const method = init?.method ?? "GET";
    const body = typeof init?.body === "string" ? (JSON.parse(init.body) as unknown) : undefined;
    const headers = new Headers(init?.headers);
    calls.push({
      method,
      path: url.pathname,
      search: url.search,
      body,
      ifMatch: headers.get("If-Match"),
    });
    const route = routes[`${method} ${url.pathname}`];
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
  const router = createMemoryRouter([...reportsRoutes, ...extraRoutes], {
    initialEntries: [path],
  });
  render(
    <QueryProvider client={client}>
      <RouterProvider router={router} />
    </QueryProvider>,
  );
  return { calls, fetchImpl };
}

const LIST_PATH = `/reports?domain_id=${encodeURIComponent(DOMAIN)}`;
const VIEW_PATH = reportViewHref(DOMAIN, REPORT_ID);
const LIST_API = reportsPath(DOMAIN);
const ITEM_API = reportPath(DOMAIN, REPORT_ID);
const RUN_API = reportRunPath(DOMAIN, REPORT_ID);

function viewRoutes(r: ReportView, runReply: Reply = { status: 200, body: run() }): Routes {
  return {
    [`GET ${ITEM_API}`]: { status: 200, body: r },
    [`POST ${RUN_API}`]: runReply,
  };
}

describe("exports", () => {
  it("exports routes and nav items without wiring them into the app", () => {
    expect(reportsRoutes.map((r) => r.path)).toEqual(["reports", "reports/view"]);
    expect(reportsNavItems()).toEqual([{ to: "/reports", label: "Reports" }]);
  });
});

describe("report list", () => {
  it("asks for a domain before fetching", () => {
    const { fetchImpl } = setup("/reports", {});
    expect(screen.getByTestId("domain-required")).toBeTruthy();
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("lists reports with their publication state and ownership", async () => {
    const list: ReportListResponse = {
      items: [
        report(),
        report({
          id: "rpt-0002",
          title: "Shared with me",
          is_owner: false,
          publication: { ...report().publication, state: "approved" },
        }),
      ],
      next_cursor: null,
    };
    setup(LIST_PATH, { [`GET ${LIST_API}`]: { status: 200, body: list } });
    const rows = await screen.findAllByTestId("report-row");
    expect(rows).toHaveLength(2);
    expect(within(rows[0]!).getByText("Agents by version")).toBeTruthy();
    expect(within(rows[0]!).getByText(new RegExp(STRINGS.youAreOwner))).toBeTruthy();
    expect(within(rows[1]!).getByText(STRINGS.publication.approved)).toBeTruthy();
    const link = within(rows[1]!).getByRole("link", { name: "Shared with me" });
    expect(link.getAttribute("href")).toBe(reportViewHref(DOMAIN, "rpt-0002"));
  });

  it("shows the empty state and follows the next-page cursor", async () => {
    const user = userEvent.setup();
    let served = 0;
    const { calls } = setup(LIST_PATH, {
      [`GET ${LIST_API}`]: () => {
        served += 1;
        const body: ReportListResponse =
          served === 1
            ? { items: [report()], next_cursor: "rp1.abc" }
            : { items: [], next_cursor: null };
        return { status: 200, body };
      },
    });
    await screen.findAllByTestId("report-row");
    await user.click(screen.getByRole("button", { name: STRINGS.nextPage }));
    expect(await screen.findByTestId("empty-state")).toBeTruthy();
    expect(calls[1]?.search).toContain("cursor=rp1.abc");
  });

  it("requests only pending reports when the reviewer filter is chosen", async () => {
    const { calls } = setup(`${LIST_PATH}&publication=pending`, {
      [`GET ${LIST_API}`]: { status: 200, body: { items: [], next_cursor: null } },
    });
    await screen.findByTestId("empty-state");
    expect(calls[0]?.search).toContain("publication_state=pending");
  });

  it("shows 403 as an access message, not an empty list", async () => {
    setup(LIST_PATH, { [`GET ${LIST_API}`]: problem(403, "forbidden") });
    expect(await screen.findByTestId("forbidden-state")).toBeTruthy();
    expect(screen.queryByTestId("empty-state")).toBeNull();
  });

  it("shows an outage as unavailable, not an empty list", async () => {
    setup(LIST_PATH, { [`GET ${LIST_API}`]: problem(503, "dependency_transient") });
    expect(await screen.findByTestId("unavailable-state")).toBeTruthy();
    expect(screen.queryByTestId("empty-state")).toBeNull();
  });
});

describe("report view", () => {
  it("runs the report and renders the chart with its citations and freshness", async () => {
    const { calls } = setup(VIEW_PATH, viewRoutes(report()));
    expect(await screen.findByTestId("chart-frame")).toBeTruthy();
    expect(document.querySelector("iframe")?.getAttribute("title")).toBe("Agents by version");
    const citation = await screen.findByTestId("citation");
    expect(citation.textContent).toContain("fresh");
    expect(citation.textContent).toContain("2026-10-21T08:00:00Z");
    expect(calls.filter((c) => c.method === "POST" && c.path === RUN_API)).toHaveLength(1);
    // The run request carries no body: scope and identity come from the bearer token.
    expect(calls.find((c) => c.path === RUN_API)?.body).toBeUndefined();
  });

  it("explains an empty result for this viewer instead of drawing an empty chart", async () => {
    setup(
      VIEW_PATH,
      viewRoutes(report({ is_owner: false }), {
        status: 200,
        body: run({ status: "no_data", chart_plan: null, citations: [] }),
      }),
    );
    expect(await screen.findByTestId("no-data-state")).toBeTruthy();
    expect(screen.queryByTestId("chart-frame")).toBeNull();
  });

  it("notes when a server limit truncated the data", async () => {
    setup(VIEW_PATH, viewRoutes(report(), { status: 200, body: run({ truncated: true }) }));
    expect(await screen.findByTestId("truncated")).toBeTruthy();
  });

  it("shows owner controls only to the owner", async () => {
    setup(VIEW_PATH, viewRoutes(report({ is_owner: false })));
    await screen.findByTestId("run-section");
    expect(screen.queryByTestId("share-open")).toBeNull();
    expect(screen.queryByTestId("request-publication")).toBeNull();
    expect(screen.queryByTestId("delete-report")).toBeNull();
  });

  it("shows 404 as not found", async () => {
    setup(VIEW_PATH, { [`GET ${ITEM_API}`]: { status: 404, body: { status: 404 } } });
    expect(await screen.findByTestId("not-found-state")).toBeTruthy();
  });

  it("shows 403 on the report as an access message", async () => {
    setup(VIEW_PATH, { [`GET ${ITEM_API}`]: problem(403, "forbidden") });
    expect(await screen.findByTestId("forbidden-state")).toBeTruthy();
  });

  it("shows a revoked run (403) as an access message and draws no chart", async () => {
    setup(VIEW_PATH, viewRoutes(report({ is_owner: false }), problem(403, "forbidden")));
    expect(await screen.findByTestId("forbidden-state")).toBeTruthy();
    expect(screen.queryByTestId("chart-frame")).toBeNull();
  });

  it("shows a run refused for an invalid stored plan (422) and draws no chart", async () => {
    setup(VIEW_PATH, viewRoutes(report(), problem(422, "invalid_schema")));
    expect(await screen.findByTestId("invalid-plan-state")).toBeTruthy();
    expect(screen.queryByTestId("chart-frame")).toBeNull();
  });

  it("re-runs on demand", async () => {
    const user = userEvent.setup();
    const { calls } = setup(VIEW_PATH, viewRoutes(report()));
    await screen.findByTestId("run-section");
    await user.click(screen.getByRole("button", { name: STRINGS.run }));
    await waitFor(() =>
      expect(calls.filter((c) => c.method === "POST" && c.path === RUN_API)).toHaveLength(2),
    );
  });
});

describe("sharing", () => {
  it("shares with a principal and lists current shares", async () => {
    const user = userEvent.setup();
    const { calls } = setup(VIEW_PATH, {
      ...viewRoutes(report({ shares: [BOB] })),
      [`POST ${reportSharesPath(DOMAIN, REPORT_ID)}`]: {
        status: 200,
        body: report({ shares: [BOB] }),
      },
    });
    await user.click(await screen.findByTestId("share-open"));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByTestId("share-list").textContent).toContain(BOB);
    await user.type(within(dialog).getByLabelText(STRINGS.share.principalLabel), BOB);
    await user.click(within(dialog).getByRole("button", { name: STRINGS.share.add }));
    await waitFor(() => expect(calls.some((c) => c.path.endsWith("/shares"))).toBe(true));
    expect(calls.find((c) => c.path.endsWith("/shares"))?.body).toEqual({ principal_id: BOB });
  });

  it("removes a share", async () => {
    const user = userEvent.setup();
    const { calls } = setup(VIEW_PATH, {
      ...viewRoutes(report({ shares: [BOB] })),
      [`DELETE ${reportSharesPath(DOMAIN, REPORT_ID)}/${encodeURIComponent(BOB)}`]: {
        status: 200,
        body: report(),
      },
    });
    await user.click(await screen.findByTestId("share-open"));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: STRINGS.share.remove }));
    await waitFor(() => expect(calls.some((c) => c.method === "DELETE")).toBe(true));
  });

  it("explains a refused share (403 not_owner) and changes nothing", async () => {
    const user = userEvent.setup();
    setup(VIEW_PATH, {
      ...viewRoutes(report()),
      [`POST ${reportSharesPath(DOMAIN, REPORT_ID)}`]: problem(403, "forbidden", "not_owner"),
    });
    await user.click(await screen.findByTestId("share-open"));
    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByLabelText(STRINGS.share.principalLabel), BOB);
    await user.click(within(dialog).getByRole("button", { name: STRINGS.share.add }));
    expect((await within(dialog).findByTestId("mutation-error")).textContent).toContain(
      STRINGS.errors.notOwner,
    );
  });
});

describe("publication", () => {
  const PUBLICATION_API = `${ITEM_API}/publication`;
  const DECISION_API = `${PUBLICATION_API}/decision`;
  const pending = {
    ...report().publication,
    state: "pending" as const,
    requested_by: "commercial:contoso:entra:person:psn_alice000000000001",
  };

  it("lets the owner request add-to-UI", async () => {
    const user = userEvent.setup();
    const { calls } = setup(VIEW_PATH, {
      ...viewRoutes(report()),
      [`POST ${PUBLICATION_API}`]: { status: 200, body: report({ publication: pending }) },
    });
    await user.click(await screen.findByTestId("request-publication"));
    expect(await screen.findByTestId("publication-requested")).toBeTruthy();
    expect(calls.find((c) => c.path === PUBLICATION_API)?.body).toBeUndefined();
  });

  it("hides the request control while a request is pending", async () => {
    setup(VIEW_PATH, viewRoutes(report({ publication: pending })));
    await screen.findByTestId("run-section");
    expect(screen.queryByTestId("request-publication")).toBeNull();
    expect(screen.getAllByText(STRINGS.publication.pending).length).toBeGreaterThan(0);
  });

  it("hides the approve control from the owner", async () => {
    setup(VIEW_PATH, viewRoutes(report({ publication: pending, can_decide_publication: false })));
    await screen.findByTestId("run-section");
    expect(screen.queryByTestId("decision-controls")).toBeNull();
    expect(screen.queryByRole("button", { name: STRINGS.publish.approve })).toBeNull();
  });

  it("shows approve and reject to a reviewer and sends the decision", async () => {
    const user = userEvent.setup();
    const reviewerView = report({
      is_owner: false,
      publication: pending,
      can_decide_publication: true,
    });
    const { calls } = setup(VIEW_PATH, {
      [`GET ${ITEM_API}`]: { status: 200, body: reviewerView },
      [`POST ${DECISION_API}`]: {
        status: 200,
        body: { ...reviewerView, publication: { ...pending, state: "approved" } },
      },
    });
    await screen.findByTestId("decision-controls");
    // A reviewer reads the definition but does not run a pending report.
    expect(calls.some((c) => c.path === RUN_API)).toBe(false);
    await user.type(screen.getByLabelText(STRINGS.publish.reasonLabel), "looks good");
    await user.click(screen.getByRole("button", { name: STRINGS.publish.approve }));
    expect(await screen.findByTestId("decision-recorded")).toBeTruthy();
    expect(calls.find((c) => c.path === DECISION_API)?.body).toEqual({
      decision: "approve",
      reason: "looks good",
    });
  });

  it("sends a rejection without an empty reason", async () => {
    const user = userEvent.setup();
    const reviewerView = report({
      is_owner: false,
      publication: pending,
      can_decide_publication: true,
    });
    const { calls } = setup(VIEW_PATH, {
      [`GET ${ITEM_API}`]: { status: 200, body: reviewerView },
      [`POST ${DECISION_API}`]: { status: 200, body: reviewerView },
    });
    await user.click(await screen.findByRole("button", { name: STRINGS.publish.reject }));
    await waitFor(() => expect(calls.some((c) => c.path === DECISION_API)).toBe(true));
    expect(calls.find((c) => c.path === DECISION_API)?.body).toEqual({ decision: "reject" });
  });

  it("explains a refused self-approval from the server", async () => {
    const user = userEvent.setup();
    const reviewerView = report({
      is_owner: false,
      publication: pending,
      can_decide_publication: true,
    });
    setup(VIEW_PATH, {
      [`GET ${ITEM_API}`]: { status: 200, body: reviewerView },
      [`POST ${DECISION_API}`]: problem(403, "forbidden", "self_approval_refused"),
    });
    await user.click(await screen.findByRole("button", { name: STRINGS.publish.approve }));
    expect((await screen.findByTestId("mutation-error")).textContent).toContain(
      STRINGS.errors.selfApproval,
    );
  });

  it("explains a stale decision (409)", async () => {
    const user = userEvent.setup();
    const reviewerView = report({
      is_owner: false,
      publication: pending,
      can_decide_publication: true,
    });
    setup(VIEW_PATH, {
      [`GET ${ITEM_API}`]: { status: 200, body: reviewerView },
      [`POST ${DECISION_API}`]: problem(409, "stale_version", "publication_not_pending"),
    });
    await user.click(await screen.findByRole("button", { name: STRINGS.publish.approve }));
    expect((await screen.findByTestId("mutation-error")).textContent).toContain(
      STRINGS.errors.notPending,
    );
  });
});

describe("delete", () => {
  it("deletes with the loaded ETag as If-Match", async () => {
    const user = userEvent.setup();
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const { calls } = setup(VIEW_PATH, {
      ...viewRoutes(report()),
      [`DELETE ${ITEM_API}`]: { status: 204, body: null },
      [`GET ${LIST_API}`]: { status: 200, body: { items: [], next_cursor: null } },
    });
    await user.click(await screen.findByTestId("delete-report"));
    await waitFor(() => expect(calls.some((c) => c.method === "DELETE")).toBe(true));
    expect(calls.find((c) => c.method === "DELETE")?.ifMatch).toBe(ETAG);
  });

  it("surfaces a stale delete (409) and keeps the page", async () => {
    const user = userEvent.setup();
    vi.spyOn(window, "confirm").mockReturnValue(true);
    setup(VIEW_PATH, {
      ...viewRoutes(report()),
      [`DELETE ${ITEM_API}`]: problem(409, "stale_version", "report_modified"),
    });
    await user.click(await screen.findByTestId("delete-report"));
    expect((await screen.findByTestId("mutation-error")).textContent).toContain(
      STRINGS.errors.stale,
    );
  });
});

describe("save from plan", () => {
  it("builds a body from a plan and a bounded query, with no scope or identity fields", () => {
    const body = buildSaveReportRequest({
      title: "  Agents  ",
      chartPlan: PLAN,
      querySpec: QUERY,
    });
    expect(body).toEqual({ title: "Agents", chart_plan: PLAN, query_spec: QUERY, metric: "cost" });
    const text = JSON.stringify(body);
    for (const forbidden of ["domain_id", "customer_id", "principal", "owner"]) {
      expect(text).not.toContain(forbidden);
    }
  });

  it("refuses an empty or oversized title", () => {
    expect(buildSaveReportRequest({ title: "   ", chartPlan: PLAN, querySpec: QUERY })).toBeNull();
    expect(
      buildSaveReportRequest({ title: "x".repeat(201), chartPlan: PLAN, querySpec: QUERY }),
    ).toBeNull();
  });

  it("saves through the dialog and links to the new report", async () => {
    const user = userEvent.setup();
    const saved = report();
    const route: RouteObject = {
      path: "chat",
      element: <SaveReportDialog chartPlan={PLAN} querySpec={QUERY} domainId={DOMAIN} />,
    };
    const { calls } = setup("/chat", { [`POST ${LIST_API}`]: { status: 201, body: saved } }, [
      route,
    ]);
    await user.click(await screen.findByTestId("save-report-open"));
    const dialog = await screen.findByRole("dialog");
    const submit = within(dialog).getByRole("button", { name: STRINGS.save.submit });
    expect((submit as HTMLButtonElement).disabled).toBe(true);
    await user.type(within(dialog).getByLabelText(STRINGS.save.titleLabel), "Agents by version");
    await user.click(submit);
    expect(await within(dialog).findByTestId("report-saved")).toBeTruthy();
    const post = calls.find((c) => c.method === "POST");
    expect(post?.path).toBe(LIST_API);
    expect(post?.body).toEqual({
      title: "Agents by version",
      chart_plan: PLAN,
      query_spec: QUERY,
      metric: "cost",
    });
    expect(
      within(dialog).getByRole("link", { name: STRINGS.save.open_report }).getAttribute("href"),
    ).toBe(reportViewHref(DOMAIN, REPORT_ID));
  });

  it("shows a hostile plan rejected by the server (422) and reports nothing saved", async () => {
    const user = userEvent.setup();
    const route: RouteObject = {
      path: "chat",
      element: <SaveReportDialog chartPlan={PLAN} querySpec={QUERY} domainId={DOMAIN} />,
    };
    setup("/chat", { [`POST ${LIST_API}`]: problem(422, "invalid_schema") }, [route]);
    await user.click(await screen.findByTestId("save-report-open"));
    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByLabelText(STRINGS.save.titleLabel), "Agents");
    await user.click(within(dialog).getByRole("button", { name: STRINGS.save.submit }));
    expect((await within(dialog).findByTestId("mutation-error")).textContent).toContain(
      STRINGS.errors.invalid,
    );
    expect(within(dialog).queryByTestId("report-saved")).toBeNull();
  });
});
