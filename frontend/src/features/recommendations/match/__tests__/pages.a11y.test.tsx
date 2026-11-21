import { cleanup, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { axe } from "vitest-axe";
import {
  ResizeObserverStub,
  TASK,
  json,
  problem,
  setupPage,
  view,
  type Behaviour,
} from "./fixtures";

beforeAll(() => {
  vi.stubGlobal("ResizeObserver", ResizeObserverStub);
});
afterEach(cleanup);

const violations = async (container: HTMLElement): Promise<string[]> =>
  (await axe(container)).violations.map((v) => `${v.id}: ${v.help}`);

async function results(b: Behaviour = {}) {
  const user = userEvent.setup();
  const page = setupPage(b);
  await user.type(await screen.findByTestId("match-task-input"), TASK);
  await user.click(screen.getByTestId("match-submit"));
  return { user, ...page };
}

describe("find an agent accessibility", () => {
  it("empty form has no axe violations", async () => {
    const { container } = setupPage();
    await screen.findByTestId("match-acceptance-rate");
    expect(await violations(container)).toEqual([]);
  });

  it("results with cold start and partial banners have no axe violations", async () => {
    const { container } = await results({
      match: () =>
        json(
          view({
            truncated: true,
            partial_reason: "limit",
            cold_start: true,
            signals_unavailable: ["usage"],
          }),
        ),
    });
    await screen.findAllByTestId("match-candidate");
    expect(await violations(container)).toEqual([]);
  });

  it("403 state has no axe violations", async () => {
    const { container } = await results({
      match: () => problem(403, "forbidden", "data_read_required"),
    });
    await screen.findByTestId("forbidden-state");
    expect(await violations(container)).toEqual([]);
  });

  it("is keyboard operable: type, submit, accept", async () => {
    const user = userEvent.setup();
    setupPage();
    await screen.findByTestId("match-task-input");
    await user.tab();
    expect(document.activeElement).toBe(screen.getByTestId("match-task-input"));
    await user.keyboard(TASK);
    await user.tab();
    expect(document.activeElement).toBe(screen.getByTestId("match-submit"));
    await user.keyboard("{Enter}");
    await screen.findAllByTestId("match-candidate");
    const accept = screen.getAllByTestId("match-accept")[0]!;
    accept.focus();
    await user.keyboard("{Enter}");
    await vi.waitFor(() =>
      expect(screen.getAllByTestId("match-decision")[0]).toHaveTextContent("Accepted"),
    );
    expect(document.activeElement).toBe(accept);
  });
});
