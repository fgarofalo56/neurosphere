import os from "node:os";

// Helpers shared by map-perf.spec.ts (frame rate) and map-latency.spec.ts (interaction latency):
// both render the same 2000-node fixture against the same fake realtime gateway.

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

export function installFakeGateway(initialCoverage: string): void {
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

export interface HostInfo {
  platform: string;
  release: string;
  arch: string;
  cpuModel: string;
  cpuCount: number;
  totalMemBytes: number;
  node: string;
}

/** Host facts captured in the Node test process (OS, CPU model, logical cores, RAM). */
export function hostInfo(): HostInfo {
  const cpus = os.cpus();
  return {
    platform: os.platform(),
    release: os.release(),
    arch: os.arch(),
    cpuModel: cpus[0]?.model ?? "unknown",
    cpuCount: cpus.length,
    totalMemBytes: os.totalmem(),
    node: process.version,
  };
}
