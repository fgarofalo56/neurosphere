import { act, cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { Outlet, RouterProvider, createMemoryRouter, useLocation } from "react-router";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { axe } from "vitest-axe";
import { QueryProvider, createApiClient } from "../../api/index.js";
import { detailHref } from "../actions/ActionsPage";
import { CopilotDock } from "./CopilotDock";
import { actionDetailHref, displayText } from "./components";
import { buildMessageContext, timeRangeFromParams } from "./requestContext";
import { setCopilotSelection, useCopilotSelection } from "./selection";
import { STRINGS } from "./strings";
import { SseParser, parseEvent, streamMessage, type StreamTransport } from "./stream";
import { CopilotTransportProvider } from "./transport";

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
  setCopilotSelection([]);
});

// ---- fixtures: the SSE shapes of frontend/tests/mock-api/copilot.ts ---------------------------

type Ev = readonly [string, unknown];

const ECHO = {
  page: "echo-page",
  route: "/echo/route",
  filters: { status: "ok" },
  time_range: { from: "2026-10-01T00:00:00Z", to: "2026-10-08T00:00:00Z" },
  selection: ["accepted-entity"],
  dropped_selection_count: 2,
  applied_domains: ["domain-a"],
};

const PLAN = {
  schema_version: "1.0.0",
  citations: [{ evidence_id: "ev-1", as_of: "2026-10-21T12:00:00Z" }],
  spec: {
    title: "Cost by agent",
    data: { values: [{ agent: "a", cost: 1 }] },
    mark: "bar",
    encoding: {
      x: { field: "agent", type: "nominal" },
      y: { field: "cost", type: "quantitative" },
    },
  },
};

const SUGGESTION = {
  intent_id: "intent-1",
  domain_id: "domain-a",
  action_type: "swap_model",
  target: { canonical_id: "commercial:e2e:foundry:model_deployment:support-gpt" },
  intent_hash: "hash-1",
};

const ANSWERED: Ev[] = [
  ["context", ECHO],
  ["tool", { name: "get_cost_summary", status: "started" }],
  ["tool", { name: "get_cost_summary", status: "ok" }],
  ["token", { text: "Spend on support-gpt is highest " }],
  ["token", { text: "[cite:r1]." }],
  [
    "citation",
    {
      record_id: "r1",
      kind: "cost_record",
      source: "aggregates",
      as_of: "2026-10-21T12:00:00Z",
      freshness: "fresh",
    },
  ],
  [
    "citation",
    {
      record_id: "r2",
      kind: "cost_record",
      source: "aggregates",
      as_of: "2026-10-14T12:00:00Z",
      freshness: "stale",
    },
  ],
  [
    "citation",
    { record_id: "r3", kind: "cost_record", source: "billing", as_of: null, freshness: "unknown" },
  ],
  ["chart", { chart_plan: PLAN }],
  ["done", { message_id: "m1", status: "answered" }],
];

const encoder = new TextEncoder();

function frame([name, data]: Ev): string {
  return `event: ${name}\ndata: ${JSON.stringify(data)}\n\n`;
}

function sse(events: readonly Ev[]): Response {
  return new Response(events.map(frame).join(""), {
    status: 200,
    headers: { "content-type": "text/event-stream" },
  });
}

function problem(status: number, code: string): Response {
  return new Response(JSON.stringify({ code, title: code, retryable: status === 503 }), {
    status,
    headers: { "content-type": "application/problem+json" },
  });
}

function created(): Response {
  return new Response(
    JSON.stringify({ id: "conv-1", created_at: "t", retention_class: "standard", expires_at: "t" }),
    { status: 201, headers: { "content-type": "application/json" } },
  );
}

interface Call {
  readonly url: string;
  readonly init: RequestInit;
}

/** A fetch stub: the first call per path family is conversation create, the rest are messages. */
function stubFetch(messages: (n: number, init: RequestInit) => Response | Promise<Response>) {
  const calls: Call[] = [];
  let n = 0;
  const impl = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const request = init ?? {};
    calls.push({ url, init: request });
    if (url.endsWith("/api/v1/copilot/conversations")) return Promise.resolve(created());
    n += 1;
    return Promise.resolve(messages(n, request));
  });
  return { impl: impl as unknown as typeof fetch, calls };
}

function LocationProbe(): ReactElement {
  const location = useLocation();
  return <output data-testid="location">{`${location.pathname}${location.search}`}</output>;
}

function Shell(): ReactElement {
  return (
    <>
      <Outlet />
      <CopilotDock />
    </>
  );
}

function mount(
  fetchImpl: typeof fetch,
  initial = "/dashboards?status=ok&days=7&domain_id=domain-a",
  page: ReactElement = <LocationProbe />,
) {
  const transport: StreamTransport = {
    baseUrl: "http://api.test",
    getToken: () => Promise.resolve("test-token"),
    fetchImpl,
  };
  const client = createApiClient({
    baseUrl: "http://api.test",
    getToken: () => Promise.resolve("test-token"),
    fetchImpl,
  });
  const router = createMemoryRouter(
    [
      {
        path: "/",
        Component: Shell,
        children: [{ path: "*", element: page }],
      },
    ],
    { initialEntries: [initial] },
  );
  return render(
    <QueryProvider client={client}>
      <CopilotTransportProvider transport={transport}>
        <RouterProvider router={router} />
      </CopilotTransportProvider>
    </QueryProvider>,
  );
}

async function ask(text = "How much did we spend?") {
  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: STRINGS.open }));
  await user.type(screen.getByRole("textbox", { name: STRINGS.inputLabel }), text);
  await user.click(screen.getByRole("button", { name: STRINGS.send }));
  return user;
}

function lastBody(calls: readonly Call[]): Record<string, unknown> {
  const call = calls.filter((c) => c.url.endsWith("/messages")).at(-1);
  return JSON.parse(String(call?.init.body)) as Record<string, unknown>;
}

// ---- rendering --------------------------------------------------------------------------------

describe("context chip", () => {
  it("shows exactly what the server echoed, not what the client asked for", async () => {
    const { impl, calls } = stubFetch(() => sse(ANSWERED));
    mount(impl);
    await ask();

    const chip = await screen.findByTestId("context-chip");
    await waitFor(() => expect(chip).toHaveTextContent("Page: echo-page"));
    expect(chip).toHaveTextContent("Route: /echo/route");
    expect(chip).toHaveTextContent("Filters: status=ok");
    expect(chip).toHaveTextContent("2026-10-01T00:00:00Z to 2026-10-08T00:00:00Z");
    expect(chip).toHaveTextContent("Selection: accepted-entity");
    expect(chip).toHaveTextContent("Domains: domain-a");
    expect(chip).toHaveTextContent(STRINGS.context.droppedMany(2));
    // The client asked for something else: its own page name, route and a days window.
    const sent = lastBody(calls)["context"] as Record<string, unknown>;
    expect(sent["page"]).toBe("dashboards");
    expect(chip).not.toHaveTextContent("Page: dashboards");
  });

  it("sends the router location, allowlisted filters, time range and published selection", async () => {
    const { impl, calls } = stubFetch(() => sse(ANSWERED));
    function Publisher(): null {
      useCopilotSelection(["entity-1", "entity-2"]);
      return null;
    }
    mount(impl, "/dashboards?status=ok&days=7&domain_id=domain-a&evil=1", <Publisher />);
    await ask();
    await screen.findByText(/Spend on support-gpt/);
    const context = lastBody(calls)["context"] as Record<string, unknown>;
    expect(context["route"]).toBe("/dashboards");
    expect(context["filters"]).toEqual({ status: "ok" });
    expect(context["selection"]).toEqual(["entity-1", "entity-2"]);
    expect(context["domain_id"]).toBe("domain-a");
    const range = context["time_range"] as { from: string; to: string };
    expect(Date.parse(range.to) - Date.parse(range.from)).toBe(7 * 86_400_000);
  });
});

describe("answered stream", () => {
  it("renders tokens, citations with freshness in words, and the chart", async () => {
    const { impl } = stubFetch(() => sse(ANSWERED));
    mount(impl);
    await ask();

    const turn = await screen.findByTestId("assistant-turn");
    await waitFor(() => expect(turn).toHaveAttribute("data-status", "answered"));
    expect(screen.getByTestId("answer-text")).toHaveTextContent(
      "Spend on support-gpt is highest [r1].",
    );
    const citations = within(screen.getByTestId("citations")).getAllByRole("listitem");
    expect(citations).toHaveLength(3);
    expect(citations[0]).toHaveTextContent("Fresh");
    expect(citations[0]).toHaveTextContent("as of 2026-10-21T12:00:00Z");
    expect(citations[1]).toHaveTextContent("Stale");
    expect(citations[2]).toHaveTextContent("Freshness unknown");
    expect(citations[2]).toHaveTextContent("date unknown");
    expect(screen.getByTestId("tools")).toHaveTextContent("get_cost_summary: done");

    const chart = screen.getByTestId("assistant-chart");
    expect(within(chart).getByTestId("chart-frame")).toBeInTheDocument();
    expect(within(chart).getByTestId("save-report-open")).toBeInTheDocument();
  });

  it("records the first-token timing for tests", async () => {
    const { impl } = stubFetch(() => sse(ANSWERED));
    mount(impl);
    await ask();
    const turn = await screen.findByTestId("assistant-turn");
    await waitFor(() => expect(turn).toHaveAttribute("data-first-token-ms"));
    expect(Number(turn.getAttribute("data-first-token-ms"))).toBeGreaterThanOrEqual(0);
    expect(
      performance.getEntriesByType("mark").some((m) => m.name.startsWith("copilot:first-token")),
    ).toBe(true);
  });

  it("reads a stream split at arbitrary byte boundaries", async () => {
    const text = ANSWERED.map(frame).join("");
    const bytes = encoder.encode(text);
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        for (let i = 0; i < bytes.length; i += 7) controller.enqueue(bytes.slice(i, i + 7));
        controller.close();
      },
    });
    const { impl } = stubFetch(() => new Response(body, { status: 200 }));
    mount(impl);
    await ask();
    await waitFor(() =>
      expect(screen.getByTestId("assistant-turn")).toHaveAttribute("data-status", "answered"),
    );
    expect(screen.getByTestId("answer-text")).toHaveTextContent("[r1].");
  });
});

describe("terminal semantics", () => {
  it("replaces streamed tokens with the abstention and its reason", async () => {
    const { impl } = stubFetch(() =>
      sse([
        ["context", ECHO],
        ["token", { text: "I could not find " }],
        [
          "citation",
          { record_id: "r9", kind: "k", source: "s", as_of: null, freshness: "unknown" },
        ],
        [
          "abstain",
          {
            message_id: "m2",
            reason_code: "no_authorized_evidence",
            reason: "No records you can read support an answer.",
          },
        ],
      ]),
    );
    mount(impl);
    await ask();
    const notice = await screen.findByTestId("abstain");
    expect(notice).toHaveTextContent("No records you can read support an answer.");
    expect(notice).toHaveTextContent("no_authorized_evidence");
    expect(screen.queryByTestId("answer-text")).toBeNull();
    expect(screen.queryByTestId("citations")).toBeNull();
    expect(screen.queryByText(/I could not find/)).toBeNull();
  });

  it("replaces streamed tokens with the denial and its reason", async () => {
    const { impl } = stubFetch(() =>
      sse([
        ["context", ECHO],
        ["tool", { name: "export_data", status: "refused" }],
        ["token", { text: "Sure, exporting" }],
        [
          "denied",
          {
            message_id: "m3",
            reason_code: "tool_not_registered",
            reason: "That tool is not allowed.",
          },
        ],
      ]),
    );
    mount(impl);
    await ask();
    const notice = await screen.findByTestId("denied");
    expect(notice).toHaveTextContent("That tool is not allowed.");
    expect(notice).toHaveTextContent("tool_not_registered");
    expect(screen.queryByText(/exporting/)).toBeNull();
    expect(screen.getByTestId("tools")).toHaveTextContent("export_data: refused");
  });

  it("shows an error event as an alert, never as an answer", async () => {
    const { impl } = stubFetch(() =>
      sse([
        ["context", ECHO],
        ["error", { code: "dependency_transient", detail: "The model endpoint is unavailable." }],
      ]),
    );
    mount(impl);
    await ask();
    const alert = await screen.findByTestId("turn-error");
    expect(alert).toHaveAttribute("role", "alert");
    expect(alert).toHaveTextContent("The model endpoint is unavailable.");
  });

  it("ignores unknown events and malformed non-terminal payloads", async () => {
    const { impl } = stubFetch(() =>
      sse([
        ["context", ECHO],
        ["telemetry", { anything: true }],
        ["token", { text: 7 }],
        ["token", { text: "Real text." }],
        ["future_event", "not even an object"],
        ["done", { message_id: "m4", status: "answered" }],
      ]),
    );
    mount(impl);
    await ask();
    await waitFor(() =>
      expect(screen.getByTestId("assistant-turn")).toHaveAttribute("data-status", "answered"),
    );
    expect(screen.getByTestId("answer-text")).toHaveTextContent("Real text.");
  });

  it("ends a stream that never sends a terminal event as an error", async () => {
    const { impl } = stubFetch(() =>
      sse([
        ["context", ECHO],
        ["token", { text: "Half an ans" }],
      ]),
    );
    mount(impl);
    await ask();
    expect(await screen.findByTestId("turn-error")).toHaveTextContent("ended unexpectedly");
  });
});

describe("HTTP failures", () => {
  it.each([
    [403, "forbidden", STRINGS.httpErrors["forbidden"]],
    [503, "dependency_transient", STRINGS.httpErrors["dependency_transient"]],
    [401, "unauthorized", STRINGS.httpErrors["unauthorized"]],
  ] as const)("maps HTTP %i to a typed message", async (status, code, message) => {
    const { impl } = stubFetch(() => problem(status, code));
    mount(impl);
    await ask();
    const alert = await screen.findByTestId("turn-error");
    expect(alert).toHaveTextContent(message ?? "");
    expect(screen.queryByTestId("answer-text")).toBeNull();
  });

  it("maps a network failure to the unavailable message", async () => {
    const impl = vi.fn((input: RequestInfo | URL) =>
      String(input).endsWith("/conversations")
        ? Promise.resolve(created())
        : Promise.reject(new TypeError("fetch failed")),
    ) as unknown as typeof fetch;
    mount(impl);
    await ask();
    expect(await screen.findByTestId("turn-error")).toHaveTextContent(
      STRINGS.httpErrors["dependency_transient"] ?? "",
    );
  });

  it("surfaces typed ApiErrors from the stream client", async () => {
    const { impl } = stubFetch(() => problem(403, "forbidden"));
    const transport: StreamTransport = {
      baseUrl: "http://api.test",
      getToken: () => Promise.resolve("t"),
      fetchImpl: impl,
    };
    const run = async () => {
      for await (const _event of streamMessage(transport, "c", {
        text: "x",
        context: buildMessageContext({ pathname: "/", search: "", selection: [] }),
      })) {
        void _event;
      }
    };
    await expect(run()).rejects.toMatchObject({ name: "ForbiddenError", status: 403 });
  });
});

describe("action handoff", () => {
  it("opens the PRP-17 action page for the drafted intent and has no execute control", async () => {
    const { impl, calls } = stubFetch(() =>
      sse([
        ["context", ECHO],
        ["token", { text: "A cheaper deployment is available." }],
        ["action_suggestion", SUGGESTION],
        ["done", { message_id: "m5", status: "answered" }],
      ]),
    );
    mount(impl);
    const user = await ask("swap the model");
    const card = await screen.findByTestId("action-suggestion");
    expect(card).toHaveTextContent(
      "swap_model on commercial:e2e:foundry:model_deployment:support-gpt",
    );

    // Chat has a Review control and nothing that confirms or executes.
    const panel = screen.getByTestId("copilot-panel");
    const names = within(panel)
      .getAllByRole("button")
      .map((b) => b.textContent ?? "");
    expect(names).toContain(STRINGS.suggestion.review);
    expect(names.filter((n) => /confirm|execute|apply|approve/i.test(n))).toEqual([]);

    await user.click(within(card).getByRole("button", { name: STRINGS.suggestion.review }));
    const target = `/actions/detail?domain_id=domain-a&intent_id=intent-1`;
    await waitFor(() => expect(screen.getByTestId("location")).toHaveTextContent(target));
    expect(actionDetailHref("domain-a", "intent-1")).toBe(detailHref("domain-a", "intent-1"));

    // Only conversation create and message post were ever called: no confirm, no execute.
    const paths = calls.map((c) => new URL(c.url).pathname);
    expect(paths.every((p) => p.startsWith("/api/v1/copilot/conversations"))).toBe(true);
    expect(paths.some((p) => /confirm|execute|intents/.test(p))).toBe(false);
  });
});

describe("lifecycle", () => {
  it("aborts the in-flight request on unmount", async () => {
    let signal: AbortSignal | null = null;
    const hang = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(encoder.encode(frame(["context", ECHO])));
      },
    });
    const { impl } = stubFetch((_n, init) => {
      signal = init.signal ?? null;
      return new Response(hang, { status: 200 });
    });
    const view = mount(impl);
    await ask();
    await screen.findByTestId("assistant-turn");
    expect((signal as AbortSignal | null)?.aborted).toBe(false);
    view.unmount();
    expect((signal as AbortSignal | null)?.aborted).toBe(true);
  });

  it("aborts the earlier stream when a new message is sent", async () => {
    const signals: AbortSignal[] = [];
    const hang = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(encoder.encode(frame(["context", ECHO])));
      },
    });
    const { impl } = stubFetch((n, init) => {
      if (init.signal != null) signals.push(init.signal);
      return n === 1 ? new Response(hang, { status: 200 }) : sse(ANSWERED);
    });
    mount(impl);
    const user = await ask("first");
    await screen.findByTestId("assistant-turn");
    await user.type(screen.getByRole("textbox", { name: STRINGS.inputLabel }), "second");
    await user.click(screen.getByRole("button", { name: STRINGS.send }));
    await waitFor(() => expect(screen.getAllByTestId("assistant-turn")).toHaveLength(2));
    await waitFor(() => expect(signals[0]?.aborted).toBe(true));
    const turns = screen.getAllByTestId("assistant-turn");
    expect(turns[0]).toHaveAttribute("data-status", "error");
    expect(turns[0]).toHaveTextContent(STRINGS.cancelled);
    await waitFor(() => expect(turns[1]).toHaveAttribute("data-status", "answered"));
  });

  it("reuses one conversation for later messages", async () => {
    const { impl, calls } = stubFetch(() => sse(ANSWERED));
    mount(impl);
    const user = await ask("one");
    await waitFor(() =>
      expect(screen.getByTestId("assistant-turn")).toHaveAttribute("data-status", "answered"),
    );
    await user.type(screen.getByRole("textbox", { name: STRINGS.inputLabel }), "two");
    await user.click(screen.getByRole("button", { name: STRINGS.send }));
    await waitFor(() => expect(calls.filter((c) => c.url.endsWith("/messages"))).toHaveLength(2));
    expect(calls.filter((c) => c.url.endsWith("/api/v1/copilot/conversations"))).toHaveLength(1);
    const messageCall = calls.find((c) => c.url.endsWith("/conv-1/messages"));
    expect(messageCall).toBeDefined();
    const headers = messageCall?.init.headers as Record<string, string>;
    expect(headers["Authorization"]).toBe("Bearer test-token");
  });
});

describe("dock accessibility", () => {
  it("is a labelled region, moves focus in and back, and closes on Escape", async () => {
    const { impl } = stubFetch(() => sse(ANSWERED));
    mount(impl);
    const user = userEvent.setup();
    const toggle = screen.getByRole("button", { name: STRINGS.open });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    await user.click(toggle);

    const region = screen.getByRole("region", { name: STRINGS.title });
    expect(region).toBeInTheDocument();
    expect(screen.getByRole("button", { name: STRINGS.close, expanded: true })).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByRole("textbox", { name: STRINGS.inputLabel })).toHaveFocus(),
    );
    const log = screen.getByRole("log", { name: STRINGS.logLabel });
    expect(log).toHaveAttribute("aria-live", "polite");

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("region", { name: STRINGS.title })).toBeNull();
    await waitFor(() => expect(screen.getByRole("button", { name: STRINGS.open })).toHaveFocus());
  });

  it("has no axe violations with an answered turn on screen", async () => {
    // jsdom cannot run axe across the chart iframe; the Playwright spec covers the chart too.
    const withoutChart = ANSWERED.filter(([name]) => name !== "chart");
    const { impl } = stubFetch(() => sse([...withoutChart, ["action_suggestion", SUGGESTION]]));
    const view = mount(impl);
    await ask();
    await waitFor(() =>
      expect(screen.getByTestId("assistant-turn")).toHaveAttribute("data-status", "answered"),
    );
    await act(async () => {});
    const results = await axe(view.container, { rules: { "color-contrast": { enabled: false } } });
    expect(results.violations.map((v) => `${v.id}: ${v.help}`)).toEqual([]);
  });
});

// ---- units ------------------------------------------------------------------------------------

describe("SseParser and parseEvent", () => {
  it("joins multi-line data, accepts CRLF, skips comments and splits across chunks", () => {
    const parser = new SseParser();
    expect(parser.push(": keep-alive\r\n\r\nevent: tok")).toEqual([]);
    const events = parser.push('en\r\ndata: {"text":\r\ndata: "hi"}\r\n\r\n');
    expect(events).toEqual([{ event: "token", data: '{"text":\n"hi"}' }]);
    expect(parseEvent(events[0] ?? { event: "", data: "" })).toEqual({
      name: "token",
      data: { text: "hi" },
    });
  });

  it("turns a malformed terminal into an error and ignores a malformed non-terminal", () => {
    expect(parseEvent({ event: "done", data: "not json" })).toMatchObject({ name: "error" });
    expect(parseEvent({ event: "abstain", data: '{"message_id":"m"}' })).toMatchObject({
      name: "error",
    });
    expect(parseEvent({ event: "token", data: "not json" })).toBeNull();
    expect(parseEvent({ event: "mystery", data: "{}" })).toBeNull();
  });

  it("rejects a chart without a spec or citations", () => {
    expect(parseEvent({ event: "chart", data: '{"chart_plan":{"spec":{}}}' })).toBeNull();
  });
});

describe("request context", () => {
  it("builds page, route, filters, selection and a domain hint", () => {
    const context = buildMessageContext({
      pathname: "/reports/view",
      search: "?kind=a&kind=b&provider=x&unknown=1&domain_id=d1",
      selection: ["e1"],
      now: new Date("2026-10-21T00:00:00Z"),
    });
    expect(context).toMatchObject({
      page: "reports",
      route: "/reports/view",
      filters: { kind: ["a", "b"], provider: "x" },
      selection: ["e1"],
      domain_id: "d1",
      time_range: null,
    });
    expect(buildMessageContext({ pathname: "/", search: "", selection: [] }).page).toBe("home");
  });

  it("derives a time range from from/to or days and drops reversed or invalid ranges", () => {
    const now = new Date("2026-10-21T00:00:00Z");
    expect(
      timeRangeFromParams(
        new URLSearchParams("from=2026-10-01T00:00:00Z&to=2026-10-02T00:00:00Z"),
        now,
      ),
    ).toEqual({ from: "2026-10-01T00:00:00Z", to: "2026-10-02T00:00:00Z" });
    expect(
      timeRangeFromParams(
        new URLSearchParams("from=2026-10-03T00:00:00Z&to=2026-10-02T00:00:00Z"),
        now,
      ),
    ).toBeNull();
    expect(timeRangeFromParams(new URLSearchParams("days=2"), now)).toEqual({
      from: "2026-10-19T00:00:00.000Z",
      to: "2026-10-21T00:00:00.000Z",
    });
    expect(timeRangeFromParams(new URLSearchParams("days=0"), now)).toBeNull();
    expect(timeRangeFromParams(new URLSearchParams("days=abc"), now)).toBeNull();
  });

  it("renders citation handles readably", () => {
    expect(displayText("Up [cite:r1], down [cite:r_2].")).toBe("Up [r1], down [r_2].");
  });
});
