import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { QueryProvider, createApiClient } from "../../api/index.js";
import { ExecutionControlPage } from "./ExecutionControlPage";
import { EMERGENCY_DISABLE_PATH } from "./paths";
import { STRINGS } from "./strings";

class ResizeObserverStub {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}

beforeAll(() => {
  vi.stubGlobal("ResizeObserver", ResizeObserverStub);
});
afterEach(cleanup);

const API = "http://api.test";
const ENABLED = { disabled: false, reason: null, changed_by: null, changed_at: null };

let activeFetch: typeof fetch = () => Promise.reject(new Error("useApi() was not called"));

function json(body: unknown, status = 200, type = "application/json"): Response {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": type } });
}

function problem(status: number, code: string, detail: string): Response {
  return json(
    {
      schema_version: "1.0.0",
      type: "https://neurosphere.invalid/problems/x",
      title: "Problem",
      status,
      detail,
      instance: "/x",
      code,
      reason: detail,
      retryable: false,
      correlation_id: "corr-test-1",
    },
    status,
    "application/problem+json",
  );
}

interface Call {
  readonly method: string;
  readonly path: string;
  readonly body: unknown;
}

/** Strict fake API: only the emergency-disable path exists. */
function useApi(handler: (call: Call) => Response): Call[] {
  const calls: Call[] = [];
  activeFetch = (input, init) => {
    const raw = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    const url = new URL(raw);
    if (url.pathname !== EMERGENCY_DISABLE_PATH) {
      return Promise.reject(new Error(`unhandled request: ${url.pathname}`));
    }
    const body = typeof init?.body === "string" ? (JSON.parse(init.body) as unknown) : undefined;
    const call = { method: init?.method ?? "GET", path: url.pathname, body };
    calls.push(call);
    return Promise.resolve(handler(call));
  };
  return calls;
}

function renderPage() {
  const client = createApiClient({
    baseUrl: API,
    getToken: () => Promise.resolve("test-credential"),
    fetchImpl: (input, init) => activeFetch(input, init),
    maxRetries: 0,
  });
  return render(
    <QueryProvider client={client}>
      <MemoryRouter initialEntries={["/admin/execution-control"]}>
        <ExecutionControlPage />
      </MemoryRouter>
    </QueryProvider>,
  );
}

async function openAndSubmit(reason: string): Promise<void> {
  fireEvent.click(await screen.findByTestId("execution-toggle"));
  const dialog = await screen.findByTestId("change-confirm-dialog");
  fireEvent.change(within(dialog).getByRole("textbox"), { target: { value: reason } });
  fireEvent.click(within(dialog).getByRole("button", { name: /confirm|submit|apply/i }));
}

describe("ExecutionControlPage", () => {
  it("shows the state with a pseudonymous changed_by", async () => {
    useApi(() =>
      json({
        disabled: true,
        reason: "incident_review",
        changed_by: "psn-test-1",
        changed_at: "2026-10-29T08:00:00.000000Z",
      }),
    );
    renderPage();
    expect((await screen.findByTestId("execution-pill")).textContent).toContain(
      STRINGS.disabledText,
    );
    expect(screen.getByTestId("execution-reason").textContent).toBe("incident_review");
    expect(screen.getByTestId("execution-changed-by").textContent).toBe("psn-test-1");
    expect(screen.getByTestId("execution-toggle").textContent).toBe(STRINGS.enable);
  });

  it("disables through the confirm dialog and refreshes from the PUT response", async () => {
    const calls = useApi((c) =>
      c.method === "PUT"
        ? json({
            disabled: true,
            reason: "incident_review",
            changed_by: "psn-test-2",
            changed_at: "2026-10-30T12:00:00.000000Z",
          })
        : json(ENABLED),
    );
    renderPage();
    fireEvent.click(await screen.findByTestId("execution-toggle"));
    const dialog = await screen.findByTestId("change-confirm-dialog");
    expect(within(dialog).getByTestId("change-diff-row").textContent).toContain("enabled");
    expect(calls.filter((c) => c.method === "PUT")).toHaveLength(0);
    fireEvent.change(within(dialog).getByRole("textbox"), { target: { value: "incident_review" } });
    const buttons = within(dialog).getAllByRole("button");
    fireEvent.click(buttons[buttons.length - 1]!);
    await waitFor(() =>
      expect(screen.getByTestId("execution-pill").textContent).toContain(STRINGS.disabledText),
    );
    expect(screen.getByTestId("execution-changed-by").textContent).toBe("psn-test-2");
    const puts = calls.filter((c) => c.method === "PUT");
    expect(puts).toHaveLength(1);
    expect(puts[0]?.body).toEqual({ disabled: true, reason: "incident_review" });
  });

  it("rejects a reason that is not a snake_case code without calling the API", async () => {
    const calls = useApi(() => json(ENABLED));
    renderPage();
    fireEvent.click(await screen.findByTestId("execution-toggle"));
    const dialog = await screen.findByTestId("change-confirm-dialog");
    fireEvent.change(within(dialog).getByRole("textbox"), { target: { value: "Not A Code" } });
    const buttons = within(dialog).getAllByRole("button");
    fireEvent.click(buttons[buttons.length - 1]!);
    expect((await screen.findByTestId("change-error")).textContent).toBe(STRINGS.invalidReason);
    expect(calls.filter((c) => c.method === "PUT")).toHaveLength(0);
  });

  it("shows the server 422 and the API 403 on a write", async () => {
    let status = 422;
    useApi((c) =>
      c.method === "PUT"
        ? status === 422
          ? problem(422, "invalid_schema", "reason rejected by the service")
          : problem(403, "forbidden", "permission_missing")
        : json(ENABLED),
    );
    renderPage();
    await openAndSubmit("valid_code");
    expect((await screen.findByTestId("change-error")).textContent).toContain(
      "reason rejected by the service",
    );
    cleanup();
    status = 403;
    renderPage();
    await openAndSubmit("valid_code");
    expect((await screen.findByTestId("change-error")).textContent).toContain(STRINGS.accessDenied);
    expect(screen.getByTestId("execution-pill").textContent).toContain(STRINGS.enabledText);
  });

  it("shows ForbiddenState when the read is 403", async () => {
    useApi(() => problem(403, "forbidden", "permission_missing"));
    renderPage();
    await screen.findByTestId("forbidden-state");
  });
});
