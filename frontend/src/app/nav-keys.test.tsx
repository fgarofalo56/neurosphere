import { cleanup, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, describe, expect, it } from "vitest";
import { accountWith, domainEntry, renderShell, stubResizeObserver } from "./test-support";

/** #94: arrow keys move focus between the navigation links (no Tabster Mover in the nav). */

beforeAll(stubResizeObserver);
afterEach(() => {
  cleanup();
  localStorage.clear();
});

const NAV_ITEMS = [
  { to: "/", label: "Home", group: "Overview" },
  { to: "/page", label: "Some page", group: "Quality" },
  { to: "/other", label: "Other page", group: "Quality" },
];

async function renderNav() {
  renderShell({
    account: accountWith(`home-${crypto.randomUUID()}`, ["Viewer"]),
    respond: () =>
      new Response(JSON.stringify({ items: [domainEntry("commercial:t:s:domain:a", "A")] })),
    routes: {
      extraRoutes: [
        { path: "page", element: <p>page</p> },
        { path: "other", element: <p>other</p> },
      ],
      navItems: NAV_ITEMS,
    },
  });
  const nav = await screen.findByRole("navigation", { name: "Primary" });
  return within(nav).getAllByRole("link");
}

describe("navigation arrow keys", () => {
  it("ArrowDown and ArrowUp move focus between links and stop at the ends", async () => {
    const links = await renderNav();
    const user = userEvent.setup();
    expect(links).toHaveLength(3);
    links[0]?.focus();
    await user.keyboard("{ArrowDown}");
    expect(links[1]).toHaveFocus();
    await user.keyboard("{ArrowDown}{ArrowDown}");
    expect(links[2]).toHaveFocus();
    await user.keyboard("{ArrowUp}");
    expect(links[1]).toHaveFocus();
    await user.keyboard("{ArrowUp}{ArrowUp}");
    expect(links[0]).toHaveFocus();
  });

  it("Home and End jump to the first and last link", async () => {
    const links = await renderNav();
    const user = userEvent.setup();
    links[1]?.focus();
    await user.keyboard("{End}");
    expect(links[2]).toHaveFocus();
    await user.keyboard("{Home}");
    expect(links[0]).toHaveFocus();
  });

  it("leaves every link in the tab order", async () => {
    const links = await renderNav();
    for (const link of links) expect(link).not.toHaveAttribute("tabindex", "-1");
  });
});
