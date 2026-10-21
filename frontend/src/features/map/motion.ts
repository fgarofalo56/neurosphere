import { useCallback, useEffect, useState } from "react";

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
