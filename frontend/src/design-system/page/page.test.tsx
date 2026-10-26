import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { axe } from "vitest-axe";
import { AppThemeProvider } from "../AppThemeProvider";
import { useThemeStore } from "../theme-store";
import { THEME_NAMES } from "../tokens";
import { PageTemplate } from "./index";

afterEach(() => {
  cleanup();
  useThemeStore.setState({ themeName: "light" });
});

describe("PageTemplate v2", () => {
  it("keeps every v1 prop and exactly one h1", () => {
    render(
      <AppThemeProvider>
        <PageTemplate
          title="Review queue"
          description="Pending items"
          actions={<span>act</span>}
          toolbar={<span>filter</span>}
          toolbarLabel="Queue filters"
          busy
          data-testid="page"
        >
          <p>body</p>
        </PageTemplate>
      </AppThemeProvider>,
    );
    expect(screen.getAllByRole("heading")).toHaveLength(1);
    expect(screen.getByRole("heading", { level: 1, name: "Review queue" })).toBeTruthy();
    expect(screen.getByText("Pending items")).toBeTruthy();
    expect(screen.getByText("act")).toBeTruthy();
    expect(screen.getByRole("group", { name: "Queue filters" })).toBeTruthy();
    const region = screen.getByTestId("page");
    expect(region.getAttribute("aria-busy")).toBe("true");
    expect(screen.getByRole("region", { name: "Review queue" })).toBe(region);
  });

  it("renders kpis, layout and density additively", () => {
    const { container } = render(
      <AppThemeProvider>
        <PageTemplate title="T" kpis={<span>kpi-a</span>} layout="grid">
          <p>body</p>
        </PageTemplate>
      </AppThemeProvider>,
    );
    expect(container.querySelector("[data-slot='page-kpis']")?.textContent).toBe("kpi-a");
    expect(container.querySelector("[data-layout='grid']")).not.toBeNull();
    expect(container.querySelector("[data-density]")?.getAttribute("data-density")).toMatch(
      /^(compact|comfortable)$/,
    );
    expect(screen.getAllByRole("heading")).toHaveLength(1);
  });

  it("defaults to stack layout and omits the kpi row", () => {
    const { container } = render(
      <AppThemeProvider>
        <PageTemplate title="T">
          <p>body</p>
        </PageTemplate>
      </AppThemeProvider>,
    );
    expect(container.querySelector("[data-layout='stack']")).not.toBeNull();
    expect(container.querySelector("[data-slot='page-kpis']")).toBeNull();
  });

  for (const name of THEME_NAMES) {
    it(`is axe clean in ${name}`, async () => {
      useThemeStore.setState({ themeName: name });
      const { container } = render(
        <AppThemeProvider>
          <PageTemplate title="T" toolbar={<span>f</span>} kpis={<span>k</span>}>
            <p>body</p>
          </PageTemplate>
        </AppThemeProvider>,
      );
      const blocking = (await axe(container)).violations.filter(
        (v) => v.impact === "serious" || v.impact === "critical",
      );
      expect(blocking.map((v) => v.id)).toEqual([]);
    });
  }
});
