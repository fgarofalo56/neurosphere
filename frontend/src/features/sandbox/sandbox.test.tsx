import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { QueryProvider, createApiClient } from "../../api/index.js";
import {
  SANDBOX_STORAGE_KEY,
  SandboxBanner,
  SandboxToggle,
  sandboxRoutes,
  sandboxStatusPath,
  useSandboxStore,
  STRINGS,
} from "./index";

class ResizeObserverStub {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}

beforeAll(() => {
  vi.stubGlobal("ResizeObserver", ResizeObserverStub);
});

beforeEach(() => {
  window.localStorage.clear();
  useSandboxStore.setState({ enabled: false });
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("SandboxBanner", () => {
  it("is absent when sandbox mode is off", () => {
    render(<SandboxBanner />);
    expect(screen.queryByRole("region")).toBeNull();
    expect(screen.queryByTestId("sandbox-banner")).toBeNull();
  });

  it("is a named region when sandbox mode is on", () => {
    useSandboxStore.setState({ enabled: true });
    render(<SandboxBanner />);
    const region = screen.getByRole("region", { name: STRINGS.bannerName });
    expect(region.getAttribute("aria-label")).toBe("Sandbox mode: synthetic data only");
    expect(region.textContent).toContain("synthetic dataset");
  });
});

describe("SandboxToggle", () => {
  it("flips the store, shows the banner and persists the choice", async () => {
    const user = userEvent.setup();
    render(
      <>
        <SandboxToggle />
        <SandboxBanner />
      </>,
    );
    const toggle = screen.getByRole("switch", { name: STRINGS.toggleLabel });
    expect(toggle).toHaveProperty("checked", false);

    await user.click(toggle);
    expect(useSandboxStore.getState().enabled).toBe(true);
    expect(screen.getByRole("region", { name: STRINGS.bannerName })).toBeTruthy();
    const stored = JSON.parse(window.localStorage.getItem(SANDBOX_STORAGE_KEY) ?? "{}") as {
      state?: { enabled?: boolean };
    };
    expect(stored.state?.enabled).toBe(true);

    await user.click(toggle);
    expect(useSandboxStore.getState().enabled).toBe(false);
    expect(screen.queryByRole("region")).toBeNull();
    const cleared = JSON.parse(window.localStorage.getItem(SANDBOX_STORAGE_KEY) ?? "{}") as {
      state?: { enabled?: boolean };
    };
    expect(cleared.state?.enabled).toBe(false);
  });
});

describe("sandbox page", () => {
  function setup(reply: { status: number; body: unknown }) {
    const paths: string[] = [];
    const fetchImpl = vi.fn<typeof fetch>((input) => {
      const url = new URL(String(input));
      paths.push(url.pathname);
      return Promise.resolve(new Response(JSON.stringify(reply.body), { status: reply.status }));
    });
    const client = createApiClient({
      baseUrl: "http://api.test",
      getToken: () => Promise.resolve("t"),
      fetchImpl,
      maxRetries: 0,
    });
    const router = createMemoryRouter(sandboxRoutes, { initialEntries: ["/sandbox"] });
    render(
      <QueryProvider client={client}>
        <RouterProvider router={router} />
      </QueryProvider>,
    );
    return { paths };
  }

  it("renders the status summary from the API", async () => {
    const { paths } = setup({
      status: 200,
      body: {
        environment: "sandbox",
        synthetic: true,
        customer_id: "synthco",
        database: "sandbox-neurosphere",
        counts: { domain: 4, agent: 12 },
        relations: 30,
        total: 46,
      },
    });
    await waitFor(() => expect(screen.getByTestId("sandbox-total").textContent).toBe("46"));
    expect(paths).toEqual([sandboxStatusPath()]);
    expect(screen.getByTestId("sandbox-flags").textContent).toContain("sandbox");
    const rows = screen.getAllByTestId("sandbox-row").map((r) => r.textContent);
    expect(rows).toEqual([`${STRINGS.kinds.domain}4`, `${STRINGS.kinds.agent}12`]);
    expect(screen.getByRole("heading", { level: 1, name: STRINGS.pageTitle })).toBeTruthy();
  });

  it("shows an access-denied state on 403, not an empty summary", async () => {
    setup({ status: 403, body: { status: 403, code: "forbidden" } });
    const alert = await screen.findByTestId("sandbox-error");
    expect(alert.textContent).toContain(STRINGS.forbidden);
    expect(screen.queryByTestId("sandbox-total")).toBeNull();
  });
});
