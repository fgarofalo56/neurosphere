import { create } from "zustand";
import { DEFAULT_THEME_PACK_ID, THEME_PACKS } from "./themes";
import { THEME_NAMES } from "./tokens";
import type { ThemeName } from "./tokens";

/** Single localStorage key holding `{ packId, themeName }` as JSON. */
export const THEME_STORAGE_KEY = "ns.theme";

export interface ThemeState {
  themeName: ThemeName;
  packId: string;
  setTheme: (name: ThemeName) => void;
  setPack: (packId: string) => void;
  /**
   * Apply the deployment-level default (from runtime config). A value the user already chose
   * (kept in local storage) wins; unknown values are ignored.
   */
  applyDeploymentDefault: (defaults: { packId?: string; themeName?: string }) => void;
}

export function isThemeName(value: unknown): value is ThemeName {
  return typeof value === "string" && (THEME_NAMES as readonly string[]).includes(value);
}

export function isThemePackId(value: unknown): value is string {
  return typeof value === "string" && Object.prototype.hasOwnProperty.call(THEME_PACKS, value);
}

interface StoredTheme {
  packId?: string;
  themeName?: ThemeName;
}

/** Reads and validates the stored preference; unknown values are dropped, errors swallowed. */
function readStored(): StoredTheme {
  try {
    const raw = window.localStorage.getItem(THEME_STORAGE_KEY);
    if (raw === null) return {};
    const parsed: unknown = JSON.parse(raw);
    if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) return {};
    const record = parsed as Record<string, unknown>;
    const out: StoredTheme = {};
    if (isThemePackId(record["packId"])) out.packId = record["packId"];
    if (isThemeName(record["themeName"])) out.themeName = record["themeName"];
    return out;
  } catch {
    return {};
  }
}

function writeStored(value: StoredTheme): void {
  try {
    window.localStorage.setItem(THEME_STORAGE_KEY, JSON.stringify(value));
  } catch {
    // Storage may be unavailable or full; the preference then lasts for this session only.
  }
}

/** What the user has explicitly chosen (loaded from storage, extended by setTheme/setPack). */
let chosen: StoredTheme = readStored();

/**
 * Re-read local storage (tests, or a storage event). Resets the store to the stored preference
 * or the built-in defaults.
 */
export function reloadStoredTheme(): void {
  chosen = readStored();
  useThemeStore.setState({
    packId: chosen.packId ?? DEFAULT_THEME_PACK_ID,
    themeName: chosen.themeName ?? "light",
  });
}

/**
 * UI-only presentation state. Switching is an in-memory update plus a best-effort write to local
 * storage: no navigation, no network. It never feeds an access decision.
 */
export const useThemeStore = create<ThemeState>()((set) => ({
  themeName: chosen.themeName ?? "light",
  packId: chosen.packId ?? DEFAULT_THEME_PACK_ID,
  setTheme: (name) => {
    chosen = { ...chosen, themeName: name };
    writeStored(chosen);
    set({ themeName: name });
  },
  setPack: (packId) => {
    if (!isThemePackId(packId)) return;
    chosen = { ...chosen, packId };
    writeStored(chosen);
    set({ packId });
  },
  applyDeploymentDefault: (defaults) => {
    const next: Partial<Pick<ThemeState, "packId" | "themeName">> = {};
    if (chosen.packId === undefined && isThemePackId(defaults.packId))
      next.packId = defaults.packId;
    if (chosen.themeName === undefined && isThemeName(defaults.themeName)) {
      next.themeName = defaults.themeName;
    }
    if (Object.keys(next).length > 0) set(next);
  },
}));
