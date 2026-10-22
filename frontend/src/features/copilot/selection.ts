import { useEffect, useSyncExternalStore } from "react";

/**
 * Selection published by features for the copilot. The dock lives in the app shell next to the
 * routed page, not under it, so the selection travels through a tiny module-level store rather
 * than React context. Features opt in later by calling `useCopilotSelection(ids)`; nothing else
 * needs to change.
 *
 * The selection is only a hint for the next question. The server drops (and counts) anything the
 * caller cannot read, and the context chip shows what it actually accepted.
 */
const EMPTY: readonly string[] = [];
let current: readonly string[] = EMPTY;
const listeners = new Set<() => void>();

function emit(): void {
  for (const listener of listeners) listener();
}

function sameIds(a: readonly string[], b: readonly string[]): boolean {
  return a.length === b.length && a.every((id, i) => id === b[i]);
}

/** Replaces the published selection. Pass an empty list to clear it. */
export function setCopilotSelection(ids: readonly string[]): void {
  const next = ids.length === 0 ? EMPTY : [...ids];
  if (sameIds(current, next)) return;
  current = next;
  emit();
}

export function getCopilotSelection(): readonly string[] {
  return current;
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** For the dock: the currently published selection. */
export function useCurrentCopilotSelection(): readonly string[] {
  return useSyncExternalStore(subscribe, getCopilotSelection, getCopilotSelection);
}

/**
 * For features: publish the entities the user has selected while the component is mounted. The
 * selection is cleared again on unmount, so it cannot leak into another page's questions.
 */
export function useCopilotSelection(ids: readonly string[]): void {
  const key = ids.join("\u0000");
  useEffect(() => {
    setCopilotSelection(key === "" ? EMPTY : key.split("\u0000"));
    return () => setCopilotSelection(EMPTY);
  }, [key]);
}
