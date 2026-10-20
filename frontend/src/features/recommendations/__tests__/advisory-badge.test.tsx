import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { AdvisoryBadge } from "../components";
import { ResizeObserverStub, detail, detailPath, listPath, rec, setupPage } from "./fixtures";

beforeAll(() => {
  vi.stubGlobal("ResizeObserver", ResizeObserverStub);
});
afterEach(cleanup);

describe("advisory badge", () => {
  it("shows Advisory with the reason while not executable", () => {
    render(<AdvisoryBadge advisory executable={false} />);
    expect(screen.getByTestId("advisory-badge").textContent).toBe("Advisory");
    expect(screen.getByTestId("advisory-reason").textContent).toContain("action gates not passed");
  });

  it("stays Advisory even when the record says advisory is false but gates have not passed", () => {
    render(<AdvisoryBadge advisory={false} executable={false} />);
    expect(screen.getByTestId("advisory-badge").textContent).toBe("Advisory");
    expect(screen.getByTestId("advisory-reason")).toBeTruthy();
  });

  it("is shown on the detail page with advisory false", async () => {
    setupPage(detailPath(), { detail: detail(rec({ advisory: false })) });
    await screen.findByTestId("advisory-badge");
    expect(screen.getByTestId("advisory-reason").textContent).toContain("action gates not passed");
  });

  it("is shown on every list row", async () => {
    const items = [
      rec(),
      rec({
        recommendation_id: "commercial:contoso:neurosphere:recommendation:rec-0004",
        advisory: true,
      }),
    ];
    setupPage(listPath(), { list: { items, next_cursor: null } });
    await screen.findAllByTestId("recommendation-row");
    expect(screen.getAllByTestId("advisory-badge")).toHaveLength(2);
  });
});
