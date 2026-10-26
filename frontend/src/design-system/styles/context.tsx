import { createContext, useContext } from "react";
import { DEFAULT_UI_STYLE_ID, getUiStyle } from "./registry";
import { resolveUiStyle } from "./resolve";
import type { UiStyleState } from "./types";

const FALLBACK: UiStyleState = resolveUiStyle(getUiStyle(DEFAULT_UI_STYLE_ID), "light");

/** Provided by AppThemeProvider. Outside a provider the built-in default style (light) applies. */
export const UiStyleContext = createContext<UiStyleState>(FALLBACK);

/** The active style's density, chart theme, health palette and component treatment. */
export function useUiStyle(): UiStyleState {
  return useContext(UiStyleContext);
}
