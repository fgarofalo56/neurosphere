import { FluentProvider } from "@fluentui/react-components";
import type { ReactNode } from "react";
import { useThemeStore } from "./theme-store";
import { themesByName } from "./tokens";

export interface AppThemeProviderProps {
  children: ReactNode;
}

/** Wrap the whole app (including auth redirect screens) so everything is themed. */
export function AppThemeProvider({ children }: AppThemeProviderProps) {
  const themeName = useThemeStore((s) => s.themeName);
  return (
    <FluentProvider theme={themesByName[themeName]} data-theme={themeName}>
      {children}
    </FluentProvider>
  );
}
