import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { axe } from "vitest-axe";
import { AppThemeProvider } from "./AppThemeProvider";
import { LogoSlot } from "./LogoSlot";
import { ThemeGallery } from "./ThemeGallery";
import { THEME_STORAGE_KEY, reloadStoredTheme, useThemeStore } from "./theme-store";
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

describe("theme persistence", () => {
  beforeEach(() => {
    window.localStorage.clear();
    reloadStoredTheme();
  });

  afterEach(() => {
    window.localStorage.clear();
    reloadStoredTheme();
  });

  it("persists mode and pack under one key and restores them", () => {
    act(() => {
      useThemeStore.getState().setTheme("dark");
      useThemeStore.getState().setPack("sample-agency");
    });
    expect(JSON.parse(window.localStorage.getItem(THEME_STORAGE_KEY) ?? "null")).toEqual({
      themeName: "dark",
      packId: "sample-agency",
    });
    useThemeStore.setState({ themeName: "light", packId: "default" });
    reloadStoredTheme();
    expect(useThemeStore.getState().themeName).toBe("dark");
    expect(useThemeStore.getState().packId).toBe("sample-agency");
  });

  it("falls back to defaults for unknown or corrupt stored values", () => {
    window.localStorage.setItem(THEME_STORAGE_KEY, JSON.stringify({ packId: "x", themeName: "y" }));
    reloadStoredTheme();
    expect(useThemeStore.getState().packId).toBe("default");
    expect(useThemeStore.getState().themeName).toBe("light");
    window.localStorage.setItem(THEME_STORAGE_KEY, "{not json");
    reloadStoredTheme();
    expect(useThemeStore.getState().packId).toBe("default");
  });

  it("ignores an unknown pack id and survives storage errors", () => {
    useThemeStore.getState().setPack("not-a-pack");
    expect(useThemeStore.getState().packId).toBe("default");
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("quota");
    });
    expect(() => {
      useThemeStore.getState().setTheme("dark");
    }).not.toThrow();
    expect(useThemeStore.getState().themeName).toBe("dark");
  });

  it("deployment default applies only where the user has not chosen", () => {
    useThemeStore.getState().applyDeploymentDefault({ packId: "sample-agency", themeName: "dark" });
    expect(useThemeStore.getState().packId).toBe("sample-agency");
    expect(useThemeStore.getState().themeName).toBe("dark");
    window.localStorage.clear();
    reloadStoredTheme();
    act(() => {
      useThemeStore.getState().setTheme("light");
    });
    useThemeStore.getState().applyDeploymentDefault({ themeName: "dark" });
    expect(useThemeStore.getState().themeName).toBe("light");
  });

  it("sets data-theme-pack on the provider", () => {
    act(() => {
      useThemeStore.getState().setPack("sample-agency");
    });
    const { container } = render(
      <AppThemeProvider>
        <LogoSlot />
      </AppThemeProvider>,
    );
    expect(container.querySelector("[data-theme]")?.getAttribute("data-theme-pack")).toBe(
      "sample-agency",
    );
  });
});
