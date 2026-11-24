import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";
import type { Page } from "@playwright/test";
import { expect, test } from "../e2e-support/fixtures.ts";
import { DOMAIN_MAP_PERF, MAP_PERF_NODE_COUNT } from "../mock-api/server.ts";
import { hostInfo, installFakeGateway } from "./map-perf-helpers.ts";

// PRP-77 item 7: interaction latency on the 2000-node fixture (same fixture and fake realtime
// gateway as map-perf.spec.ts). For each of pan, wheel zoom, node hover, node click and "Show
// impact" highlight it records at least 30 samples of
//
//   input event dispatched in the page  ->  the SECOND requestAnimationFrame after that dispatch
//
// Method (clarification 7): Playwright performs the real input (mouse move/down/up, wheel, click),
// but the clock is page-side. A capture-phase listener on `window` takes performance.now() when the
// armed event reaches the page, then schedules two nested requestAnimationFrame callbacks and takes
// performance.now() in the second one. The first rAF is the frame the browser was about to render;
// the second runs after that frame was produced, so the interval covers handler work, style/layout
// and the paint the input caused. Playwright round-trips are not counted. "Show impact" additionally
// waits for the dependents list to appear (the answer to the impact POST, served by this spec) before
// the two frames, so it measures click -> response -> highlight.
//
// The number is hardware-specific: it is RECORDED always and ASSERTED (p95 <= 200 ms for every
// interaction) only when NS_MAP_LATENCY_ENFORCE=1. Headless Chromium uses SwiftShader (software
// GL), which is not product evidence; the file says so. Nothing here speaks for 50k nodes.
//
//   NS_MAP_PERF_HEADED=1             run headed (real GPU path), same switch as map-perf
//   NS_MAP_LATENCY_ENFORCE=1         assert p95 <= 200 ms per interaction
//   NS_MAP_LATENCY_RUN=1             run in CI too (skipped there by default: software GL is slow)
//   NS_MAP_LATENCY_SAMPLES          samples per interaction (default 30, minimum 30)
//   NS_MAP_LATENCY_WRITE_EVIDENCE=1  write docs/evidence/G07/map/interaction-latency.json
//                                    (default: temp/map-latency/, so a routine run never
//                                    overwrites the committed evidence)

const HEADED = process.env["NS_MAP_PERF_HEADED"] === "1";
const ENFORCE = process.env["NS_MAP_LATENCY_ENFORCE"] === "1";
const WRITE_EVIDENCE = process.env["NS_MAP_LATENCY_WRITE_EVIDENCE"] === "1";
const SAMPLES = Math.max(30, Number(process.env["NS_MAP_LATENCY_SAMPLES"] ?? 30));
// Node events normally come from sigma's GPU picking pass. Software GL (headless SwiftShader) never
// resolves a node under the pointer on this fixture (no enterNode/clickNode ever fires: verified),
// so a headless run raises the same sigma event from the page right after the real mouse input.
// The file records which one was used. NS_MAP_LATENCY_NODE_INPUT=pointer|emit overrides the default
// (pointer when headed, emit when headless).
const NODE_INPUT = process.env["NS_MAP_LATENCY_NODE_INPUT"] ?? (HEADED ? "pointer" : "emit");
const EMIT_NODE_EVENTS = NODE_INPUT === "emit";
const IN_CI = (process.env["CI"] ?? "") !== "";
const RUN_IN_CI = process.env["NS_MAP_LATENCY_RUN"] === "1";
const TARGET_P95_MS = 200;
const REPO_ROOT = path.resolve(import.meta.dirname, "../../..");
const OUT_DIR = WRITE_EVIDENCE
  ? path.join(REPO_ROOT, "docs/evidence/G07/map")
  : path.join(REPO_ROOT, "temp/map-latency");

test.use({
  headless: !HEADED,
  reducedMotion: "no-preference",
  viewport: { width: 1280, height: 900 },
});

type Kind = "pan" | "wheel_zoom" | "node_hover" | "node_click" | "show_impact";
const ALL_KINDS: readonly Kind[] = ["pan", "wheel_zoom", "node_hover", "node_click", "show_impact"];
// NS_MAP_LATENCY_KINDS=node_click,show_impact limits a run (development only; the evidence run
// leaves it unset so all five interactions are recorded).
const KINDS: readonly Kind[] = ALL_KINDS.filter((k) =>
  (process.env["NS_MAP_LATENCY_KINDS"] ?? ALL_KINDS.join(",")).split(",").includes(k),
);

interface Recorder {
  samples: Record<string, number[]>;
  arm(kind: string, event: string, waitSelector: string | null, emit: SigmaEmit | null): void;
  /** Discards the last sample of a kind (a click that missed every node is not a node click). */
  drop(kind: string): void;
  done(): Promise<void>;
}

/** A sigma node event raised from the page right after the armed input (software-GL runs only). */
interface SigmaEmit {
  name: "clickNode" | "enterNode";
  node: string;
}

interface MapHook {
  camera: { setState(s: { x: number; y: number; ratio: number }): void };
  sigma: {
    getNodeDisplayData(id: string): { x: number; y: number; size: number } | undefined;
    framedGraphToViewport(p: { x: number; y: number }): { x: number; y: number };
  };
  nodeCount(): number;
  edgeCount(): number;
}

type Win = typeof globalThis & { __nsLat: Recorder };

/** Page-side recorder (see the method note at the top). Runs inside the page. */
function installRecorder(): void {
  const samples: Record<string, number[]> = {};
  let armed: {
    kind: string;
    event: string;
    waitSelector: string | null;
    emit: SigmaEmit | null;
  } | null = null;
  let pending: Promise<void> | null = null;

  const onInput = (e: Event): void => {
    if (armed === null || e.type !== armed.event) return;
    // A pan sample is a mouse move with the primary button held.
    if (e.type === "mousemove" && armed.kind === "pan" && (e as MouseEvent).buttons !== 1) return;
    const a = armed;
    armed = null;
    const t0 = performance.now();
    pending = new Promise<void>((resolve, reject) => {
      const go = (): void => {
        const twoFrames = (): void => {
          requestAnimationFrame(() =>
            requestAnimationFrame(() => {
              (samples[a.kind] ??= []).push(performance.now() - t0);
              resolve();
            }),
          );
        };
        if (a.waitSelector === null) return twoFrames();
        const sel = a.waitSelector;
        const timer = setTimeout(() => {
          observer.disconnect();
          reject(new Error(`"${sel}" never appeared after ${a.kind}`));
        }, 10_000);
        const observer = new MutationObserver(() => {
          if (document.querySelector(sel) === null) return;
          observer.disconnect();
          clearTimeout(timer);
          twoFrames();
        });
        observer.observe(document.body, { childList: true, subtree: true });
      };
      if (a.emit === null) return go();
      // After the whole DOM dispatch of the input (sigma's own handler runs inside it), raise the
      // node event the GPU picking pass would have raised, then count the two frames.
      const target = a.emit;
      setTimeout(() => {
        const el = document.querySelector('[data-testid="map-canvas"]') as HTMLElement & {
          __nsMap?: { sigma: { emit(name: string, payload: object): void } };
        };
        el.__nsMap?.sigma.emit(target.name, {
          node: target.node,
          event: {},
          preventSigmaDefault: () => undefined,
        });
        go();
      }, 0);
    });
  };
  for (const type of ["mousemove", "mouseup", "wheel", "click"]) {
    window.addEventListener(type, onInput, { capture: true, passive: true });
  }

  (window as Win).__nsLat = {
    samples,
    drop(kind) {
      samples[kind]?.pop();
    },
    arm(kind, event, waitSelector, emit) {
      pending = null;
      armed = { kind, event, waitSelector, emit };
    },
    async done() {
      // Give the dispatched input a moment to reach the page, then wait for its two frames.
      for (let i = 0; i < 500 && pending === null; i += 1) {
        await new Promise((r) => setTimeout(r, 20));
      }
      if (pending === null) {
        const kind = armed?.kind ?? "?";
        armed = null;
        throw new Error(
          `the armed ${kind} input never reached the page (${samples[kind]?.length ?? 0} samples so far)`,
        );
      }
      await Promise.race([
        pending,
        new Promise((_, reject) =>
          setTimeout(() => reject(new Error("the two frames never arrived (15 s)")), 15_000),
        ),
      ]);
    },
  };
}

/** A realistic impact answer for the node the click named: two levels of dependents. */
function impactAnswer(domainId: string, nodeId: string): object {
  const index = Number(nodeId.split(":").at(-1));
  const kinds = ["agent", "sub_agent", "tool", "service"] as const;
  const health = ["ok", "ok", "degraded", "failing", "unknown"] as const;
  const dep = (offset: number): object => {
    const n = (index + offset) % MAP_PERF_NODE_COUNT;
    return {
      id: `perf:node:${n}`,
      kind: kinds[n % kinds.length],
      label: `perf-${n}`,
      domain_id: domainId,
      health: health[n % health.length],
      health_inferred: n % 3 === 0,
    };
  };
  return {
    domain_id: domainId,
    node_id: nodeId,
    direction: "dependents",
    levels: [
      {
        depth: 1,
        nodes: [1, 7, 13, 29].map((o) => dep(o)),
        edge_ids: [1, 7, 13, 29].map((o) => `perf:edge:${(index + o) % 4000}`),
      },
      {
        depth: 2,
        nodes: [41, 53, 67, 83, 97, 101].map((o) => dep(o)),
        edge_ids: [41, 53, 67, 83, 97, 101].map((o) => `perf:edge:${(index + o) % 4000}`),
      },
    ],
    truncated: false,
    truncation_reason: null,
    coverage: { state: "complete", lag_seconds: 0, as_of: null },
  };
}

function percentile(sorted: number[], p: number): number {
  if (sorted.length === 0) return Number.NaN;
  return sorted[Math.min(sorted.length - 1, Math.floor(p * sorted.length))] ?? Number.NaN;
}

const round = (n: number): number => Number(n.toFixed(2));

async function sample(
  page: Page,
  kind: Kind,
  event: string,
  waitSelector: string | null,
  act: () => Promise<void>,
  emit: SigmaEmit | null = null,
): Promise<void> {
  await page.evaluate(([k, e, w, m]) => (window as Win).__nsLat.arm(k, e, w, m), [
    kind,
    event,
    waitSelector,
    emit,
  ] as const);
  await act();
  await page.evaluate(() => (window as Win).__nsLat.done());
}

/** Viewport position (page coordinates) of a node, after the layout has settled. */
async function nodePoint(page: Page, id: string): Promise<{ x: number; y: number } | null> {
  return page.evaluate(async (nodeId: string) => {
    await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
    const el = document.querySelector('[data-testid="map-canvas"]') as HTMLElement & {
      __nsMap?: MapHook;
    };
    const hook = el.__nsMap;
    const d = hook?.sigma.getNodeDisplayData(nodeId);
    if (hook === undefined || d === undefined || d.size <= 0) return null;
    const p = hook.sigma.framedGraphToViewport({ x: d.x, y: d.y });
    const box = el.getBoundingClientRect();
    const inView = (x: number, y: number): boolean =>
      x > 40 && y > 40 && x < window.innerWidth - 40 && y < window.innerHeight - 60;
    if (p.x < 40 || p.y < 40 || p.x > box.width - 40 || p.y > box.height - 40) return null;
    if (!inView(box.left + p.x, box.top + p.y)) return null;
    return { x: box.left + p.x, y: box.top + p.y };
  }, id);
}

/**
 * Moves the pointer onto a node and waits two frames so the renderer has resolved the hovered node
 * (sigma resolves it per frame; a click that arrives first lands on the stage). Not a sample.
 */
async function pointAt(page: Page, p: { x: number; y: number }): Promise<void> {
  await page.mouse.move(p.x, p.y);
  await page.evaluate(
    () => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r))),
  );
}

/** After a click: is a node selected (its panel open)? Waits for the frames that apply it. */
async function panelOpen(page: Page): Promise<boolean> {
  await page.evaluate(
    () => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r))),
  );
  return page
    .getByTestId("node-panel")
    .waitFor({ state: "visible", timeout: 3000 })
    .then(
      () => true,
      () => false,
    );
}

/** Resets the camera to the framed fixture (page-side, not a sample). */
async function resetCamera(page: Page): Promise<void> {
  await page.evaluate(() => {
    const el = document.querySelector('[data-testid="map-canvas"]') as HTMLElement & {
      __nsMap?: MapHook;
    };
    el.__nsMap?.camera.setState({ x: 0.5, y: 0.5, ratio: 1 });
  });
}

test("records p50/p95/max interaction latency on the 2000-node fixture", async ({
  page,
  browser,
}, testInfo) => {
  // Software GL (headless) runs at about 5 fps, so a full headless run takes 20 minutes or more:
  // in CI it is opt-in (NS_MAP_LATENCY_RUN=1) instead of running on every PR.
  test.skip(IN_CI && !RUN_IN_CI, "slow software-GL measurement: set NS_MAP_LATENCY_RUN=1 in CI");
  test.setTimeout(3_000_000);
  // The impact POST is answered here (the mock API has no impact route); the body names the node.
  await page.route("**/api/v1/map/domains/*/impact", async (route) => {
    const cors = {
      "access-control-allow-origin": "*",
      "access-control-allow-headers": "authorization, content-type, x-correlation-id, if-match",
      "access-control-allow-methods": "GET, POST, PUT, PATCH, DELETE, OPTIONS",
    };
    if (route.request().method() === "OPTIONS") {
      return route.fulfill({ status: 204, headers: cors });
    }
    const body = route.request().postDataJSON() as { node_id: string };
    return route.fulfill({
      status: 200,
      headers: cors,
      json: impactAnswer(DOMAIN_MAP_PERF, body.node_id),
    });
  });
  await page.addInitScript(installFakeGateway, "complete");
  await page.goto(`/map?domain_id=${encodeURIComponent(DOMAIN_MAP_PERF)}`);
  const canvas = page.getByTestId("map-canvas");
  await expect(canvas).toHaveAttribute("data-node-count", String(MAP_PERF_NODE_COUNT), {
    timeout: 60_000,
  });
  await expect(canvas).toHaveAttribute("data-renderer", "webgl");
  await expect(page.getByTestId("live-status")).toHaveAttribute("data-live-status", "live");
  await expect(canvas).toHaveAttribute("data-edge-animation", "on");
  await page.evaluate(installRecorder);

  const scene = await page.evaluate(() => {
    const el = document.querySelector('[data-testid="map-canvas"]') as HTMLElement & {
      __nsMap?: MapHook;
    };
    const hook = el.__nsMap;
    if (hook === undefined) throw new Error("map test hook missing");
    const probe = document.createElement("canvas").getContext("webgl2");
    const info = probe?.getExtension("WEBGL_debug_renderer_info");
    return {
      nodes: hook.nodeCount(),
      edges: hook.edgeCount(),
      renderer: probe && info ? String(probe.getParameter(info.UNMASKED_RENDERER_WEBGL)) : null,
    };
  });
  expect(scene.nodes).toBe(MAP_PERF_NODE_COUNT);

  // Candidate nodes: the framed fixture, spread across the canvas, never reused within a kind.
  await resetCamera(page);
  // One page-side pass: each per-node round trip would wait for frames, slow under software GL.
  const candidates = await page.evaluate((limit: number) => {
    const el = document.querySelector('[data-testid="map-canvas"]') as HTMLElement & {
      __nsMap?: MapHook;
    };
    const hook = el.__nsMap;
    const out: string[] = [];
    if (hook === undefined) return out;
    const box = el.getBoundingClientRect();
    for (let i = 0; i < 2000 && out.length < limit; i += 3) {
      const d = hook.sigma.getNodeDisplayData(`perf:node:${i}`);
      if (d === undefined || d.size <= 0) continue;
      const p = hook.sigma.framedGraphToViewport({ x: d.x, y: d.y });
      const inCanvas = p.x > 40 && p.y > 40 && p.x < box.width - 40 && p.y < box.height - 40;
      const inWindow = box.top + p.y < window.innerHeight - 60;
      if (inCanvas && inWindow) {
        out.push(`perf:node:${i}`);
      }
    }
    return out;
  }, SAMPLES * 12);
  expect(candidates.length).toBeGreaterThanOrEqual(SAMPLES * 8);
  const pick = (kindIndex: number): string[] => candidates.filter((_, i) => i % 4 === kindIndex);

  const box = await canvas.boundingBox();
  if (box === null) throw new Error("map canvas has no box");
  const cx = box.x + box.width / 2;
  const cy = box.y + box.height / 2;

  const count = (kind: Kind): Promise<number> =>
    page.evaluate((k) => (window as Win).__nsLat.samples[k]?.length ?? 0, kind);
  // Pan: drag with the primary button held; every mouse move is one sample.
  if (KINDS.includes("pan")) {
    await resetCamera(page);
    await page.mouse.move(cx, cy);
    await page.mouse.down();
    for (let i = 0; i < SAMPLES; i += 1) {
      const dx = i % 2 === 0 ? 40 : -40;
      await sample(page, "pan", "mousemove", null, () => page.mouse.move(cx + dx, cy + 10));
    }
    await page.mouse.up();
  }

  // Wheel zoom: alternate in and out so the camera stays in range; let the zoom settle between.
  if (KINDS.includes("wheel_zoom")) {
    await resetCamera(page);
    await page.mouse.move(cx, cy);
    for (let i = 0; i < SAMPLES; i += 1) {
      await sample(page, "wheel_zoom", "wheel", null, () =>
        page.mouse.wheel(0, i % 2 === 0 ? -120 : 120),
      );
      await page.waitForTimeout(250);
    }
  }

  // Node hover: move onto a different node each time.
  if (KINDS.includes("node_hover")) {
    await resetCamera(page);
    for (const id of pick(0)) {
      if ((await count("node_hover")) >= SAMPLES) break;
      const p = await nodePoint(page, id);
      if (p === null) continue;
      await page.mouse.move(p.x + 25, p.y + 25);
      await sample(
        page,
        "node_hover",
        "mousemove",
        null,
        () => page.mouse.move(p.x, p.y),
        EMIT_NODE_EVENTS ? { name: "enterNode", node: id } : null,
      );
    }
  }

  // Node click: mouse up is the input that selects (sigma raises clickNode from it).
  if (KINDS.includes("node_click")) {
    await resetCamera(page);
    for (const id of pick(1)) {
      if ((await count("node_click")) >= SAMPLES) break;
      const p = await nodePoint(page, id);
      if (p === null) continue;
      await pointAt(page, p);
      await page.mouse.down();
      await sample(
        page,
        "node_click",
        "mouseup",
        null,
        () => page.mouse.up(),
        EMIT_NODE_EVENTS ? { name: "clickNode", node: id } : null,
      );
      // A click that missed every node deselects (the panel closes): that is not a node click.
      if (!(await panelOpen(page)))
        await page.evaluate(() => (window as Win).__nsLat.drop("node_click"));
    }
  }

  // "Show impact": select a node (unmeasured), click the button, wait for the dependents list.
  if (KINDS.includes("show_impact")) {
    await resetCamera(page);
    for (const id of pick(2)) {
      if ((await count("show_impact")) >= SAMPLES) break;
      const p = await nodePoint(page, id);
      if (p === null) continue;
      if (EMIT_NODE_EVENTS) {
        await page.evaluate((node: string) => {
          const el = document.querySelector('[data-testid="map-canvas"]') as HTMLElement & {
            __nsMap?: { sigma: { emit(name: string, payload: object): void } };
          };
          el.__nsMap?.sigma.emit("clickNode", {
            node,
            event: {},
            preventSigmaDefault: () => undefined,
          });
        }, id);
      } else {
        await pointAt(page, p);
        await page.mouse.down();
        await page.mouse.up();
      }
      if (!(await panelOpen(page))) continue;
      const button = page.getByTestId("show-impact");
      await expect(button).toBeEnabled({ timeout: 30_000 });
      await sample(page, "show_impact", "click", '[data-testid="impact-row"]', () =>
        button.click(),
      );
      await page.getByTestId("impact-clear").click();
      await expect(page.getByTestId("impact-row")).toHaveCount(0, { timeout: 30_000 });
    }
  }

  const samples = await page.evaluate(() => (window as Win).__nsLat.samples);
  const interactions: Record<string, object> = {};
  let allMeet = true;
  for (const kind of KINDS) {
    const sorted = [...(samples[kind] ?? [])].sort((a, b) => a - b);
    const p95 = percentile(sorted, 0.95);
    const meets = sorted.length >= 30 && p95 <= TARGET_P95_MS;
    allMeet &&= meets;
    interactions[kind] = {
      samples: sorted.length,
      p50_ms: round(percentile(sorted, 0.5)),
      p95_ms: round(p95),
      max_ms: round(sorted.at(-1) ?? Number.NaN),
      meets_target: meets,
      ...(kind === "node_hover" || kind === "node_click" || kind === "show_impact"
        ? {
            node_targeting: EMIT_NODE_EVENTS
              ? "sigma node event raised from the page after the real mouse input (no GPU picking)"
              : "real pointer on the node (GPU picking)",
          }
        : {}),
    };
  }

  const host = hostInfo();
  const record = {
    prp: "PRP-77 item 7",
    method:
      "page-side performance.now() at the dispatched input event to the second requestAnimationFrame after it; Playwright performs the input; show_impact waits for the dependents list",
    measured_at: new Date().toISOString(),
    target_p95_ms: TARGET_P95_MS,
    meets_target: allMeet,
    enforced: ENFORCE,
    mode: HEADED ? "headed" : "headless",
    browser: {
      name: testInfo.project.name,
      version: browser.version(),
      webgl_renderer: scene.renderer,
    },
    host: {
      os: `${host.platform} ${host.release} ${host.arch}`,
      cpu_model: host.cpuModel,
      logical_cores: host.cpuCount,
      ram_bytes: host.totalMemBytes,
      node: host.node,
    },
    scene: { nodes: scene.nodes, edges: scene.edges },
    interactions,
    note: HEADED
      ? "Headed run on the hardware above. The 200 ms p95 figure is reported for this hardware and 2000 nodes only; no claim is made about 50k nodes."
      : "Headless run: Chromium used software GL (SwiftShader), so these numbers are NOT product evidence; node hover, click and impact events were raised from the page after the real mouse input because software GL never resolves a node under the pointer (see node_targeting); re-measure headed on operator hardware (PRP-66). The 200 ms p95 figure is reported for this hardware and 2000 nodes only; no claim is made about 50k nodes.",
  };

  mkdirSync(OUT_DIR, { recursive: true });
  writeFileSync(
    path.join(OUT_DIR, "interaction-latency.json"),
    `${JSON.stringify(record, null, 2)}\n`,
    "utf-8",
  );
  console.log(`map-latency: ${JSON.stringify(interactions)} renderer=${scene.renderer ?? "n/a"}`);

  // Always: every interaction was actually measured.
  for (const kind of KINDS) {
    expect(samples[kind]?.length ?? 0, `${kind} samples`).toBeGreaterThanOrEqual(30);
  }
  // Only on the documented hardware.
  if (ENFORCE) {
    for (const kind of KINDS) {
      const sorted = [...(samples[kind] ?? [])].sort((a, b) => a - b);
      expect(percentile(sorted, 0.95), `${kind} p95`).toBeLessThanOrEqual(TARGET_P95_MS);
    }
  }
});
