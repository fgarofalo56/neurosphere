import { cleanup, screen, within } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { confidenceText, impactText } from "../components";
import { ResizeObserverStub, coldStartRec, listPath, rec, setupPage } from "./fixtures";

beforeAll(() => {
  vi.stubGlobal("ResizeObserver", ResizeObserverStub);
});
afterEach(cleanup);

describe("recommendation cards", () => {
  it("renders each recommendation as a card with impact, confidence and an advisory pill", async () => {
    setupPage(listPath(), { list: { items: [rec(), coldStartRec()], next_cursor: null } });
    const cards = await screen.findAllByTestId("recommendation-row");
    expect(cards).toHaveLength(2);
    const first = within(cards[0] as HTMLElement);
    expect(first.getByTestId("impact").textContent).toBe("-$629.50 (monthly)");
    expect(first.getByTestId("confidence").textContent).toBe("90% interval");
    expect(first.getByTestId("advisory-badge").textContent).toBe("Advisory");
    expect(first.getByRole("link", { name: "Model right-sizing" })).toBeTruthy();
    // The created time goes through Timestamp: no raw ISO string is visible.
    expect(cards[0]?.textContent).toContain("2026-10-10 06:00 UTC");
    expect(cards[0]?.textContent).not.toContain("2026-10-10T06:00:00Z");
  });

  it("shows unknown, never 0, for a cold-start card", async () => {
    setupPage(listPath(), { list: { items: [coldStartRec()], next_cursor: null } });
    const card = within(await screen.findByTestId("recommendation-row"));
    expect(card.getByTestId("impact").textContent).toBe("unknown");
    expect(card.getByTestId("confidence").textContent).toBe("Insufficient history");
  });

  it("never words the projected change as savings", async () => {
    const { container } = setupPage(listPath(), {
      list: { items: [rec()], next_cursor: null },
    });
    await screen.findByTestId("recommendation-row");
    expect(container.textContent?.toLowerCase()).not.toContain("saving");
  });

  it("derives impact and confidence from the record", () => {
    expect(impactText(null)).toBe("unknown");
    expect(impactText({ ...rec().projected_estimate!, projected_amount: "" })).toBe("unknown");
    expect(confidenceText({ ...rec(), uncertainty: { method: "not_estimable" } })).toBe(
      "not estimable",
    );
  });
});

describe("recommendation list states", () => {
  it("shows an empty state when nothing matches", async () => {
    setupPage(listPath(), { list: { items: [], next_cursor: null } });
    await screen.findByTestId("empty-state");
    expect(screen.getByText("No recommendations match.")).toBeTruthy();
  });

  it("shows a loading state before the data arrives", () => {
    setupPage(listPath(), { list: { items: [], next_cursor: null } });
    expect(screen.getByLabelText("Loading...")).toBeTruthy();
  });

  it("shows an error state, not an empty list, when the service fails", async () => {
    setupPage(listPath(), { status: 503 });
    await screen.findByTestId("unavailable-state");
    expect(screen.getByRole("alert")).toBeTruthy();
    expect(screen.queryByTestId("empty-state")).toBeNull();
  });
});
