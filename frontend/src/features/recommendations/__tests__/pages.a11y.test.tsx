import { cleanup, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { axe } from "vitest-axe";
import {
  ResizeObserverStub,
  coldStartRec,
  detail,
  detailPath,
  listPath,
  rec,
  setupPage,
} from "./fixtures";

beforeAll(() => {
  vi.stubGlobal("ResizeObserver", ResizeObserverStub);
});
afterEach(cleanup);

const violations = async (container: HTMLElement): Promise<string[]> =>
  (await axe(container)).violations.map((v) => `${v.id}: ${v.help}`);

describe("accessibility", () => {
  it("list page has no axe violations", async () => {
    const { container } = setupPage(listPath(), {
      list: { items: [rec(), coldStartRec()], next_cursor: "c2" },
    });
    await screen.findAllByTestId("recommendation-row");
    expect(await violations(container)).toEqual([]);
  });

  it("detail page has no axe violations", async () => {
    const { container } = setupPage(detailPath(), { detail: detail() });
    await screen.findByTestId("coverage");
    expect(await violations(container)).toEqual([]);
  });

  it("cold start detail page has no axe violations", async () => {
    const { container } = setupPage(detailPath(), { detail: detail(coldStartRec()) });
    await screen.findByTestId("insufficient-history");
    expect(await violations(container)).toEqual([]);
  });

  it("403 state has no axe violations", async () => {
    const { container } = setupPage(listPath(), { status: 403 });
    await screen.findByTestId("forbidden-state");
    expect(await violations(container)).toEqual([]);
  });

  it("list filters and Route to review are keyboard operable", async () => {
    const user = userEvent.setup();
    setupPage(detailPath(), { detail: detail() });
    await screen.findByTestId("coverage");
    await user.tab();
    expect(document.activeElement).toBe(
      screen.getByRole("link", { name: "Back to recommendations" }),
    );
    await user.tab();
    const button = screen.getByRole("button", { name: "Route to review" });
    expect(document.activeElement).toBe(button);
    await user.keyboard("{Enter}");
    await screen.findByTestId("review-state");
  });
});
