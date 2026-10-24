import { act, cleanup, screen } from "@testing-library/react";
import { afterEach, beforeAll, beforeEach, describe, expect, it } from "vitest";
import { sandboxRoutes } from "../features/sandbox/routes";
import { STRINGS } from "../features/sandbox/strings";
import { useSandboxStore } from "../features/sandbox/store";
import { accountWith, domainEntry, renderShell, stubResizeObserver } from "./test-support";

beforeAll(stubResizeObserver);
beforeEach(() => {
  window.localStorage.clear();
  useSandboxStore.setState({ enabled: false });
});
afterEach(cleanup);

function list(): Response {
  return new Response(JSON.stringify({ items: [domainEntry("d:1", "One")] }), { status: 200 });
}

function renderAt(path: string) {
  return renderShell({
    account: accountWith(`home-${crypto.randomUUID()}`, ["Viewer"]),
    respond: list,
    path,
    routes: {
      extraRoutes: [
        ...sandboxRoutes,
        { path: "page", element: <h1>Some page</h1> },
        { path: "other", element: <h1>Other page</h1> },
      ],
    },
  });
}

describe("sandbox banner in the shell", () => {
  it("renders on every route while sandbox mode is on", () => {
    useSandboxStore.setState({ enabled: true });
    for (const path of ["/", "/page", "/other", "/sandbox", "/no-such-route"]) {
      renderAt(path);
      const banner = screen.getByRole("region", { name: STRINGS.bannerName });
      expect(banner).toBeInTheDocument();
      // Before <main>, so it precedes the page content on every route.
      const main = screen.getByRole("main");
      expect(banner.compareDocumentPosition(main) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
      expect(screen.getAllByRole("region", { name: STRINGS.bannerName })).toHaveLength(1);
      cleanup();
    }
  });

  it("is absent on every route while sandbox mode is off", () => {
    for (const path of ["/", "/page", "/sandbox"]) {
      renderAt(path);
      expect(screen.queryByRole("region", { name: STRINGS.bannerName })).toBeNull();
      cleanup();
    }
  });

  it("appears and disappears live when the mode changes", () => {
    renderAt("/page");
    expect(screen.queryByTestId("sandbox-banner")).toBeNull();
    act(() => {
      useSandboxStore.getState().setEnabled(true);
    });
    expect(screen.getByRole("region", { name: STRINGS.bannerName })).toBeInTheDocument();
    act(() => {
      useSandboxStore.getState().setEnabled(false);
    });
    expect(screen.queryByTestId("sandbox-banner")).toBeNull();
  });
});
