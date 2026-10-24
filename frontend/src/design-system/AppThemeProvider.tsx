import { FluentProvider } from "@fluentui/react-components";
import { useMemo, type ReactNode } from "react";
import { useThemeStore } from "./theme-store";
import { getThemePack, resolveTheme } from "./themes";

export interface AppThemeProviderProps {
  children: ReactNode;
}

/** Wrap the whole app (including auth redirect screens) so everything is themed. */
export function AppThemeProvider({ children }: AppThemeProviderProps) {
  const themeName = useThemeStore((s) => s.themeName);
  const packId = useThemeStore((s) => s.packId);
  const theme = useMemo(() => resolveTheme(getThemePack(packId), themeName), [packId, themeName]);
  return (
    <FluentProvider theme={theme} data-theme={themeName} data-theme-pack={getThemePack(packId).id}>
      {children}
    </FluentProvider>
  );
}
