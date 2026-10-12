import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { axe } from "vitest-axe";
import { AppThemeProvider } from "./AppThemeProvider";
import { LogoSlot } from "./LogoSlot";
import { ThemeGallery } from "./ThemeGallery";
import { useThemeStore } from "./theme-store";
import { THEME_NAMES } from "./tokens";
import type { ThemeName } from "./tokens";

beforeEach(() => {
  useThemeStore.setState({ themeName: "light" });
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("theme switching", () => {
  it("switches light, dark and high-contrast at runtime without any network call", () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    const locationBefore = window.location.href;
    const { container } = render(
      <AppThemeProvider>
        <ThemeGallery />
      </AppThemeProvider>,
    );
    const root = (): HTMLElement | null => container.querySelector("[data-theme]");
    expect(root()?.getAttribute("data-theme")).toBe("light");

    const labels: Record<ThemeName, string> = {
      light: "Light",
      dark: "Dark",
      "high-contrast": "High contrast",
    };
    for (const name of ["dark", "high-contrast", "light"] as const) {
      fireEvent.click(screen.getByRole("button", { name: labels[name] }));
      expect(root()?.getAttribute("data-theme")).toBe(name);
      expect(screen.getByRole("button", { name: labels[name] }).getAttribute("aria-pressed")).toBe(
        "true",
      );
    }
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(globalThis.fetch).toBe(fetchSpy);
    expect(window.location.href).toBe(locationBefore);
    vi.unstubAllGlobals();
  });

  it("store updates apply to the provider", () => {
    const { container } = render(
      <AppThemeProvider>
        <LogoSlot />
      </AppThemeProvider>,
    );
    act(() => {
      useThemeStore.getState().setTheme("high-contrast");
    });
    expect(container.querySelector("[data-theme]")?.getAttribute("data-theme")).toBe(
      "high-contrast",
    );
  });

  it("logo slot is an empty region with no brand mark", () => {
    const { container } = render(
      <AppThemeProvider>
        <LogoSlot />
      </AppThemeProvider>,
    );
    const slot = container.querySelector("[data-slot='logo']");
    expect(slot).not.toBeNull();
    expect(slot?.childNodes.length).toBe(0);
  });
});

// jsdom cannot resolve CSS variables or layout, so axe's color-contrast rule is inconclusive
// here. The computed-ratio test in tokens.test.ts is the real contrast guard; this check
// covers the remaining serious/critical rules (names, roles, structure) in every theme.
describe("ThemeGallery axe", () => {
  for (const name of THEME_NAMES) {
    it(`has no serious or critical violations in ${name}`, async () => {
      useThemeStore.setState({ themeName: name });
      const { container } = render(
        <AppThemeProvider>
          <ThemeGallery />
        </AppThemeProvider>,
      );
      const results = await axe(container);
      const blocking = results.violations.filter(
        (v) => v.impact === "serious" || v.impact === "critical",
      );
      expect(blocking.map((v) => `${v.id}: ${v.help}`)).toEqual([]);
    });
  }
});
