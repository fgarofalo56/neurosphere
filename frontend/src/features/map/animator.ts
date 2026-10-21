/**
 * Edge animation loop. Advances the dash offset of OBSERVED edges only; declared and inferred
 * edges are never touched. The scheduler is injected so tests count frames deterministically,
 * and a stopped animator schedules nothing (reduced motion means zero scheduled frames).
 */
export interface Scheduler {
  request(callback: (timeMs: number) => void): number;
  cancel(handle: number): void;
}

export const browserScheduler: Scheduler = {
  request: (cb) => requestAnimationFrame(cb),
  cancel: (handle) => cancelAnimationFrame(handle),
};

export interface AnimatorTarget {
  /** Ids of the edges that may animate right now. */
  animatedEdgeIds(): string[];
  /** Apply the new offset (px) to those edges and redraw. */
  setOffset(edgeIds: readonly string[], offset: number): void;
}

/** Dash offset speed in px per second. */
export const FLOW_SPEED = 24;

export interface EdgeAnimator {
  start(): void;
  stop(): void;
  readonly running: boolean;
  /** Number of animation frames this animator has run (a testable signal). */
  readonly frames: number;
}

export function createEdgeAnimator(
  target: AnimatorTarget,
  scheduler: Scheduler = browserScheduler,
  onFrame?: (frames: number) => void,
): EdgeAnimator {
  let handle: number | null = null;
  let last: number | null = null;
  let offset = 1;
  let frames = 0;

  const tick = (timeMs: number): void => {
    handle = null;
    const dt = last === null ? 0 : Math.min((timeMs - last) / 1000, 0.1);
    last = timeMs;
    offset += dt * FLOW_SPEED;
    const ids = target.animatedEdgeIds();
    if (ids.length > 0) target.setOffset(ids, offset);
    frames += 1;
    onFrame?.(frames);
    handle = scheduler.request(tick);
  };

  return {
    start() {
      if (handle !== null) return;
      last = null;
      handle = scheduler.request(tick);
    },
    stop() {
      if (handle !== null) scheduler.cancel(handle);
      handle = null;
      last = null;
    },
    get running() {
      return handle !== null;
    },
    get frames() {
      return frames;
    },
  };
}
