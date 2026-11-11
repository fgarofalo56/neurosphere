import {
  createContext,
  useContext,
  useEffect,
  useRef,
  useSyncExternalStore,
  type ReactElement,
  type ReactNode,
} from "react";

/**
 * Selection published by features for the copilot. The dock lives in the app shell next to the
 * routed page, not under it, so publishers and the dock must share one provider mounted above
 * both. Each `CopilotSelectionProvider` owns its own store: separately mounted roots (sessions,
 * tests) never share a selection.
 *
 * Without a provider, `useCopilotSelection` is a no-op (nothing is published, nothing leaks) and
 * the dock wraps itself in a provider of its own, so it still works with an empty selection.
 *
 * The selection is only a hint for the next question. The server drops (and counts) anything the
 * caller cannot read, and the context chip shows what it actually accepted.
 */
const EMPTY: readonly string[] = [];

export interface SelectionStore {
  readonly get: () => readonly string[];
  readonly set: (ids: readonly string[]) => void;
  readonly subscribe: (listener: () => void) => () => void;
}

function sameIds(a: readonly string[], b: readonly string[]): boolean {
  return a.length === b.length && a.every((id, i) => id === b[i]);
}

export function createSelectionStore(): SelectionStore {
  let current: readonly string[] = EMPTY;
  const listeners = new Set<() => void>();
  return {
    get: () => current,
    set: (ids) => {
      const next = ids.length === 0 ? EMPTY : [...ids];
      if (sameIds(current, next)) return;
      current = next;
      for (const listener of listeners) listener();
    },
    subscribe: (listener) => {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
  };
}

const SelectionContext = createContext<SelectionStore | null>(null);

const DETACHED: SelectionStore = {
  get: () => EMPTY,
  set: () => undefined,
  subscribe: () => () => undefined,
};

export function CopilotSelectionProvider({ children }: { children: ReactNode }): ReactElement {
  const ref = useRef<SelectionStore | null>(null);
  ref.current ??= createSelectionStore();
  return <SelectionContext.Provider value={ref.current}>{children}</SelectionContext.Provider>;
}

/** True when a `CopilotSelectionProvider` is mounted above the caller. */
export function useHasCopilotSelectionProvider(): boolean {
  return useContext(SelectionContext) !== null;
}

/** For the dock: the currently published selection. */
export function useCurrentCopilotSelection(): readonly string[] {
  const store = useContext(SelectionContext) ?? DETACHED;
  return useSyncExternalStore(store.subscribe, store.get, store.get);
}

/**
 * For features: publish the entities the user has selected while the component is mounted. The
 * selection is cleared again on unmount, so it cannot leak into another page's questions.
 */
export function useCopilotSelection(ids: readonly string[]): void {
  const store = useContext(SelectionContext) ?? DETACHED;
  const key = ids.join("\u0000");
  useEffect(() => {
    store.set(key === "" ? EMPTY : key.split("\u0000"));
    return () => store.set(EMPTY);
  }, [store, key]);
}
