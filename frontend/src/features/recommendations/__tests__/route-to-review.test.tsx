import { cleanup, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { REVIEW_ID, ResizeObserverStub, detail, detailPath, setupPage } from "./fixtures";

beforeAll(() => {
  vi.stubGlobal("ResizeObserver", ResizeObserverStub);
});
afterEach(cleanup);

describe("route to review", () => {
  it("posts the recommendation id to the review-requests path, then shows Pending review", async () => {
    const user = userEvent.setup();
    const { fetchImpl } = setupPage(detailPath(), { detail: detail() });
    await user.click(await screen.findByRole("button", { name: "Route to review" }));
    await screen.findByTestId("review-state");

    const post = fetchImpl.mock.calls.find(([, init]) => init?.method === "POST");
    expect(post).toBeDefined();
    const url = new URL(String(post?.[0]));
    expect(url.pathname).toBe(
      "/api/v1/recommendations/domains/commercial%3Acontoso%3Acatalog%3Adomain%3Afinance/review-requests",
    );
    expect(url.search).toBe("");
    expect(JSON.parse(String(post?.[1]?.body))).toEqual({
      recommendation_id: "commercial:contoso:neurosphere:recommendation:rec-0003",
    });
    expect(screen.getByTestId("review-state").textContent).toContain("Pending review");
    expect(screen.getByTestId("review-request-id").textContent).toBe(REVIEW_ID);
    expect(screen.queryByRole("button", { name: "Route to review" })).toBeNull();
  });

  it("shows Pending review from the detail response without offering the control again", async () => {
    setupPage(detailPath(), {
      detail: detail(undefined, {
        review: { state: "pending_review", review_request_id: "rev-9" },
      }),
    });
    await screen.findByTestId("review-state");
    expect(screen.getByTestId("review-request-id").textContent).toBe("rev-9");
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("surfaces a failure and keeps the control", async () => {
    const user = userEvent.setup();
    setupPage(detailPath(), { detail: detail(), reviewStatus: 403 });
    await user.click(await screen.findByRole("button", { name: "Route to review" }));
    await waitFor(() => expect(screen.getByTestId("route-error")).toBeTruthy());
    expect(screen.getByRole("button", { name: "Route to review" })).toBeTruthy();
    expect(screen.queryByTestId("review-state")).toBeNull();
  });
});
