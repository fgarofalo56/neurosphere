/**
 * Browser client for the scoped realtime gateway (/api/v1/realtime/ws). The bearer token rides in
 * the Sec-WebSocket-Protocol header (`ns.bearer`, <token>), never in the URL. Server messages of
 * unknown type are ignored (the gateway also sends subscribed/unsubscribed/pong). Close 4403
 * (forbidden or revoked) is final: this client never reconnects after it.
 */
import type { Coverage, DeltaMessage } from "./types";
import { parseEdge, parseNode } from "./mapGraph";

export const REALTIME_PATH = "/api/v1/realtime/ws";
export const BEARER_SUBPROTOCOL = "ns.bearer";

export const CLOSE_UNAUTHENTICATED = 4401;
export const CLOSE_FORBIDDEN = 4403;
export const CLOSE_BUDGET = 4429;

export type LiveStatus =
  | "connecting"
  | "live"
  | "reconnecting"
  | "disconnected"
  | "unavailable"
  | "unauthenticated"
  | "revoked";

export interface WebSocketLike {
  onopen: ((event: unknown) => void) | null;
  onmessage: ((event: { data: unknown }) => void) | null;
  onclose: ((event: { code: number; reason?: string }) => void) | null;
  onerror: ((event: unknown) => void) | null;
  send(data: string): void;
  close(code?: number, reason?: string): void;
}

export type SocketFactory = (url: string, protocols: string[]) => WebSocketLike;

export const defaultSocketFactory: SocketFactory = (url, protocols) =>
  new WebSocket(url, protocols) as unknown as WebSocketLike;

/** http(s) API base URL -> ws(s) gateway URL. */
export function realtimeUrl(apiBaseUrl: string): string {
  const base = apiBaseUrl.replace(/\/+$/, "");
  if (base.startsWith("https://")) return `wss://${base.slice("https://".length)}${REALTIME_PATH}`;
  if (base.startsWith("http://")) return `ws://${base.slice("http://".length)}${REALTIME_PATH}`;
  const proto = typeof location !== "undefined" && location.protocol === "https:" ? "wss" : "ws";
  const host = typeof location !== "undefined" ? location.host : "";
  return `${proto}://${host}${base}${REALTIME_PATH}`;
}

export type ServerMessage =
  | { kind: "subscribed" }
  | { kind: "delta"; delta: DeltaMessage }
  | { kind: "error"; code: string }
  | { kind: "ignored" };

function parseCoverage(raw: unknown): Coverage | null {
  if (typeof raw !== "object" || raw === null) return null;
  const r = raw as Record<string, unknown>;
  const states = ["complete", "partial", "delayed", "unknown"];
  if (typeof r["state"] !== "string" || !states.includes(r["state"])) return null;
  return {
    state: r["state"] as Coverage["state"],
    lag_seconds: typeof r["lag_seconds"] === "number" ? r["lag_seconds"] : null,
    as_of: typeof r["as_of"] === "string" ? r["as_of"] : null,
  };
}

/** Parses one server frame; anything unrecognised becomes `ignored`, never an exception. */
export function parseServerMessage(data: unknown): ServerMessage {
  if (typeof data !== "string") return { kind: "ignored" };
  let raw: unknown;
  try {
    raw = JSON.parse(data);
  } catch {
    return { kind: "ignored" };
  }
  if (typeof raw !== "object" || raw === null) return { kind: "ignored" };
  const m = raw as Record<string, unknown>;
  switch (m["type"]) {
    case "subscribed":
      return { kind: "subscribed" };
    case "error":
      return { kind: "error", code: typeof m["code"] === "string" ? m["code"] : "unknown" };
    case "delta": {
      const coverage = parseCoverage(m["coverage"]);
      if (typeof m["domain_id"] !== "string" || typeof m["seq"] !== "number" || coverage === null) {
        return { kind: "ignored" };
      }
      const nodes = Array.isArray(m["nodes"]) ? m["nodes"] : [];
      const edges = Array.isArray(m["edges"]) ? m["edges"] : [];
      return {
        kind: "delta",
        delta: {
          type: "delta",
          domain_id: m["domain_id"],
          seq: m["seq"],
          nodes: nodes.map(parseNode).filter((n) => n !== null),
          edges: edges.map(parseEdge).filter((e) => e !== null),
          coverage,
          emitted_at: typeof m["emitted_at"] === "string" ? m["emitted_at"] : "",
        },
      };
    }
    default:
      return { kind: "ignored" };
  }
}

export interface LiveClientOptions {
  readonly url: string;
  readonly domainId: string;
  readonly getToken: () => Promise<string>;
  readonly onStatus: (status: LiveStatus) => void;
  readonly onDelta: (delta: DeltaMessage) => void;
  readonly onError?: (code: string) => void;
  readonly socketFactory?: SocketFactory;
  /** Injected so tests run without real timers. */
  readonly setTimer?: (callback: () => void, ms: number) => number;
  readonly clearTimer?: (handle: number) => void;
  /** Attempts before giving up when the gateway was never reachable / was lost. */
  readonly maxAttempts?: number;
}

export interface LiveClient {
  start(): void;
  stop(): void;
}

const BACKOFF_MS = [1000, 2000, 4000, 8000, 16000];
const BUDGET_BACKOFF_MS = 30_000;

export function createLiveClient(options: LiveClientOptions): LiveClient {
  const factory = options.socketFactory ?? defaultSocketFactory;
  const setTimer = options.setTimer ?? ((cb, ms) => window.setTimeout(cb, ms));
  const clearTimer = options.clearTimer ?? ((h) => window.clearTimeout(h));
  const maxAttempts = options.maxAttempts ?? 4;

  let stopped = true;
  let socket: WebSocketLike | null = null;
  let timer: number | null = null;
  let attempts = 0;
  let everConnected = false;
  let authRetried = false;
  let lastSeq = -1;
  let generation = 0;

  function clearPendingTimer(): void {
    if (timer !== null) clearTimer(timer);
    timer = null;
  }

  function scheduleReconnect(delayMs: number): void {
    if (stopped) return;
    if (attempts >= maxAttempts) {
      options.onStatus(everConnected ? "disconnected" : "unavailable");
      return;
    }
    attempts += 1;
    // Never reached the gateway: say so now and keep retrying quietly; a later success flips to live.
    options.onStatus(everConnected ? "reconnecting" : "unavailable");
    clearPendingTimer();
    timer = setTimer(() => void connect(), delayMs);
  }

  async function connect(): Promise<void> {
    if (stopped) return;
    const mine = ++generation;
    let token: string;
    try {
      token = await options.getToken();
    } catch {
      if (!stopped && mine === generation) options.onStatus("unauthenticated");
      return;
    }
    if (stopped || mine !== generation) return;

    let ws: WebSocketLike;
    try {
      ws = factory(options.url, [BEARER_SUBPROTOCOL, token]);
    } catch {
      scheduleReconnect(BACKOFF_MS[Math.min(attempts, BACKOFF_MS.length - 1)] ?? 16000);
      return;
    }
    socket = ws;

    ws.onopen = () => {
      if (stopped || mine !== generation) return;
      ws.send(JSON.stringify({ type: "subscribe", domain_id: options.domainId }));
    };
    ws.onmessage = (event) => {
      if (stopped || mine !== generation) return;
      const message = parseServerMessage(event.data);
      switch (message.kind) {
        case "subscribed":
          everConnected = true;
          attempts = 0;
          authRetried = false;
          options.onStatus("live");
          break;
        case "delta":
          if (message.delta.domain_id !== options.domainId) break;
          // A replayed or reordered frame must not overwrite newer state.
          if (message.delta.seq <= lastSeq) break;
          lastSeq = message.delta.seq;
          options.onDelta(message.delta);
          break;
        case "error":
          options.onError?.(message.code);
          break;
        case "ignored":
          break;
      }
    };
    ws.onerror = () => {
      // The close event that follows carries the decision; nothing to do here.
    };
    ws.onclose = (event) => {
      if (mine !== generation) return;
      socket = null;
      if (stopped) return;
      lastSeq = -1;
      if (event.code === CLOSE_FORBIDDEN) {
        // Revoked or not permitted: final. Never reconnect.
        stopped = true;
        options.onStatus("revoked");
        return;
      }
      if (event.code === CLOSE_UNAUTHENTICATED) {
        if (authRetried) {
          stopped = true;
          options.onStatus("unauthenticated");
          return;
        }
        authRetried = true; // one retry with a freshly acquired token
        scheduleReconnect(500);
        return;
      }
      if (event.code === CLOSE_BUDGET) {
        scheduleReconnect(BUDGET_BACKOFF_MS);
        return;
      }
      scheduleReconnect(BACKOFF_MS[Math.min(attempts, BACKOFF_MS.length - 1)] ?? 16000);
    };
  }

  return {
    start() {
      if (!stopped) return;
      stopped = false;
      attempts = 0;
      everConnected = false;
      authRetried = false;
      lastSeq = -1;
      options.onStatus("connecting");
      void connect();
    },
    stop() {
      stopped = true;
      generation += 1;
      clearPendingTimer();
      const ws = socket;
      socket = null;
      if (ws !== null) {
        ws.onclose = null;
        ws.onmessage = null;
        ws.onerror = null;
        try {
          ws.close(1000, "client_closed");
        } catch {
          // already closed
        }
      }
    },
  };
}
