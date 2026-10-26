import { FluentProvider, makeStaticStyles, tokens } from "@fluentui/react-components";
import { useMemo, type ReactNode } from "react";
import { useThemeStore } from "./theme-store";
import { UiStyleContext, getUiStyle, resolveStyledTheme, resolveUiStyle } from "./styles";
import { getThemePack } from "./themes";

/** Class on the provider root that scopes the anchor rule below. */
export const LINK_SCOPE_CLASS = "ns-theme-root";

/**
 * Fluent does not style raw anchors, so react-router links render the browser
 * default blue (1.5:1 on dark, 2.2:1 on black; axe A11Y-001..010). One global
 * rule gives every anchor the active theme's link tokens in all modes and packs.
 * `:where()` keeps specificity at zero so Fluent Link, buttons-as-anchors and
 * nav items with their own classes still win.
 */
const useLinkStyles = makeStaticStyles(`
  :where(.${LINK_SCOPE_CLASS} a) {
    color: ${tokens.colorBrandForegroundLink};
    text-decoration: underline;
  }
  :where(.${LINK_SCOPE_CLASS} a:visited) { color: ${tokens.colorBrandForegroundLink}; }
  :where(.${LINK_SCOPE_CLASS} a:hover) { color: ${tokens.colorBrandForegroundLinkHover}; }
  :where(.${LINK_SCOPE_CLASS} a:active) { color: ${tokens.colorBrandForegroundLinkPressed}; }
`);

export interface AppThemeProviderProps {
  children: ReactNode;
}

/** Wrap the whole app (including auth redirect screens) so everything is themed. */
export function AppThemeProvider({ children }: AppThemeProviderProps) {
  const themeName = useThemeStore((s) => s.themeName);
  const packId = useThemeStore((s) => s.packId);
  const styleId = useThemeStore((s) => s.styleId);
  const style = getUiStyle(styleId);
  const theme = useMemo(
    () => resolveStyledTheme(getThemePack(packId), themeName, style),
    [packId, themeName, style],
  );
  const uiStyle = useMemo(() => resolveUiStyle(style, themeName), [style, themeName]);
  useLinkStyles();
  return (
    <FluentProvider
      className={LINK_SCOPE_CLASS}
      theme={theme}
      data-theme={themeName}
      data-theme-pack={getThemePack(packId).id}
      data-ui-style={style.id}
    >
      <UiStyleContext.Provider value={uiStyle}>{children}</UiStyleContext.Provider>
    </FluentProvider>
  );
}
