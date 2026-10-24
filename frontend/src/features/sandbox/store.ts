import { create } from "zustand";
import { persist } from "zustand/middleware";

export const SANDBOX_STORAGE_KEY = "ns.sandbox-mode";

export interface SandboxState {
  readonly enabled: boolean;
  readonly setEnabled: (enabled: boolean) => void;
  readonly toggle: () => void;
}

/**
 * UI preference only (persisted to localStorage). It selects the route family the UI shows; the
 * server enforces isolation with a container allowlist and never reads this flag.
 */
export const useSandboxStore = create<SandboxState>()(
  persist(
    (set) => ({
      enabled: false,
      setEnabled: (enabled) => {
        set({ enabled });
      },
      toggle: () => {
        set((s) => ({ enabled: !s.enabled }));
      },
    }),
    {
      name: SANDBOX_STORAGE_KEY,
      partialize: (s) => ({ enabled: s.enabled }),
    },
  ),
);
