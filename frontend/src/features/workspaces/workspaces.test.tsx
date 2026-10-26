import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { QueryProvider, createApiClient } from "../../api/index.js";
import { createAppRoutes } from "../../app/routes";
import { NS_ROLES } from "../../auth/roles";
import { WORKSPACES, probePath } from "./personas";
import { workspaceNavItems, workspaceRoutes } from "./routes";

// jsdom has no ResizeObserver, which Fluent MessageBar uses.
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
});

function setup(path: string, status: number, roles: Parameters<typeof workspaceNavItems>[0]) {
  const fetchImpl = vi.fn<typeof fetch>(() =>
    Promise.resolve(
      status === 200
        ? new Response(JSON.stringify({ ok: true }), { status })
        : new Response(JSON.stringify({ status }), { status }),
    ),
  );
  const client = createApiClient({
    baseUrl: "http://api.test",
    getToken: () => Promise.resolve("t"),
    fetchImpl,
    maxRetries: 0,
  });
  const router = createMemoryRouter(
    createAppRoutes({ extraRoutes: workspaceRoutes, navItems: workspaceNavItems(roles) }),
    { initialEntries: [path] },
  );
  render(
    <QueryProvider client={client}>
      <RouterProvider router={router} />
    </QueryProvider>,
  );
  return fetchImpl;
}

describe("workspace routes", () => {
  it.each(WORKSPACES)("renders the $label route and probes the API", async (def) => {
    const fetchImpl = setup(def.path, 200, NS_ROLES);
    await screen.findByText(/Placeholder/);
    expect(screen.getByRole("heading", { name: `${def.label} workspace` })).toBeTruthy();
    expect(String(fetchImpl.mock.calls[0]?.[0])).toContain(probePath(def.persona));
  });

  it("nav shows only entries suggested by roles", async () => {
    setup("/workspaces/viewer", 200, ["Viewer", "Auditor"]);
    await screen.findByText(/Placeholder/);
    const nav = screen.getByRole("navigation", { name: "Primary" });
    const links = Array.from(nav.querySelectorAll("a")).map((a) => a.textContent);
    expect(links).toEqual(["Viewer", "Auditor"]);
  });

  it("no roles yields no workspace nav entries", () => {
    expect(workspaceNavItems([])).toEqual([]);
  });

  it("URL to a hidden workspace still calls the API and renders forbidden on 403", async () => {
    const fetchImpl = setup("/workspaces/admin", 403, ["Viewer"]);
    await screen.findByTestId("forbidden-state");
    expect(fetchImpl).toHaveBeenCalled();
    expect(String(fetchImpl.mock.calls[0]?.[0])).toContain("/api/v1/workspaces/admin");
    const nav = screen.getByRole("navigation", { name: "Primary" });
    expect(nav.textContent).not.toContain("Admin");
    expect(screen.queryByText(/Placeholder/)).toBeNull();
  });

  it("shows a loading state while the probe is in flight", () => {
    const fetchImpl = vi.fn<typeof fetch>(() => new Promise<Response>(() => undefined));
    const client = createApiClient({
      baseUrl: "http://api.test",
      getToken: () => Promise.resolve("t"),
      fetchImpl,
      maxRetries: 0,
    });
    const router = createMemoryRouter(
      createAppRoutes({ extraRoutes: workspaceRoutes, navItems: workspaceNavItems(NS_ROLES) }),
      { initialEntries: ["/workspaces/viewer"] },
    );
    render(
      <QueryProvider client={client}>
        <RouterProvider router={router} />
      </QueryProvider>,
    );
    expect(screen.getByLabelText("Loading the Viewer workspace")).toBeTruthy();
    expect(screen.queryByText(/Placeholder/)).toBeNull();
  });

  it("renders the persona page as cards with a status indicator", async () => {
    setup("/workspaces/steward", 200, NS_ROLES);
    await screen.findByText(/Placeholder/);
    expect(document.querySelectorAll('[data-slot="panel"]').length).toBe(2);
    expect(document.querySelector('[data-slot="health-indicator"]')?.textContent).toBe(
      "Service answered",
    );
  });

  it("503 shows an error state, not empty data", async () => {
    setup("/workspaces/steward", 503, NS_ROLES);
    await waitFor(() => expect(screen.getByTestId("error-state")).toBeTruthy());
    expect(screen.queryByTestId("forbidden-state")).toBeNull();
    expect(screen.queryByText(/Placeholder/)).toBeNull();
  });
});
