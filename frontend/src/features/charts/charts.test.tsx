import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import type { ChartPlan } from "@neurosphere/contracts";
import { afterEach, describe, expect, it, vi } from "vitest";
import { axe } from "vitest-axe";
import { ChartFrame, type ChartStatus } from "./ChartFrame";
import {
  MSG_ERROR,
  MSG_READY,
  MSG_RENDER,
  MSG_RENDERED,
  PROTOCOL_VERSION,
  parseParentMessage,
  parseSandboxMessage,
  specViolations,
} from "./protocol";
import { STRINGS } from "./strings";

afterEach(cleanup);

function plan(over: Record<string, unknown> = {}): ChartPlan {
  return {
    schema_version: "1.0.0",
    citations: [{ evidence_id: "ev:cost", as_of: "2026-10-10T11:58:00Z", label: "Invoiced cost" }],
    spec: {
      title: "Cost",
      width: 400,
      height: 200,
      data: {
        values: [
          { agent: "a", amount: 1.5 },
          { agent: "b", amount: null },
        ],
      },
      mark: "bar",
      encoding: {
        x: { field: "agent", type: "nominal" },
        y: { field: "amount", type: "quantitative" },
      },
      ...over,
    },
  } as ChartPlan;
}

function frameWindow(): Window {
  const iframe = document.querySelector("iframe");
  if (iframe?.contentWindow == null) throw new Error("no iframe window");
  return iframe.contentWindow;
}

function fromSandbox(data: unknown, source: Window | null, origin = "null"): void {
  act(() => {
    window.dispatchEvent(new MessageEvent("message", { data, source, origin }));
  });
}

describe("ChartFrame focus indicator", () => {
  it("paints a ring while the iframe holds focus and clears it when focus returns", () => {
    render(<ChartFrame plan={plan()} />);
    const iframe = document.querySelector("iframe") as HTMLIFrameElement;
    const before = iframe.className;
    iframe.focus();
    act(() => {
      window.dispatchEvent(new Event("blur"));
    });
    expect(iframe.className).not.toBe(before);
    act(() => {
      window.dispatchEvent(new Event("focus"));
    });
    expect(iframe.className).toBe(before);
  });
});

describe("ChartFrame sandbox attributes", () => {
  it("sandboxes the iframe with allow-scripts only", () => {
    render(<ChartFrame plan={plan()} />);
    const iframe = document.querySelector("iframe");
    expect(iframe).not.toBeNull();
    expect(iframe?.getAttribute("sandbox")).toBe("allow-scripts");
    expect(iframe?.getAttribute("sandbox")).not.toContain("allow-same-origin");
    expect(iframe?.getAttribute("src")).toBe("/chart-sandbox.html");
    expect(iframe?.getAttribute("referrerpolicy")).toBe("no-referrer");
  });
});

describe("ChartFrame postMessage handshake", () => {
  it("sends the spec only after the sandbox reports ready", () => {
    render(<ChartFrame plan={plan()} />);
    const win = frameWindow();
    const post = vi.spyOn(win, "postMessage");
    expect(post).not.toHaveBeenCalled();

    fromSandbox({ type: MSG_READY, version: PROTOCOL_VERSION }, win);
    expect(post).toHaveBeenCalledTimes(1);
    const [message, target] = post.mock.calls[0] as [Record<string, unknown>, string];
    expect(target).toBe("*");
    expect(message["type"]).toBe(MSG_RENDER);
    expect(message["spec"]).toEqual(plan().spec);
  });

  it("ignores messages that do not come from the iframe window or have a real origin", () => {
    render(<ChartFrame plan={plan()} />);
    const win = frameWindow();
    const post = vi.spyOn(win, "postMessage");
    const ready = { type: MSG_READY, version: PROTOCOL_VERSION };

    fromSandbox(ready, window);
    fromSandbox(ready, null);
    fromSandbox(ready, win, "https://evil.example");
    expect(post).not.toHaveBeenCalled();
  });

  it("tracks rendered and failed status by request id and falls back to the table", () => {
    const seen: ChartStatus[] = [];
    render(<ChartFrame plan={plan()} onStatusChange={(s) => seen.push(s)} />);
    const win = frameWindow();
    const post = vi.spyOn(win, "postMessage");
    fromSandbox({ type: MSG_READY, version: PROTOCOL_VERSION }, win);
    const id = (post.mock.calls[0]?.[0] as { request_id: string }).request_id;

    fromSandbox({ type: MSG_RENDERED, version: PROTOCOL_VERSION, request_id: "stale" }, win);
    expect(seen.at(-1)).toBe("loading");
    fromSandbox({ type: MSG_RENDERED, version: PROTOCOL_VERSION, request_id: id }, win);
    expect(seen.at(-1)).toBe("rendered");

    fromSandbox({ type: MSG_READY, version: PROTOCOL_VERSION }, win);
    const id2 = (post.mock.calls[1]?.[0] as { request_id: string }).request_id;
    fromSandbox(
      { type: MSG_ERROR, version: PROTOCOL_VERSION, request_id: id2, code: "render_failed" },
      win,
    );
    expect(seen.at(-1)).toBe("failed");
    expect(screen.getByRole("alert")).toHaveTextContent(STRINGS.failed);
    expect(screen.getByRole("table")).toBeInTheDocument();
  });

  it("never mounts the iframe or posts anything for a plan carrying expr", () => {
    const seen: ChartStatus[] = [];
    const hostile = plan({ params: [{ name: "p", expr: "1" }] });
    render(<ChartFrame plan={hostile} onStatusChange={(s) => seen.push(s)} />);
    expect(document.querySelector("iframe")).toBeNull();
    expect(seen.at(-1)).toBe("rejected");
    expect(screen.getByRole("alert")).toHaveTextContent(STRINGS.rejected);
  });
});

describe("table view", () => {
  it("is an accessible table with column headers and null cells", async () => {
    const { container } = render(<ChartFrame plan={plan()} title="Cost by agent" />);
    fireEvent.click(screen.getByRole("tab", { name: STRINGS.tableView }));
    const table = screen.getByRole("table", { name: "Cost by agent" });
    expect(
      within(table)
        .getAllByRole("columnheader")
        .map((h) => h.textContent),
    ).toEqual(["agent", "amount"]);
    expect(within(table).getAllByRole("row")).toHaveLength(3);
    // The citation time goes through Timestamp: absolute UTC value, no raw ISO string.
    const sources = screen.getByTestId("chart-sources");
    expect(sources.textContent).toContain("Invoiced cost (as of");
    expect(sources.textContent).toContain("2026-10-10 11:58 UTC");
    expect(sources.textContent).not.toContain("2026-10-10T11:58:00Z");
    const results = await axe(container);
    expect(results.violations.map((v) => `${v.id}: ${v.help}`)).toEqual([]);
  });
});

describe("message schema", () => {
  it("accepts only versioned, well-formed messages", () => {
    expect(parseSandboxMessage({ type: MSG_READY, version: PROTOCOL_VERSION })).not.toBeNull();
    expect(parseSandboxMessage({ type: MSG_READY, version: 2 })).toBeNull();
    expect(parseSandboxMessage({ type: MSG_RENDERED, version: 1 })).toBeNull();
    expect(
      parseSandboxMessage({ type: MSG_ERROR, version: 1, request_id: "r1", code: "boom" }),
    ).toBeNull();
    expect(parseSandboxMessage("ns.chart.ready")).toBeNull();
    expect(
      parseParentMessage({ type: MSG_RENDER, version: 1, request_id: "r1", spec: {} }),
    ).not.toBeNull();
    expect(parseParentMessage({ type: "other", version: 1, request_id: "r1" })).toBeNull();
    expect(parseParentMessage({ type: MSG_RENDER, version: 1, request_id: "" })).toBeNull();
  });

  it.each([
    ["expr", { params: [{ name: "p", expr: "1" }] }],
    ["url data", { data: { url: "https://x.example/d.json" } }],
    ["named data", { data: { name: "src" } }],
    ["calculate", { transform: [{ calculate: "1", as: "x" }] }],
    ["href", { encoding: { x: { field: "agent", type: "nominal" }, href: { field: "agent" } } }],
    ["bad mark", { mark: "image" }],
    ["config", { config: {} }],
  ])("spec guard rejects %s", (_label, over) => {
    expect(specViolations(plan(over).spec).length).toBeGreaterThan(0);
  });

  it("spec guard allows data fields named like banned keys", () => {
    const ok = plan({ data: { values: [{ url: "a", config: 1 }] } });
    expect(specViolations(ok.spec)).toEqual([]);
  });
});

describe("sandbox sources", () => {
  const sources = import.meta.glob("./sandbox/*.ts", {
    query: "?raw",
    import: "default",
    eager: true,
  }) as Record<string, string>;
  const files = Object.entries(sources).map(
    ([path, source]) => [path.replace("./sandbox/", ""), source] as const,
  );

  it("has sandbox sources to inspect", () => {
    expect(files.map(([f]) => f).sort()).toEqual(["main.ts", "render.ts"]);
  });

  it.each(files)("%s never references eval or the Function constructor", (_name, source) => {
    expect(source).not.toMatch(/\beval\s*\(/);
    expect(source).not.toMatch(/new\s+Function\b/);
    expect(source).not.toMatch(/(^|[^.\w])Function\s*\(/);
    expect(source).not.toMatch(/setTimeout\s*\(\s*["'`]/);
  });

  it("configures vega with the interpreter and ast parsing and a refusing loader", () => {
    const render = files.find(([f]) => f === "render.ts")?.[1] ?? "";
    expect(render).toContain('from "vega-interpreter"');
    expect(render).toContain("expr: expressionInterpreter");
    expect(render).toContain("ast: true");
    expect(render).toContain("loader: denyLoader");
  });

  it("accepts messages from the parent window only", () => {
    const main = files.find(([f]) => f === "main.ts")?.[1] ?? "";
    expect(main).toContain("event.source !== window.parent");
  });
});
