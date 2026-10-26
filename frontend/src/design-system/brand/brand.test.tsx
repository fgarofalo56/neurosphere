import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { axe } from "vitest-axe";
import { AppThemeProvider } from "../AppThemeProvider";
import { useThemeStore } from "../theme-store";
import { THEME_NAMES } from "../tokens";
import { NeuroSphereMark, NeuroSphereWordmark } from "./index";

afterEach(() => {
  cleanup();
  useThemeStore.setState({ themeName: "light" });
});

describe("NeuroSphere brand", () => {
  it("mark is decorative: aria-hidden, currentColor only, no text", () => {
    const { container } = render(<NeuroSphereMark />);
    const svg = container.querySelector("svg");
    expect(svg?.getAttribute("aria-hidden")).toBe("true");
    expect(svg?.querySelector("text")).toBeNull();
    expect(container.innerHTML).not.toMatch(/#[0-9a-fA-F]{3,8}\b/);
    expect(container.innerHTML).toContain("currentColor");
  });

  it("wordmark has a real text node outside the SVG", () => {
    const { container } = render(<NeuroSphereWordmark />);
    expect(screen.getByText("NeuroSphere").closest("svg")).toBeNull();
    expect(container.querySelector("svg")?.getAttribute("aria-hidden")).toBe("true");
  });

  it("source never uses dangerouslySetInnerHTML", () => {
    const sources = import.meta.glob("./NeuroSphereMark.tsx", {
      eager: true,
      query: "?raw",
      import: "default",
    });
    const src = Object.values(sources)[0];
    expect(typeof src).toBe("string");
    expect(src).not.toContain("dangerouslySetInnerHTML");
  });

  for (const name of THEME_NAMES) {
    it(`wordmark is axe clean in ${name}`, async () => {
      useThemeStore.setState({ themeName: name });
      const { container } = render(
        <AppThemeProvider>
          <NeuroSphereWordmark />
        </AppThemeProvider>,
      );
      const blocking = (await axe(container)).violations.filter(
        (v) => v.impact === "serious" || v.impact === "critical",
      );
      expect(blocking.map((v) => v.id)).toEqual([]);
    });
  }
});
