import { mkdirSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { expect, test } from "../e2e-support/fixtures.ts";
import { DOMAIN_MAP_PERF, MAP_PERF_NODE_COUNT } from "../mock-api/server.ts";

// PRP-18 item 3: render the 2000-node fixture, then measure frames per second with
// requestAnimationFrame over a fixed window while the camera pans and zooms every frame and the
// observed edges animate. The number is hardware-specific: it is RECORDED always and ASSERTED
// (>= 30 fps) only when NS_MAP_PERF_ENFORCE=1 on the documented hardware. Headless Chromium often
// falls back to a software GL renderer; the renderer string is recorded beside the result.
//
//   NS_MAP_PERF_HEADED=1   run headed (real GPU path)
//   NS_MAP_PERF_ENFORCE=1  assert mean fps >= 30
//   NS_MAP_PERF_WINDOW_MS  measurement window (default 5000)

const HEADED = process.env["NS_MAP_PERF_HEADED"] === "1";
const ENFORCE = process.env["NS_MAP_PERF_ENFORCE"] === "1";
const WINDOW_MS = Number(process.env["NS_MAP_PERF_WINDOW_MS"] ?? 5000);
const TARGET_FPS = 30;

test.use({
  headless: !HEADED,
  reducedMotion: "no-preference",
  viewport: { width: 1280, height: 900 },
});

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

// Repo root /temp (gitignored); item 6 copies the result into evidence.
const OUT_DIR = path.resolve(import.meta.dirname, "../../../temp/map-perf");

interface PageMeasurement {
  frames: number;
  elapsedMs: number;
  fpsMean: number;
  fpsP5: number;
  frameTimeMs: { mean: number; p50: number; p95: number; p99: number; max: number };
  webgl: { renderer: string | null; vendor: string | null; version: string | null };
  hardwareConcurrency: number;
  userAgent: string;
  animationFramesDuringWindow: number;
  edgeAnimation: string | null;
  nodeCount: number;
  edgeCount: number;
  animatedEdges: number;
  canvases: number;
  firstNodeDisplayed: boolean;
}

test("renders 2000 nodes and records frames per second", async ({ page }, testInfo) => {
  test.setTimeout(120_000);
  // Animation is only on while the data is live and complete, so the measurement runs against a
  // live session (fake gateway, see above) with the animator genuinely running.
  await page.addInitScript(installFakeGateway, "complete");
  await page.goto(`/map?domain_id=${encodeURIComponent(DOMAIN_MAP_PERF)}`);
  const canvas = page.getByTestId("map-canvas");
  await expect(canvas).toHaveAttribute("data-node-count", String(MAP_PERF_NODE_COUNT), {
    timeout: 60_000,
  });
  await expect(canvas).toHaveAttribute("data-renderer", "webgl");
  // The animator is running and counting frames before we start measuring.
  await expect(page.getByTestId("live-status")).toHaveAttribute("data-live-status", "live");
  await expect(canvas).toHaveAttribute("data-edge-animation", "on");
  await page.waitForFunction(
    () =>
      Number(
        document.querySelector('[data-testid="map-canvas"]')?.getAttribute("data-animation-frames"),
      ) > 2,
  );

  const m: PageMeasurement = await page.evaluate(async (windowMs: number) => {
    const el = document.querySelector('[data-testid="map-canvas"]') as HTMLElement & {
      __nsMap?: {
        camera: { setState(s: { x: number; y: number; ratio: number }): void };
        sigma: { getNodeDisplayData(id: string): { size: number } | undefined };
        nodeCount(): number;
        edgeCount(): number;
      };
    };
    const hook = el.__nsMap;
    if (hook === undefined) throw new Error("map test hook missing");

    const probe = document.createElement("canvas").getContext("webgl2");
    const info = probe?.getExtension("WEBGL_debug_renderer_info");
    const webgl = {
      renderer: probe && info ? String(probe.getParameter(info.UNMASKED_RENDERER_WEBGL)) : null,
      vendor: probe && info ? String(probe.getParameter(info.UNMASKED_VENDOR_WEBGL)) : null,
      version: probe ? String(probe.getParameter(probe.VERSION)) : null,
    };

    const framesBefore = Number(el.dataset["animationFrames"] ?? 0);
    const deltas: number[] = [];
    const start = performance.now();
    await new Promise<void>((resolve) => {
      let last = start;
      const frame = (t: number): void => {
        deltas.push(t - last);
        last = t;
        const p = (t - start) / windowMs;
        // Pan in a circle and breathe the zoom, so every frame redraws the whole viewport.
        hook.camera.setState({
          x: 0.5 + 0.12 * Math.sin(p * Math.PI * 6),
          y: 0.5 + 0.12 * Math.cos(p * Math.PI * 6),
          ratio: 1 + 0.5 * Math.sin(p * Math.PI * 4),
        });
        if (t - start < windowMs) requestAnimationFrame(frame);
        else resolve();
      };
      requestAnimationFrame(frame);
    });
    const elapsedMs = performance.now() - start;
    const measured = deltas.slice(1); // the first delta spans the setup, not a frame
    const sorted = [...measured].sort((a, b) => a - b);
    const q = (p: number): number =>
      sorted[Math.min(sorted.length - 1, Math.floor(p * sorted.length))] ?? 0;
    const mean = measured.reduce((a, b) => a + b, 0) / Math.max(1, measured.length);
    return {
      frames: measured.length,
      elapsedMs,
      fpsMean: (measured.length / elapsedMs) * 1000,
      // 5th-percentile fps == the slowest 5% of frames (95th percentile frame time).
      fpsP5: 1000 / Math.max(q(0.95), 0.001),
      frameTimeMs: { mean, p50: q(0.5), p95: q(0.95), p99: q(0.99), max: sorted.at(-1) ?? 0 },
      webgl,
      hardwareConcurrency: navigator.hardwareConcurrency,
      userAgent: navigator.userAgent,
      animationFramesDuringWindow: Number(el.dataset["animationFrames"] ?? 0) - framesBefore,
      edgeAnimation: el.getAttribute("data-edge-animation"),
      nodeCount: hook.nodeCount(),
      edgeCount: hook.edgeCount(),
      animatedEdges: Number(el.dataset["animatedEdges"] ?? 0),
      canvases: el.querySelectorAll("canvas").length,
      firstNodeDisplayed: (hook.sigma.getNodeDisplayData("perf:node:0")?.size ?? 0) > 0,
    };
  }, WINDOW_MS);

  const cpus = os.cpus();
  const record = {
    prp: "PRP-18 item 3",
    target: `>= ${TARGET_FPS} fps at ${MAP_PERF_NODE_COUNT} visible nodes on documented hardware`,
    enforced: ENFORCE,
    headless: !HEADED,
    windowMs: WINDOW_MS,
    measuredAt: new Date().toISOString(),
    result: {
      fpsMean: Number(m.fpsMean.toFixed(2)),
      fpsP5: Number(m.fpsP5.toFixed(2)),
      frames: m.frames,
      elapsedMs: Math.round(m.elapsedMs),
      frameTimeMs: Object.fromEntries(
        Object.entries(m.frameTimeMs).map(([k, v]) => [k, Number(v.toFixed(2))]),
      ),
      meetsTarget: m.fpsMean >= TARGET_FPS,
    },
    scene: {
      nodes: m.nodeCount,
      edges: m.edgeCount,
      animatedEdges: m.animatedEdges,
      edgeAnimation: m.edgeAnimation,
      animationFramesDuringWindow: m.animationFramesDuringWindow,
    },
    browser: {
      name: testInfo.project.name,
      userAgent: m.userAgent,
      hardwareConcurrency: m.hardwareConcurrency,
      webglRenderer: m.webgl.renderer,
      webglVendor: m.webgl.vendor,
      webglVersion: m.webgl.version,
    },
    host: {
      platform: os.platform(),
      release: os.release(),
      arch: os.arch(),
      cpuModel: cpus[0]?.model ?? "unknown",
      cpuCount: cpus.length,
      totalMemBytes: os.totalmem(),
      node: process.version,
    },
  };

  mkdirSync(OUT_DIR, { recursive: true });
  writeFileSync(path.join(OUT_DIR, "fps.json"), `${JSON.stringify(record, null, 2)}\n`, "utf-8");
  await canvas.screenshot({ path: path.join(OUT_DIR, "map.png") });
  console.log(`map-perf: ${JSON.stringify(record.result)} renderer=${m.webgl.renderer ?? "n/a"}`);

  // Always: rendering happened.
  expect(m.nodeCount).toBe(MAP_PERF_NODE_COUNT);
  expect(m.edgeCount).toBeGreaterThan(0);
  expect(m.canvases).toBeGreaterThan(0);
  expect(m.firstNodeDisplayed).toBe(true);
  expect(m.frames).toBeGreaterThan(0);
  // Fail loudly if the measurement did not run with animation ON (it would flatter the fps).
  expect(m.edgeAnimation).toBe("on");
  expect(m.animatedEdges).toBeGreaterThan(0);
  expect(m.animationFramesDuringWindow).toBeGreaterThan(0);

  // Only on the documented hardware.
  if (ENFORCE) expect(m.fpsMean).toBeGreaterThanOrEqual(TARGET_FPS);
});
