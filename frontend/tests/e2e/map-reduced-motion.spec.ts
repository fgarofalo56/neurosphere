import type { Page } from "@playwright/test";
import { expect, test } from "../e2e-support/fixtures.ts";
import { DOMAIN_OK } from "../mock-api/server.ts";

// PRP-18 item 3: edge animation honours prefers-reduced-motion AND the in-app toggle, and only
// OBSERVED edges ever animate. The signals are attributes on the map container:
//   data-edge-animation   "on" | "off"
//   data-animated-edges   number of edges the animator moves (observed only, 0 when off)
//   data-animation-frames frames the animator has run since it was (re)started

const MAP_URL = `/map?domain_id=${encodeURIComponent(DOMAIN_OK)}`;

// The mock API does not serve the realtime gateway. This init script replaces ONLY the gateway
// WebSocket (the real client code still runs) with a fake that speaks the wire contract: it
// requires the `ns.bearer` subprotocol plus a token, answers `subscribe` with `subscribed` and one
// `delta` for the addressed domain carrying the coverage state below. Test control lives on
// window.__nsFakeGateway; it exists only in these specs and never ships.
interface FakeGatewayControl {
  coverage: string;
  refuse: boolean;
  sockets: { dropWith(code: number): void; deliver(state: string): void }[];
}

function installFakeGateway(initialCoverage: string): void {
  const RealWebSocket = window.WebSocket;
  const control: FakeGatewayControl = { coverage: initialCoverage, refuse: false, sockets: [] };
  let seq = 0;

  class FakeGatewaySocket {
    onopen: ((e: unknown) => void) | null = null;
    onmessage: ((e: { data: unknown }) => void) | null = null;
    onclose: ((e: { code: number }) => void) | null = null;
    onerror: ((e: unknown) => void) | null = null;
    private closed = false;
    private domain = "";
    private readonly protocols: string[];

    constructor(_url: string, protocols: string[]) {
      this.protocols = protocols;
      control.sockets.push(this);
      setTimeout(() => {
        if (control.refuse) return this.dropWith(1006);
        if (this.protocols[0] !== "ns.bearer" || !this.protocols[1]) return this.dropWith(4401);
        this.onopen?.({});
      }, 0);
    }

    private emit(message: object): void {
      if (!this.closed) this.onmessage?.({ data: JSON.stringify(message) });
    }

    deliver(state: string): void {
      seq += 1;
      this.emit({
        type: "delta",
        domain_id: this.domain,
        seq,
        nodes: [],
        edges: [],
        coverage: { state, lag_seconds: state === "delayed" ? 300 : 0, as_of: null },
        emitted_at: new Date().toISOString(),
      });
    }

    send(data: string): void {
      const m = JSON.parse(data) as { type?: string; domain_id?: string };
      if (m.type !== "subscribe" || typeof m.domain_id !== "string") return;
      this.domain = m.domain_id;
      this.emit({ type: "subscribed", domain_id: this.domain });
      this.deliver(control.coverage);
    }

    dropWith(code: number): void {
      if (this.closed) return;
      this.closed = true;
      this.onclose?.({ code });
    }

    close(): void {
      this.closed = true;
    }
  }

  window.WebSocket = function (url: string | URL, protocols?: string | string[]) {
    if (!String(url).includes("/api/v1/realtime/ws")) return new RealWebSocket(url, protocols);
    return new FakeGatewaySocket(String(url), Array.isArray(protocols) ? protocols : []);
  } as unknown as typeof WebSocket;
  (window as unknown as { __nsFakeGateway: unknown }).__nsFakeGateway = {
    /** Every later connection attempt closes at once (1006): the gateway is gone. */
    refuseNewConnections: () => {
      control.refuse = true;
    },
    dropAll: (code: number) => control.sockets.forEach((s) => s.dropWith(code)),
    sendDelta: (state: string) => {
      control.coverage = state;
      control.sockets.at(-1)?.deliver(state);
    },
  };
}

type Gateway = {
  refuseNewConnections(): void;
  dropAll(code: number): void;
  sendDelta(state: string): void;
};

const refuseNewConnections = (page: Page): Promise<void> =>
  page.evaluate(() =>
    (window as unknown as { __nsFakeGateway: Gateway }).__nsFakeGateway.refuseNewConnections(),
  );
const dropAll = (page: Page, code: number): Promise<void> =>
  page.evaluate(
    (c) => (window as unknown as { __nsFakeGateway: Gateway }).__nsFakeGateway.dropAll(c),
    code,
  );
const sendDelta = (page: Page, state: string): Promise<void> =>
  page.evaluate(
    (s) => (window as unknown as { __nsFakeGateway: Gateway }).__nsFakeGateway.sendDelta(s),
    state,
  );

interface ViewportBody {
  edges: { provenance: string }[];
}

async function openMap(page: Page): Promise<{ observed: number; others: number }> {
  const viewport = page.waitForResponse((r) => r.url().includes("/viewport") && r.status() === 200);
  await page.goto(MAP_URL);
  const body = (await (await viewport).json()) as ViewportBody;
  await expect(page.getByTestId("map-canvas")).toHaveAttribute("data-node-count", /^[1-9]/);
  const observed = body.edges.filter((e) => e.provenance === "observed").length;
  return { observed, others: body.edges.length - observed };
}

const frames = async (page: Page): Promise<number> =>
  Number(await page.getByTestId("map-canvas").getAttribute("data-animation-frames"));

test.describe("map reduced motion", () => {
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(installFakeGateway, "complete");
  });

  test("no preference: only observed edges animate", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "no-preference" });
    const { observed, others } = await openMap(page);
    await expect(page.getByTestId("live-status")).toHaveAttribute("data-live-status", "live");
    expect(observed).toBeGreaterThan(0);
    expect(others).toBeGreaterThan(0); // declared and inferred edges exist and stay static
    const canvas = page.getByTestId("map-canvas");
    await expect(canvas).toHaveAttribute("data-edge-animation", "on");
    await expect(canvas).toHaveAttribute("data-animated-edges", String(observed));
    await expect.poll(() => frames(page)).toBeGreaterThan(3);
    await expect(page.getByTestId("animation-status")).toHaveText("Observed edges animate");
  });

  test("system prefers-reduced-motion: no animation frames at all", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await openMap(page);
    const canvas = page.getByTestId("map-canvas");
    await expect(canvas).toHaveAttribute("data-edge-animation", "off");
    await expect(canvas).toHaveAttribute("data-animated-edges", "0");
    await page.waitForTimeout(600);
    expect(await frames(page)).toBe(0);
    await expect(page.getByTestId("animation-status")).toHaveText(
      "Edge animation paused: reduced motion",
    );
    // The system preference cannot be switched back on from the app.
    const toggle = page.getByRole("switch", { name: /reduce motion/i });
    await expect(toggle).toBeChecked();
    await expect(toggle).toBeDisabled();
  });

  test("in-app toggle turns animation off and back on", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "no-preference" });
    const { observed } = await openMap(page);
    await expect(page.getByTestId("live-status")).toHaveAttribute("data-live-status", "live");
    const canvas = page.getByTestId("map-canvas");
    const toggle = page.getByRole("switch", { name: /reduce motion/i });
    await expect(canvas).toHaveAttribute("data-edge-animation", "on");

    await toggle.click();
    await expect(canvas).toHaveAttribute("data-edge-animation", "off");
    await expect(canvas).toHaveAttribute("data-animated-edges", "0");
    await page.waitForTimeout(400);
    expect(await frames(page)).toBe(0);

    await toggle.click();
    await expect(canvas).toHaveAttribute("data-edge-animation", "on");
    await expect(canvas).toHaveAttribute("data-animated-edges", String(observed));
    await expect.poll(() => frames(page)).toBeGreaterThan(3);
  });
});

// Animation is a claim that the data is live. It must stop the moment that stops being true.
test.describe("map edge animation follows live state", () => {
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(installFakeGateway, "complete");
    await page.emulateMedia({ reducedMotion: "no-preference" });
  });

  test("off after the socket closes, with the reason shown", async ({ page }) => {
    await openMap(page);
    const canvas = page.getByTestId("map-canvas");
    await expect(canvas).toHaveAttribute("data-edge-animation", "on");
    await refuseNewConnections(page);
    await dropAll(page, 1006);
    await expect(canvas).toHaveAttribute("data-edge-animation", "off");
    await expect(canvas).toHaveAttribute("data-animated-edges", "0");
    await expect(page.getByTestId("animation-status")).toHaveText(
      "Edge animation paused: live updates not connected",
    );
    await page.waitForTimeout(400);
    expect(await frames(page)).toBe(0);
  });

  test("off and the data removed after access is revoked (4403)", async ({ page }) => {
    await openMap(page);
    const canvas = page.getByTestId("map-canvas");
    await expect(canvas).toHaveAttribute("data-edge-animation", "on");
    await dropAll(page, 4403);
    await expect(canvas).toHaveAttribute("data-edge-animation", "off");
    await expect(page.getByTestId("access-revoked")).toBeVisible();
    await expect(canvas).toHaveAttribute("data-node-count", "0");
    await page.waitForTimeout(400);
    expect(await frames(page)).toBe(0);
  });

  test("off while coverage is delayed, on again when complete", async ({ page }) => {
    await openMap(page);
    const canvas = page.getByTestId("map-canvas");
    await expect(canvas).toHaveAttribute("data-edge-animation", "on");
    await sendDelta(page, "delayed");
    await expect(canvas).toHaveAttribute("data-edge-animation", "off");
    await expect(page.getByTestId("animation-status")).toHaveText(
      "Edge animation paused: data delayed",
    );
    await page.waitForTimeout(400);
    expect(await frames(page)).toBe(0);
    await sendDelta(page, "complete");
    await expect(canvas).toHaveAttribute("data-edge-animation", "on");
    await expect.poll(() => frames(page)).toBeGreaterThan(3);
  });
});

// The same page, but the labels that must never be missing from the map (coverage, truncation,
// the table alternative, the live-updates state). The mock API has no realtime gateway, so the
// page must say live updates are unavailable instead of pretending to be live.
test.describe("map page states", () => {
  test("labels coverage and truncation, links to the table, and says live is unavailable", async ({
    page,
  }) => {
    await openMap(page);
    await expect(page.getByTestId("coverage-label")).toHaveAttribute(
      "data-coverage-state",
      "partial",
    );
    await expect(page.getByTestId("truncation-banner")).toContainText("node budget reached");
    const table = page.getByRole("link", { name: "View as table" });
    await expect(table).toBeVisible();
    await expect(table).toHaveAttribute("href", /^\/map\/table\?domain_id=/);
    await expect(page.getByRole("region", { name: /Agent topology map/ })).toBeVisible();
    await expect(page.getByTestId("live-status")).toHaveAttribute(
      "data-live-status",
      "unavailable",
      { timeout: 15_000 },
    );
    await expect(page.getByTestId("map-legend")).toContainText("no data (never shown as 0)");
  });

  test("expands a cluster and labels the delayed page", async ({ page }) => {
    await openMap(page);
    const canvas = page.getByTestId("map-canvas");
    await canvas.scrollIntoViewIfNeeded();
    const box = await canvas.boundingBox();
    if (box === null) throw new Error("map has no box");
    const at = await page.evaluate(() => {
      const hook = (
        document.querySelector('[data-testid="map-canvas"]') as HTMLElement & {
          __nsMap: {
            sigma: {
              getNodeDisplayData(id: string): { x: number; y: number };
              framedGraphToViewport(c: { x: number; y: number }): { x: number; y: number };
            };
          };
        }
      ).__nsMap;
      const d = hook.sigma.getNodeDisplayData("cluster:agents");
      return hook.sigma.framedGraphToViewport({ x: d.x, y: d.y });
    });
    await page.mouse.click(box.x + at.x, box.y + at.y);
    const panel = page.getByTestId("node-panel");
    await expect(panel).toBeVisible();
    const before = Number(
      (await page.getByTestId("node-count").innerText()).match(/^(\d+) nodes/)?.[1],
    );
    await panel.getByRole("button", { name: "Expand cluster" }).click();
    // Page 1 of the cluster; page 2 (served with ?cursor=page-2) is the delayed one.
    await panel.getByRole("button", { name: "Load more" }).click();
    await expect(page.getByTestId("coverage-label")).toHaveAttribute(
      "data-coverage-state",
      "delayed",
    );
    await expect(page.getByTestId("coverage-label")).toContainText("300 s behind");
    const after = Number(
      (await page.getByTestId("node-count").innerText()).match(/^(\d+) nodes/)?.[1],
    );
    expect(after).toBeGreaterThan(before);
  });
});
