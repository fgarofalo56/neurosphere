import "@testing-library/jest-dom/vitest";
import { act, cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { RouterProvider, createMemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { QueryProvider, createApiClient } from "../../../api/index.js";
import { ConfigContext } from "../../../app/ConfigContext";
import type { AppConfig } from "../../../app/config";
import { useViewport } from "../hooks";
import { MapView } from "../MapPage";
import type { ViewportResponse } from "../types";
import { FilterBar } from "./FilterBar";
import { FILTER_STRINGS as S } from "./strings";
import { TAG_PATTERN, filtersToQuery, readFilters, useMapFilters } from "./useMapFilters";

// jsdom has no WebGL: the renderer is a recorder, as in map.test.tsx (sigma is never imported).
vi.mock("../renderer", () => ({
  createMapRenderer: vi.fn(() => ({
    fit: vi.fn(),
    update: vi.fn(),
    setEdgeOffset: vi.fn(),
    select: vi.fn(),
    setReducedMotion: vi.fn(),
    kill: vi.fn(),
  })),
}));
vi.mock("../../../auth/token", () => ({ getToken: vi.fn(() => Promise.resolve("t")) }));

class ResizeObserverStub {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}

const CONFIG: AppConfig = {
  cloud: "commercial",
  tenantId: "t",
  clientId: "c",
  apiBaseUrl: "http://api.test",
  apiScope: "api://x/.default",
};

const COUNTS = {
  by_kind: { agent: 5, model: 2, service: 1 },
  by_health: { ok: 6, failing: 2 },
  by_environment: { production: 4, staging: 3, unknown: 1 },
  by_cloud: { commercial: 7, unknown: 1 },
};

function viewport(label: string): ViewportResponse {
  return {
    domain_id: "d1",
    nodes: [
      {
        id: label,
        kind: "agent",
        label,
        cluster_id: null,
        member_count: null,
        metrics: {
          tokens: null,
          context_size: null,
          frequency: null,
          latency_p95_ms: null,
          health: "ok",
        },
      },
    ],
    edges: [],
    truncated: false,
    truncation_reason: null,
    next_cursor: null,
    coverage: { state: "complete", lag_seconds: 0, as_of: "2026-10-20T10:00:00Z" },
  };
}

function setup() {
  const requested: URL[] = [];
  const fetchImpl = vi.fn<typeof fetch>((input) => {
    const url = new URL(String(input));
    requested.push(url);
    const body = url.pathname.endsWith("/search")
      ? { domain_id: "d1", matches: [], counts: COUNTS, truncated: false, truncation_reason: null }
      : viewport(url.searchParams.size <= 1 ? "unfiltered" : "filtered");
    return Promise.resolve(new Response(JSON.stringify(body), { status: 200 }));
  });
  const client = createApiClient({
    baseUrl: "http://api.test",
    getToken: () => Promise.resolve("t"),
    fetchImpl,
    maxRetries: 0,
  });
  const viewports = () => requested.filter((u) => u.pathname.endsWith("/viewport"));
  return { client, requested, viewports };
}

/** The bar plus a viewport consumer, wired the way MapView wires them. */
function Harness() {
  const state = useMapFilters();
  const data = useViewport({ domainId: "d1", filters: state.toQuery() });
  return (
    <>
      <FilterBar domainId="d1" state={state} />
      <output data-testid="first-node">{data.data?.nodes[0]?.label ?? "none"}</output>
    </>
  );
}

function mount(initial: string, element = <Harness />) {
  const ctx = setup();
  const router = createMemoryRouter([{ path: "/map", element }], { initialEntries: [initial] });
  const utils = render(
    <ConfigContext.Provider value={CONFIG}>
      <QueryProvider client={ctx.client}>
        <RouterProvider router={router} />
      </QueryProvider>
    </ConfigContext.Provider>,
  );
  return { ...ctx, ...utils, router };
}

beforeEach(() => {
  vi.stubGlobal("ResizeObserver", ResizeObserverStub);
  vi.stubGlobal("WebSocket", class {});
  vi.stubGlobal(
    "matchMedia",
    vi.fn(() => ({
      matches: false,
      media: "",
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })),
  );
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

/** Options arrive with the search counts; selecting before they load would find no option. */
async function optionsLoaded(): Promise<void> {
  await waitFor(() =>
    expect(
      within(screen.getByLabelText("Environment")).getByText("Production (4)"),
    ).toBeInTheDocument(),
  );
}

describe("filter parsing", () => {
  it("mirrors the PRP-70 tag grammar and drops invalid URL values", () => {
    expect(TAG_PATTERN.source).toBe("^[a-z0-9][a-z0-9._-]{0,62}$");
    const f = readFilters(
      new URLSearchParams(
        "environment=production&cloud=mars&tag=Bad Tag&health=failing&node_type=agent",
      ),
    );
    expect(filtersToQuery(f)).toEqual({
      environment: "production",
      health: "failing",
      node_type: "agent",
    });
  });
});

describe("FilterBar", () => {
  it("renders options with counts from the search route, only values the server accepts", async () => {
    mount("/map");
    const env = await screen.findByLabelText("Environment");
    await waitFor(() => expect(within(env).getByText("Production (4)")).toBeInTheDocument());
    expect(within(env).getByText("Staging (3)")).toBeInTheDocument();
    // "unknown" cloud is counted by the server but rejected as a filter value, so it is not offered.
    const cloud = screen.getByLabelText("Cloud");
    expect(within(cloud).getByText("Commercial (7)")).toBeInTheDocument();
    expect(within(cloud).queryByText(/Unknown/)).toBeNull();
    expect(within(screen.getByLabelText("Node type")).getByText("Agent (5)")).toBeInTheDocument();
    expect(within(screen.getByLabelText("Health")).getByText("Failing (2)")).toBeInTheDocument();
    expect(screen.getByTestId("map-filter-bar")).toBeInTheDocument();
  });

  it("asks the search route for counts without filters", async () => {
    const { requested } = mount("/map?environment=staging");
    await screen.findByLabelText("Environment");
    await waitFor(() => expect(requested.some((u) => u.pathname.endsWith("/search"))).toBe(true));
    const search = requested.find((u) => u.pathname.endsWith("/search")) as URL;
    expect(search.pathname).toBe("/api/v1/map/domains/d1/search");
    expect(search.searchParams.get("limit")).toBe("1");
    expect(search.searchParams.has("environment")).toBe(false);
  });

  it("sends the filter as a viewport parameter, and a changed filter is a new request", async () => {
    const user = userEvent.setup();
    const { viewports, router } = mount("/map");
    await screen.findByText("unfiltered");
    await optionsLoaded();
    expect(viewports()).toHaveLength(1);
    expect(viewports()[0]?.searchParams.has("environment")).toBe(false);

    await user.selectOptions(screen.getByLabelText("Environment"), "production");
    await screen.findByText("filtered");
    expect(viewports()).toHaveLength(2);
    expect(viewports()[1]?.searchParams.get("environment")).toBe("production");
    expect(router.state.location.search).toBe("?environment=production");

    await user.selectOptions(screen.getByLabelText("Health"), "failing");
    await waitFor(() => expect(viewports()).toHaveLength(3));
    const third = viewports()[2] as URL;
    expect(third.searchParams.get("environment")).toBe("production");
    expect(third.searchParams.get("health")).toBe("failing");
  });

  it("shows the applied count and clears everything", async () => {
    const user = userEvent.setup();
    const { router, viewports } = mount("/map?environment=production&health=failing");
    const clear = await screen.findByRole("button", { name: "2 filters applied, clear all" });
    expect(screen.getByTestId("map-filter-bar")).toHaveAttribute("data-active-filters", "2");
    await user.click(clear);
    await waitFor(() => expect(router.state.location.search).toBe(""));
    expect(screen.queryByRole("button", { name: /clear all/ })).toBeNull();
    await waitFor(() => expect(viewports().at(-1)?.searchParams.has("health")).toBe(false));
  });

  it("uses the singular for one filter", async () => {
    mount("/map?cloud=commercial");
    expect(await screen.findByRole("button", { name: S.clearAll(1) })).toBeInTheDocument();
    expect(S.clearAll(1)).toBe("1 filter applied, clear all");
  });

  it("blocks an invalid tag in the field before any request", async () => {
    const user = userEvent.setup();
    const { viewports, router } = mount("/map");
    await screen.findByText("unfiltered");
    const before = viewports().length;
    await user.type(screen.getByLabelText(/^Tag/), "Not A Tag!{Enter}");
    expect(await screen.findByText(S.tagInvalid)).toBeInTheDocument();
    expect(router.state.location.search).toBe("");
    // Give a wrongly issued request time to appear before asserting there is none.
    await act(async () => {
      await new Promise((r) => setTimeout(r, 50));
    });
    expect(viewports()).toHaveLength(before);
  });

  it("applies a valid tag", async () => {
    const user = userEvent.setup();
    const { viewports, router } = mount("/map");
    await screen.findByText("unfiltered");
    await user.type(screen.getByLabelText(/^Tag/), "finance.team{Enter}");
    await waitFor(() => expect(router.state.location.search).toBe("?tag=finance.team"));
    await waitFor(() => expect(viewports().at(-1)?.searchParams.get("tag")).toBe("finance.team"));
  });
});

describe("URL state", () => {
  it("survives a reload: a fresh router at that URL restores controls and request", async () => {
    const { router, unmount } = mount("/map");
    await screen.findByText("unfiltered");
    await optionsLoaded();
    await userEvent.setup().selectOptions(screen.getByLabelText("Node type"), "agent");
    await waitFor(() => expect(router.state.location.search).toBe("?node_type=agent"));
    unmount();

    const reloaded = mount(`/map${router.state.location.search}`);
    const select = (await screen.findByLabelText("Node type")) as HTMLSelectElement;
    await waitFor(() => expect(select.value).toBe("agent"));
    await screen.findByText("filtered");
    expect(reloaded.viewports()[0]?.searchParams.get("node_type")).toBe("agent");
  });

  it("restores the previous filter with the back button", async () => {
    const user = userEvent.setup();
    const { router } = mount("/map?domain_id=d1");
    const env = (await screen.findByLabelText("Environment")) as HTMLSelectElement;
    await optionsLoaded();
    await user.selectOptions(env, "production");
    await waitFor(() => expect(env.value).toBe("production"));
    await user.selectOptions(env, "staging");
    await waitFor(() => expect(env.value).toBe("staging"));
    // Other parameters are preserved.
    expect(new URLSearchParams(router.state.location.search).get("domain_id")).toBe("d1");

    await act(async () => {
      await router.navigate(-1);
    });
    await waitFor(() => expect(env.value).toBe("production"));
  });
});

describe("MapView wiring", () => {
  it("renders the bar in the toolbar and refetches the viewport with the filters", async () => {
    const user = userEvent.setup();
    const { viewports } = mount("/map", <MapView domainId="d1" />);
    await screen.findByTestId("map-filter-bar");
    await waitFor(() => expect(viewports()).toHaveLength(1));
    await optionsLoaded();
    await user.selectOptions(screen.getByLabelText("Cloud"), "commercial");
    await waitFor(() => expect(viewports().length).toBeGreaterThanOrEqual(2));
    expect(viewports().at(-1)?.searchParams.get("cloud")).toBe("commercial");
    expect(viewports().at(-1)?.searchParams.get("node_budget")).toBe("2000");
    // The bar survives the refetch (it did not unmount into the loading state).
    expect(screen.getByTestId("map-filter-bar")).toBeInTheDocument();
  });
});
