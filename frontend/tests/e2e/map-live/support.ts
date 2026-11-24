import type { APIRequestContext, Page } from "@playwright/test";
import { expect } from "../../e2e-support/fixtures.ts";
import { MOCK_API_URL } from "../../e2e-support/fixtures.ts";
import {
  DOMAIN_MAP_INCIDENT,
  INCIDENT_IDS,
  incidentDomain,
  type ControlBody,
} from "../../mock-api/features/map-topology.ts";

// PRP-77 item 6: shared helpers of the map-live specs. Each spec that mutates the fixture uses its
// own domain instance (`incidentDomain(suffix)`), so specs run in parallel without sharing state.

export { DOMAIN_MAP_INCIDENT, INCIDENT_IDS, incidentDomain };

/** The seeded token is a Viewer persona; the mock only needs a recognised fake token. */
const FAKE_TOKEN = "ns-e2e-fake-token.admin";

export function mapUrl(domain: string, query: Record<string, string> = {}): string {
  const params = new URLSearchParams({ domain_id: domain, ...query });
  return `/map?${params.toString()}`;
}

export function tableUrl(domain: string, query: Record<string, string> = {}): string {
  const params = new URLSearchParams({ domain_id: domain, ...query });
  return `/map/table?${params.toString()}`;
}

/** Drives the mock's test-only control route (flip health, add a node, reset). */
export async function control(
  request: APIRequestContext,
  domain: string,
  body: ControlBody,
): Promise<void> {
  const response = await request.post(
    `${MOCK_API_URL}/api/v1/map/domains/${encodeURIComponent(domain)}/__e2e/control`,
    { data: body, headers: { authorization: `Bearer ${FAKE_TOKEN}` } },
  );
  expect(response.status(), await response.text()).toBe(200);
}

// The mock API does not serve the realtime gateway. This init script replaces ONLY the gateway
// WebSocket (the real client code still runs) with a fake that speaks the wire contract: it needs
// the `ns.bearer` subprotocol plus a token and answers `subscribe` with `subscribed`. The pattern
// is copied from map-perf.spec.ts (that file is owned by another lane and is not imported).
// Test control lives on window.__nsFakeGateway; it exists only in these specs and never ships.
export function installFakeGateway(): void {
  const RealWebSocket = window.WebSocket;
  const sockets: FakeGatewaySocket[] = [];
  let seq = 0;

  class FakeGatewaySocket {
    onopen: ((e: unknown) => void) | null = null;
    onmessage: ((e: { data: unknown }) => void) | null = null;
    onclose: ((e: { code: number }) => void) | null = null;
    onerror: ((e: unknown) => void) | null = null;
    private closed = false;
    domain = "";
    private readonly protocols: string[];

    constructor(_url: string, protocols: string[]) {
      this.protocols = protocols;
      sockets.push(this);
      setTimeout(() => {
        if (this.protocols[0] !== "ns.bearer" || !this.protocols[1]) return this.dropWith(4401);
        this.onopen?.({});
      }, 0);
    }

    emit(message: object): void {
      if (!this.closed) this.onmessage?.({ data: JSON.stringify(message) });
    }

    send(data: string): void {
      const m = JSON.parse(data) as { type?: string; domain_id?: string };
      if (m.type !== "subscribe" || typeof m.domain_id !== "string") return;
      this.domain = m.domain_id;
      this.emit({ type: "subscribed", domain_id: this.domain });
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

  const latest = (): FakeGatewaySocket => {
    const s = sockets.at(-1);
    if (s === undefined) throw new Error("no gateway socket yet");
    return s;
  };
  (window as unknown as { __nsFakeGateway: unknown }).__nsFakeGateway = {
    /** A `delta` for the subscribed domain: nodes carry the changed health. */
    sendDelta: (nodes: object[]) => {
      seq += 1;
      const s = latest();
      s.emit({
        type: "delta",
        domain_id: s.domain,
        seq,
        nodes,
        edges: [],
        coverage: { state: "complete", lag_seconds: 0, as_of: null },
        emitted_at: new Date().toISOString(),
      });
    },
    /** A `topology` notice for the subscribed domain. */
    sendTopology: (refetch: boolean, entityIds: string[]) => {
      seq += 1;
      const s = latest();
      s.emit({
        type: "topology",
        domain_id: s.domain,
        seq,
        changed_at: new Date().toISOString(),
        change_kinds: ["node_added"],
        entity_ids: entityIds,
        refetch,
        truncated: false,
        emitted_at: new Date().toISOString(),
      });
    },
  };
}

interface DeltaNode {
  id: string;
  kind: string;
  label: string;
  health: string;
}

/** Sends one live delta that turns the given nodes to the given health. */
export async function sendHealthDelta(page: Page, nodes: readonly DeltaNode[]): Promise<void> {
  await page.evaluate(
    (items) => {
      const gateway = (window as unknown as { __nsFakeGateway: { sendDelta(n: object[]): void } })
        .__nsFakeGateway;
      gateway.sendDelta(
        items.map((n) => ({
          id: n.id,
          kind: n.kind,
          label: n.label,
          cluster_id: null,
          member_count: null,
          metrics: {
            tokens: null,
            context_size: null,
            frequency: null,
            latency_p95_ms: null,
            health: n.health,
          },
        })),
      );
    },
    [...nodes],
  );
}

export async function sendTopology(
  page: Page,
  refetch: boolean,
  entityIds: readonly string[],
): Promise<void> {
  await page.evaluate(
    ([flag, ids]) => {
      (
        window as unknown as { __nsFakeGateway: { sendTopology(r: boolean, e: string[]): void } }
      ).__nsFakeGateway.sendTopology(flag as boolean, ids as string[]);
    },
    [refetch, [...entityIds]] as const,
  );
}

/** Opens the map and waits until the canvas holds nodes and the fake gateway is live. */
export async function openLiveMap(page: Page, url: string): Promise<void> {
  await page.addInitScript(installFakeGateway);
  await page.goto(url);
  await expect(page.getByTestId("live-status")).toHaveAttribute("data-live-status", "live", {
    timeout: 20_000,
  });
  await expect(page.getByTestId("node-count")).not.toContainText("0 nodes");
}

/** Picks a search result by typing and using the keyboard only: Arrow Down to it, then Enter. */
export async function searchAndSelect(page: Page, text: string, resultName: string): Promise<void> {
  const box = page.getByTestId("map-search");
  await box.click();
  await box.fill(text);
  const result = page.getByTestId("map-search-result").filter({ hasText: resultName });
  await expect(result).toBeVisible();
  const resultId = await result.getAttribute("id");
  for (let i = 0; i < 20; i += 1) {
    if ((await box.getAttribute("aria-activedescendant")) === resultId) break;
    await page.keyboard.press("ArrowDown");
  }
  await expect(box).toHaveAttribute("aria-activedescendant", resultId ?? "");
  await page.keyboard.press("Enter");
}
