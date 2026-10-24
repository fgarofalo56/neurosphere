import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { AppThemeProvider, LINK_SCOPE_CLASS } from "./AppThemeProvider";
import { useThemeStore } from "./theme-store";

/**
 * jsdom's CSSOM drops `:where()` rules, so the rule body and the computed
 * contrast are proven by the Playwright axe suite (tests/e2e/a11y). Here we
 * assert the wiring: every anchor sits under the scoped provider root in every
 * theme, and the scope class stays on the FluentProvider element.
 */
describe("global link colour (A11Y-001..010)", () => {
  it.each(["light", "dark", "high-contrast"] as const)("scopes anchors in %s", (name) => {
    useThemeStore.setState({ themeName: name });
    const { container } = render(
      <AppThemeProvider>
        <nav>
          <a href="/x">plain</a>
        </nav>
      </AppThemeProvider>,
    );
    const root = container.querySelector(`.${LINK_SCOPE_CLASS}`);
    expect(root).not.toBeNull();
    expect(root?.classList.contains("fui-FluentProvider")).toBe(true);
    expect(root?.getAttribute("data-theme")).toBe(name);
    expect(root?.querySelector("a")?.closest(`.${LINK_SCOPE_CLASS}`)).toBe(root);
  });
});
