import { cleanup, screen, within } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { ResizeObserverStub, coldStartRec, detail, detailPath, rec, setupPage } from "./fixtures";

beforeAll(() => {
  vi.stubGlobal("ResizeObserver", ResizeObserverStub);
});
afterEach(cleanup);

const text = (id: string): string => screen.getByTestId(id).textContent ?? "";

describe("recommendation detail", () => {
  it("requests the contract path with the domain as a path segment", async () => {
    const { fetchImpl } = setupPage(detailPath(), { detail: detail() });
    await screen.findByTestId("coverage");
    const url = new URL(String(fetchImpl.mock.calls[0]?.[0]));
    expect(url.pathname).toBe(
      "/api/v1/recommendations/domains/commercial%3Acontoso%3Acatalog%3Adomain%3Afinance/items/commercial%3Acontoso%3Aneurosphere%3Arecommendation%3Arec-0003",
    );
    expect(url.search).toBe("");
  });

  it("renders every field of a fully populated recommendation", async () => {
    setupPage(detailPath(), { detail: detail() });
    await screen.findByTestId("coverage");
    expect(screen.getByRole("heading", { level: 1, name: "Model right-sizing" })).toBeTruthy();
    expect(text("score")).toBe("0.64");
    expect(text("evidence-window")).toBe("2026-09-10T00:00:00Z to 2026-10-10T00:00:00Z");
    expect(text("coverage")).toBe("sampled, observed 20%");
    expect(text("uncertainty")).toBe("confidence_interval: lower 0.51, upper 0.74, level 0.9");
    expect(text("prerequisites")).toContain("quality_regression_test: unmet");
    expect(text("prerequisites")).toContain("tool_compatibility: met");
    expect(text("owner")).toBe("commercial:contoso:entra:owner:team-support (inferred)");
    expect(text("generator")).toBe("rule.right-sizing 1.2.0");
    expect(text("evidence-ids")).toBe("ev:eval:offline-42");
    expect(
      screen.getByText("commercial:contoso:foundry:model_deployment:gpt-large-eastus"),
    ).toBeTruthy();
  });

  it("labels the projected estimate with price version and effective date, never savings", async () => {
    const { container } = setupPage(detailPath(), { detail: detail() });
    await screen.findByTestId("estimate");
    expect(screen.getByRole("heading", { level: 2, name: "Estimate" })).toBeTruthy();
    expect(text("price-version")).toBe(
      "price version azure-retail-2026-10-01 (effective 2026-10-01)",
    );
    const estimate = screen.getByTestId("estimate");
    expect(within(estimate).getByText("1210.50 USD")).toBeTruthy();
    expect(container.textContent?.toLowerCase()).not.toContain("saving");
  });

  it("renders unknown for every missing or null field, never 0 or blank", async () => {
    setupPage(detailPath(), { detail: detail(coldStartRec()) });
    await screen.findByTestId("coverage");
    expect(text("coverage")).toBe("unknown, observed unknown");
    expect(text("owner")).toBe("unknown");
    expect(text("generator")).toBe("unknown");
    expect(text("evidence-ids-empty")).toBe("unknown");
    expect(text("prerequisites-empty")).toBe("unknown");
    expect(text("estimate-unknown")).toContain("unknown");
    expect(text("uncertainty")).toBe("not estimable");
  });

  it("renders unknown, not a crash, when the real API sends explicit nulls", async () => {
    // The real API serialises absent optionals as null (the mock API omits them): PRP-29's
    // real-stack run crashed here on `projected_estimate: null`.
    const base = rec();
    const nulls = {
      ...base,
      projected_estimate: null,
      uncertainty: { ...base.uncertainty, level: null },
    } as unknown as Parameters<typeof rec>[0];
    setupPage(detailPath(), { detail: detail(rec(nulls)) });
    await screen.findByTestId("coverage");
    expect(text("estimate-unknown")).toContain("unknown");
    expect(text("uncertainty")).not.toContain("null");
    const amounts = { ...base.projected_estimate!, lower_amount: null, upper_amount: null };
    cleanup();
    setupPage(detailPath(), {
      detail: detail(rec({ projected_estimate: amounts } as unknown as Parameters<typeof rec>[0])),
    });
    await screen.findByTestId("estimate");
    expect(text("estimate")).not.toContain("null");
  });

  it("renders unknown for a missing estimate effective date and unbounded amounts", async () => {
    const base = rec();
    const estimate = { ...base.projected_estimate! };
    delete estimate.price_effective_date;
    delete estimate.lower_amount;
    delete estimate.upper_amount;
    setupPage(detailPath(), { detail: detail(rec({ projected_estimate: estimate })) });
    await screen.findByTestId("estimate");
    expect(text("price-version")).toBe("price version azure-retail-2026-10-01 (effective unknown)");
    expect(screen.getAllByText("unknown").length).toBeGreaterThanOrEqual(2);
  });

  it("shows Insufficient history and no score on insufficient evidence", async () => {
    setupPage(detailPath(), { detail: detail(coldStartRec()) });
    await screen.findByTestId("insufficient-history");
    expect(text("insufficient-history")).toBe("Insufficient history");
    expect(screen.queryByTestId("score")).toBeNull();
    expect(screen.queryByRole("heading", { name: "Score" })).toBeNull();
  });

  it("shows the consolidation note for candidate_duplicate", async () => {
    setupPage(detailPath(), {
      detail: detail(rec({ kind: "candidate_duplicate", advisory: true })),
    });
    await screen.findByTestId("duplicate-note");
    expect(text("duplicate-note")).toBe("Consolidation review only; never merged automatically");
  });

  it("has no execute, apply, merge or swap control, only Route to review", async () => {
    setupPage(detailPath(), { detail: detail() });
    await screen.findByTestId("coverage");
    const labels = screen.queryAllByRole("button").map((b) => b.textContent);
    expect(labels).toEqual(["Route to review"]);
    expect(
      screen.queryByRole("button", { name: /execut|apply|merge|swap|consolidate/i }),
    ).toBeNull();
  });
});
