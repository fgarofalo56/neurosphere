import { useCallback, useEffect, useState } from "react";
import type { LiveStatus } from "./realtime";
import type { Coverage } from "./types";

export type AnimationGate = "on" | "reduced" | "notLive" | "delayed" | "unknown";

/**
 * Observed edges animate only while motion is allowed, the socket is live and coverage is
 * complete or partial. Animating stale data as live is misleading; a gap is labelled, never
 * smoothed over. Reduced motion is checked first so its reason wins.
 */
export function animationGate(
  reduced: boolean,
  status: LiveStatus,
  coverageState: Coverage["state"] | null,
): AnimationGate {
  if (reduced) return "reduced";
  if (status !== "live") return "notLive";
  if (coverageState === "complete" || coverageState === "partial") return "on";
  return coverageState === "delayed" ? "delayed" : "unknown";
}

export const REDUCED_MOTION_QUERY = "(prefers-reduced-motion: reduce)";

/** Reduced motion applies when the system asks for it OR the in-app toggle is on. */
export function effectiveReducedMotion(systemPrefers: boolean, appToggle: boolean): boolean {
  return systemPrefers || appToggle;
}

function readSystemPreference(): boolean {
  return typeof window !== "undefined" && typeof window.matchMedia === "function"
    ? window.matchMedia(REDUCED_MOTION_QUERY).matches
    : false;
}

export interface MotionState {
  readonly systemPrefers: boolean;
  readonly appToggle: boolean;
  readonly reduced: boolean;
  setAppToggle(value: boolean): void;
}

export function useReducedMotion(): MotionState {
  const [systemPrefers, setSystemPrefers] = useState(readSystemPreference);
  const [appToggle, setToggle] = useState(false);

  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const query = window.matchMedia(REDUCED_MOTION_QUERY);
    const onChange = (): void => setSystemPrefers(query.matches);
    onChange();
    query.addEventListener("change", onChange);
    return () => query.removeEventListener("change", onChange);
  }, []);

  const setAppToggle = useCallback((value: boolean) => setToggle(value), []);
  return {
    systemPrefers,
    appToggle,
    reduced: effectiveReducedMotion(systemPrefers, appToggle),
    setAppToggle,
  };
}
