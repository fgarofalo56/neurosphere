import { create } from "zustand";
import type { ThemeName } from "./tokens";

export interface ThemeState {
  themeName: ThemeName;
  setTheme: (name: ThemeName) => void;
}

/** UI-only state: switching is a pure in-memory update (no navigation, no network, no storage). */
export const useThemeStore = create<ThemeState>()((set) => ({
  themeName: "light",
  setTheme: (name) => {
    set({ themeName: name });
  },
}));
