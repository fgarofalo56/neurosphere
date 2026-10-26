import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { axe } from "vitest-axe";
import { UI_STYLE_IDS } from "../../../design-system";
import MockupGallery, { MOCKUP_MODES, MOCKUP_PAGES, MockupView, parseMockupPath } from "./index";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const COMBOS = MOCKUP_PAGES.flatMap((page) =>
  UI_STYLE_IDS.flatMap((styleId) => MOCKUP_MODES.map((mode) => ({ page, styleId, mode }))),
);

describe("mockup gallery", () => {
  it("covers 3 pages x 2 styles x 2 modes", () => {
    expect(COMBOS).toHaveLength(12);
  });

  it("parses mockup paths and rejects unknown ones", () => {
    expect(parseMockupPath("/__mockups/home/ops-console/dark")).toEqual({
      page: "home",
      styleId: "ops-console",
      mode: "dark",
    });
    expect(parseMockupPath("/__mockups/home/nope/dark")).toBeNull();
    expect(parseMockupPath("/__mockups/home/ops-console")).toBeNull();
    expect(parseMockupPath("/home")).toBeNull();
  });

  it("renders an index of links for an incomplete path", () => {
    const { container } = render(<MockupGallery pathname="/__mockups/" />);
    expect(container.querySelectorAll("a")).toHaveLength(12);
  });

  for (const sel of COMBOS) {
    it(`renders ${sel.page} / ${sel.styleId} / ${sel.mode} with no network and no serious a11y violations`, async () => {
      const fetchSpy = vi.fn();
      vi.stubGlobal("fetch", fetchSpy);
      const { container } = render(<MockupView {...sel} />);
      expect(container.querySelector("[data-ui-style]")?.getAttribute("data-ui-style")).toBe(
        sel.styleId,
      );
      expect(container.querySelector("[data-theme]")?.getAttribute("data-theme")).toBe(sel.mode);
      expect(container.querySelector("header [data-slot='neurosphere-wordmark']")).not.toBeNull();
      expect(container.querySelector("h1")).not.toBeNull();
      const results = await axe(container, { rules: { "color-contrast": { enabled: false } } });
      const blocking = results.violations.filter(
        (v) => v.impact === "serious" || v.impact === "critical",
      );
      expect(blocking.map((v) => `${v.id}: ${v.help}`)).toEqual([]);
      expect(fetchSpy).not.toHaveBeenCalled();
      vi.unstubAllGlobals();
    });
  }

  it("cost dashboard shows unknown gaps, incomplete points and a legend", () => {
    const { container } = render(
      <MockupView page="cost-dashboard" styleId="ops-console" mode="dark" />,
    );
    expect(container.querySelectorAll("[data-testid='gap-marker']").length).toBeGreaterThan(0);
    expect(container.querySelectorAll("[data-testid='incomplete-marker']").length).toBeGreaterThan(
      0,
    );
    expect(container.querySelectorAll("[aria-label='Chart legend']")).toHaveLength(2);
  });

  it("map mockup draws 20-40 labelled nodes", () => {
    const { container } = render(
      <MockupView page="map" styleId="enterprise-fluent" mode="light" />,
    );
    const nodes = container.querySelectorAll("[data-node]");
    expect(nodes.length).toBeGreaterThanOrEqual(20);
    expect(nodes.length).toBeLessThanOrEqual(40);
  });
});
