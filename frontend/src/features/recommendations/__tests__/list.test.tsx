import { cleanup, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { ResizeObserverStub, coldStartRec, listPath, rec, setupPage } from "./fixtures";

beforeAll(() => {
  vi.stubGlobal("ResizeObserver", ResizeObserverStub);
});
afterEach(cleanup);

describe("recommendation list", () => {
  it("shows kind, subjects, owner, evidence status and the Advisory badge per row", async () => {
    const { fetchImpl } = setupPage(listPath(), {
      list: { items: [rec(), coldStartRec()], next_cursor: null },
    });
    const rows = await screen.findAllByTestId("recommendation-row");
    expect(rows).toHaveLength(2);
    expect(rows[0]?.textContent).toContain("Model right-sizing");
    expect(rows[0]?.textContent).toContain("support-bot/v=3");
    expect(rows[0]?.textContent).toContain("team-support");
    expect(rows[0]?.textContent).toContain("Sufficient");
    expect(rows[1]?.textContent).toContain("Insufficient history");
    expect(rows[1]?.textContent).toContain("unknown");
    const url = new URL(String(fetchImpl.mock.calls[0]?.[0]));
    expect(url.pathname).toBe(
      "/api/v1/recommendations/domains/commercial%3Acontoso%3Acatalog%3Adomain%3Afinance",
    );
    expect(url.searchParams.has("domain_id")).toBe(false);
  });

  it("sends kind and q filters and follows next_cursor", async () => {
    const user = userEvent.setup();
    const { fetchImpl } = setupPage(`${listPath()}&kind=cost_spike&q=support`, {
      list: { items: [rec()], next_cursor: "c2" },
    });
    await screen.findAllByTestId("recommendation-row");
    const first = new URL(String(fetchImpl.mock.calls[0]?.[0]));
    expect(first.searchParams.get("kind")).toBe("cost_spike");
    expect(first.searchParams.get("q")).toBe("support");
    expect(first.searchParams.has("cursor")).toBe(false);
    await user.click(screen.getByRole("button", { name: "Next page" }));
    await waitFor(() => {
      const last = new URL(String(fetchImpl.mock.calls.at(-1)?.[0]));
      expect(last.searchParams.get("cursor")).toBe("c2");
    });
  });

  it("asks for a domain and makes no request when none is selected", () => {
    const { fetchImpl } = setupPage("/recommendations", {});
    expect(screen.getByTestId("domain-required")).toBeTruthy();
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("renders the forbidden state on 403", async () => {
    setupPage(listPath(), { status: 403 });
    await screen.findByTestId("forbidden-state");
    expect(screen.getByText("You do not have access to this domain")).toBeTruthy();
    expect(screen.queryByTestId("recommendation-row")).toBeNull();
  });

  it("renders an unavailable state, not empty data, on 503", async () => {
    setupPage(listPath(), { status: 503 });
    await screen.findByTestId("unavailable-state");
    expect(screen.queryByTestId("empty-state")).toBeNull();
  });
});
