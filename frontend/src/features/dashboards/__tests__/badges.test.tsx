import { cleanup, screen, within } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { STRINGS, priceVersionText } from "../strings";
import { PV, ResizeObserverStub, costResponse, setupPage } from "./fixtures";

beforeAll(() => {
  vi.stubGlobal("ResizeObserver", ResizeObserverStub);
});
afterEach(cleanup);

describe("cost badges", () => {
  it("shows kind and price version in DOM text on every total and point", async () => {
    setupPage("/dashboards/cost?domain_id=dom-1", { cost: costResponse() });
    const blocks = await screen.findAllByTestId("series-block");
    expect(blocks).toHaveLength(2);

    const [estimated, invoiced] = blocks as [HTMLElement, HTMLElement];
    const pvText = priceVersionText(PV);
    expect(pvText).toBe("price version pv-2026-07 (effective 2026-07-01)");

    for (const [block, kind] of [
      [estimated, STRINGS.estimated],
      [invoiced, STRINGS.invoiced],
    ] as const) {
      const kinds = within(block).getAllByTestId("kind-badge");
      const prices = within(block).getAllByTestId("price-version-badge");
      // one for the total + one per point (rows)
      const rows = within(block).getAllByRole("row").length - 1;
      expect(kinds).toHaveLength(rows + 1);
      expect(prices).toHaveLength(rows + 1);
      for (const k of kinds) expect(k.textContent).toBe(kind);
      for (const p of prices) {
        expect([pvText, STRINGS.priceVersionUnknown]).toContain(p.textContent);
      }
      // every known figure carries the version text; only an unknown point may lack it
      expect(prices[0]?.textContent).toBe(pvText);
    }
  });

  it("keeps estimated and invoiced as separate series, never blended", async () => {
    setupPage("/dashboards/cost?domain_id=dom-1", { cost: costResponse() });
    await screen.findAllByTestId("series-block");
    expect(screen.getByRole("heading", { name: "Estimated cost USD" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Invoiced cost USD" })).toBeTruthy();
  });

  it("renders zero as 0, unknown as unknown, and flags the incomplete total", async () => {
    setupPage("/dashboards/cost?domain_id=dom-1", { cost: costResponse() });
    const [estimated] = (await screen.findAllByTestId("series-block")) as [HTMLElement];
    const values = within(estimated)
      .getAllByTestId("metric-value")
      .map((n) => n.textContent);
    // total, then points 0 / unknown / 12.5
    expect(values).toEqual(["12.5", "0", "unknown", "12.5"]);
    expect(within(estimated).getByTestId("incomplete-marker").textContent).toBe(
      STRINGS.incompleteTotal,
    );
  });
});
