import { cleanup, render, screen } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import { createAppRoutes } from "./routes";

afterEach(cleanup);

function renderAt(path: string, options?: Parameters<typeof createAppRoutes>[0]) {
  const router = createMemoryRouter(createAppRoutes(options), { initialEntries: [path] });
  return render(<RouterProvider router={router} />);
}

describe("createAppRoutes", () => {
  it("renders home inside the layout with a navigation slot", () => {
    renderAt("/");
    expect(screen.getByRole("navigation", { name: "Primary" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "NeuroSphere" })).toBeTruthy();
  });

  it("renders a not-found page for unknown paths", () => {
    renderAt("/nope");
    expect(screen.getByRole("heading", { name: "Page not found" })).toBeTruthy();
  });

  it("accepts extra routes and nav items through the registration seam", () => {
    renderAt("/ws", {
      extraRoutes: [{ path: "ws", element: <h1>Workspace</h1> }],
      navItems: [
        { to: "/", label: "Home" },
        { to: "/ws", label: "Workspace" },
      ],
    });
    expect(screen.getByRole("heading", { name: "Workspace" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "Workspace" })).toBeTruthy();
  });

  it("contains a throwing route inside the error boundary, keeping the navigation", () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    function Bomb(): never {
      throw new Error("route failed");
    }
    renderAt("/bomb", { extraRoutes: [{ path: "bomb", Component: Bomb }] });
    expect(screen.getByRole("alert").textContent).toContain("Something went wrong");
    expect(screen.getByRole("navigation", { name: "Primary" })).toBeTruthy();
    vi.restoreAllMocks();
  });
});
