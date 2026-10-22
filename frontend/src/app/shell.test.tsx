import { cleanup, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, describe, expect, it } from "vitest";
import {
  NAV_GROUPS,
  groupNavItems,
  isNavItemVisible,
  selectedNavTo,
  type NavItem,
} from "./navigation";
import { accountWith, domainEntry, renderShell, stubResizeObserver } from "./test-support";
import { buildAppNavItems } from "./workspaceNav";

beforeAll(stubResizeObserver);
afterEach(cleanup);

const EXISTING_LINKS = [
  "Cost dashboard",
  "Reconciliation",
  "Actions",
  "Review",
  "Quality",
  "Recommendations",
  "Reports",
  "Map",
  "Map table",
  "Trace replay",
];

function emptyList(): Response {
  return new Response(JSON.stringify({ items: [domainEntry("d:1", "One")] }), { status: 200 });
}

function renderRealNav(roles: readonly string[]) {
  return renderShell({
    account: accountWith(`home-${crypto.randomUUID()}`, roles),
    respond: emptyList,
    path: "/",
    routes: { navItems: buildAppNavItems(), extraRoutes: [] },
  });
}

describe("app shell", () => {
  it("has a Primary navigation landmark with every existing link name", () => {
    renderRealNav(["Viewer"]);
    const nav = screen.getByRole("navigation", { name: "Primary" });
    for (const name of [...EXISTING_LINKS, "Home"]) {
      expect(within(nav).getByRole("link", { name })).toBeInTheDocument();
    }
    expect(screen.getAllByRole("navigation", { name: "Primary" })).toHaveLength(1);
  });

  it("groups the links under the six section labels, in order", () => {
    renderRealNav(["Viewer"]);
    const nav = screen.getByRole("navigation", { name: "Primary" });
    const groups = within(nav).getAllByRole("group");
    expect(groups.map((g) => g.getAttribute("aria-labelledby") !== null)).not.toContain(false);
    const labels = groups.map((g) => within(g).getAllByText(/./)[0]?.textContent);
    expect(labels).toEqual([...NAV_GROUPS]);
    const names = (group: string) =>
      within(within(nav).getByRole("group", { name: group }))
        .getAllByRole("link")
        .map((a) => a.textContent);
    expect(names("Cost & usage")).toEqual([
      "Cost dashboard",
      "Latency dashboard",
      "Coverage dashboard",
      "Reconciliation",
    ]);
    expect(names("Agents")).toEqual(["Map", "Map table", "Trace replay"]);
    expect(names("Quality")).toEqual(["Quality", "Recommendations"]);
    expect(names("Governance")).toEqual(["Review", "Actions"]);
    expect(names("Reports")).toEqual(["Reports"]);
  });

  it("does not add group labels to the page heading outline", () => {
    renderRealNav(["Viewer"]);
    const headings = screen.getAllByRole("heading").map((h) => h.textContent);
    expect(headings).toEqual(["NeuroSphere"]);
  });

  it("shows the product name, a logo slot and the role in the header", () => {
    renderRealNav(["Viewer"]);
    const banner = screen.getByRole("banner");
    expect(within(banner).getByText("NeuroSphere")).toBeInTheDocument();
    expect(banner.querySelector("[data-slot='logo']")).not.toBeNull();
    expect(within(banner).getByRole("button", { name: "Account: Viewer" })).toBeInTheDocument();
  });

  it("hides workspace entries the roles do not suggest, and keeps the rest", () => {
    renderRealNav(["Viewer"]);
    const nav = screen.getByRole("navigation", { name: "Primary" });
    expect(within(nav).getByRole("link", { name: "Viewer" })).toBeInTheDocument();
    for (const hidden of ["Admin", "Steward", "Auditor", "Analyst"]) {
      expect(within(nav).queryByRole("link", { name: hidden })).toBeNull();
    }
    expect(within(nav).getByRole("link", { name: "Actions" })).toBeInTheDocument();
  });

  it("has a skip link that moves focus to main", async () => {
    renderRealNav(["Viewer"]);
    const user = userEvent.setup();
    await user.tab();
    const skip = screen.getByRole("link", { name: "Skip to main content" });
    expect(skip).toHaveFocus();
    expect(skip.getAttribute("href")).toBe("#main-content");
    await user.keyboard("{Enter}");
    const main = screen.getByRole("main");
    expect(main.id).toBe("main-content");
    expect(main).toHaveFocus();
  });

  it("mounts the CopilotDock exactly once", () => {
    renderRealNav(["Viewer"]);
    expect(screen.getAllByRole("button", { name: "Open assistant" })).toHaveLength(1);
  });

  it("marks the entry for the current page", () => {
    renderShell({
      account: accountWith("home-x", ["Viewer"]),
      respond: emptyList,
      path: "/map/table",
      routes: {
        navItems: buildAppNavItems(),
        extraRoutes: [{ path: "map/table", element: <p>t</p> }],
      },
    });
    const nav = screen.getByRole("navigation", { name: "Primary" });
    expect(within(nav).getByRole("link", { name: "Map table" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(within(nav).getByRole("link", { name: "Map" })).toHaveAttribute("aria-current", "false");
  });
});

describe("navigation model", () => {
  const items: NavItem[] = [
    { to: "/a", label: "A", group: "Reports" },
    { to: "/b", label: "B" },
    { to: "/c", label: "C", group: "Overview", roles: ["Admin"] },
    { to: "/d", label: "D", group: "Overview", permission: "action.execute" },
  ];

  it("hides entries by role and by permission", () => {
    const none = { roles: [], permissions: new Set<string>() } as const;
    expect(isNavItemVisible(items[0]!, none)).toBe(true);
    expect(isNavItemVisible(items[2]!, none)).toBe(false);
    expect(isNavItemVisible(items[2]!, { ...none, roles: ["Admin"] })).toBe(true);
    expect(isNavItemVisible(items[3]!, none)).toBe(false);
    expect(isNavItemVisible(items[3]!, { ...none, permissions: new Set(["action.execute"]) })).toBe(
      true,
    );
  });

  it("orders ungrouped first, then groups in the fixed order, dropping empty ones", () => {
    const sections = groupNavItems(items);
    expect(sections.map((s) => s.group)).toEqual([undefined, "Overview", "Reports"]);
  });

  it("picks the longest matching path as selected", () => {
    const nav: NavItem[] = [
      { to: "/", label: "Home" },
      { to: "/map", label: "Map" },
      { to: "/map/table", label: "Map table" },
    ];
    expect(selectedNavTo(nav, "/map/table")).toBe("/map/table");
    expect(selectedNavTo(nav, "/map")).toBe("/map");
    expect(selectedNavTo(nav, "/")).toBe("/");
    expect(selectedNavTo(nav, "/other")).toBeUndefined();
  });

  it("hides a permission-gated entry in the shell until the domains are known", () => {
    renderShell({
      account: accountWith("home-p", ["Viewer"]),
      respond: emptyList,
      path: "/",
      routes: {
        navItems: [
          { to: "/", label: "Home" },
          { to: "/x", label: "Gated", permission: "action.execute" },
        ],
      },
    });
    const nav = screen.getByRole("navigation", { name: "Primary" });
    expect(within(nav).queryByRole("link", { name: "Gated" })).toBeNull();
  });
});
