import { create } from "zustand";
import { DEFAULT_UI_STYLE_ID, getUiStyle, isUiStyleId } from "./styles";
import type { UiStyleId } from "./styles";
import { DEFAULT_THEME_PACK_ID, THEME_PACKS } from "./themes";
import { THEME_NAMES } from "./tokens";
import type { ThemeName } from "./tokens";

/** Single localStorage key holding `{ packId, themeName, styleId? }` as JSON. */
export const THEME_STORAGE_KEY = "ns.theme";

export interface ThemeState {
  themeName: ThemeName;
  packId: string;
  /** Effective UI style: user choice, then deployment default, then the built-in default. */
  styleId: UiStyleId;
  setTheme: (name: ThemeName) => void;
  setPack: (packId: string) => void;
  /**
   * Choose a UI style. Switches the mode to the style's preferredMode only if the user never
   * explicitly chose a mode.
   */
  setStyle: (styleId: UiStyleId) => void;
  /**
   * Apply the deployment-level default (from runtime config). A value the user already chose
   * (kept in local storage) wins; unknown values are ignored.
   */
  applyDeploymentDefault: (defaults: {
    packId?: string;
    themeName?: string;
    styleId?: string;
  }) => void;
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
  styleId?: UiStyleId;
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
    if (isUiStyleId(record["styleId"])) out.styleId = record["styleId"];
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

/** What the user has explicitly chosen (loaded from storage, extended by the setters). */
let chosen: StoredTheme = readStored();

/** Deployment defaults applied this session (never written to storage). */
let deployment: { packId?: string; themeName?: ThemeName; styleId?: UiStyleId } = {};

function effectiveStyle(): UiStyleId {
  return chosen.styleId ?? deployment.styleId ?? DEFAULT_UI_STYLE_ID;
}

function effectiveMode(): ThemeName {
  return chosen.themeName ?? deployment.themeName ?? getUiStyle(effectiveStyle()).preferredMode;
}

/**
 * Re-read local storage (tests, or a storage event). Resets the store to the stored preference
 * or the built-in defaults.
 */
export function reloadStoredTheme(): void {
  chosen = readStored();
  deployment = {};
  useThemeStore.setState({
    packId: chosen.packId ?? DEFAULT_THEME_PACK_ID,
    styleId: effectiveStyle(),
    themeName: effectiveMode(),
  });
}

/**
 * UI-only presentation state. Switching is an in-memory update plus a best-effort write to local
 * storage: no navigation, no network. It never feeds an access decision.
 */
export const useThemeStore = create<ThemeState>()((set) => ({
  themeName: effectiveMode(),
  packId: chosen.packId ?? DEFAULT_THEME_PACK_ID,
  styleId: effectiveStyle(),
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
  setStyle: (styleId) => {
    if (!isUiStyleId(styleId)) return;
    chosen = { ...chosen, styleId };
    writeStored(chosen);
    set({ styleId, themeName: effectiveMode() });
  },
  applyDeploymentDefault: (defaults) => {
    if (isThemePackId(defaults.packId)) deployment.packId = defaults.packId;
    if (isThemeName(defaults.themeName)) deployment.themeName = defaults.themeName;
    if (isUiStyleId(defaults.styleId)) deployment.styleId = defaults.styleId;
    const next: Partial<Pick<ThemeState, "packId" | "themeName" | "styleId">> = {};
    if (chosen.packId === undefined && deployment.packId !== undefined) {
      next.packId = deployment.packId;
    }
    // Only recompute what this call can affect, so unrelated direct state is left alone.
    if (isUiStyleId(defaults.styleId)) next.styleId = effectiveStyle();
    if (isUiStyleId(defaults.styleId) || isThemeName(defaults.themeName)) {
      next.themeName = effectiveMode();
    }
    if (Object.keys(next).length > 0) set(next);
  },
}));
