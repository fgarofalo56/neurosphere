import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { ForbiddenState } from "./ForbiddenState";

// jsdom has no ResizeObserver, which Fluent MessageBar uses.
class ResizeObserverStub {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}

beforeAll(() => {
  vi.stubGlobal("ResizeObserver", ResizeObserverStub);
});
afterEach(() => {
  cleanup();
});

describe("ForbiddenState", () => {
  it("names the workspace and shows the reference", () => {
    render(<ForbiddenState workspace="Admin" correlationId="abc-1" />);
    const el = screen.getByTestId("forbidden-state");
    expect(el.textContent).toContain("Admin workspace");
    expect(el.textContent).toContain("abc-1");
  });

  it("does not claim the UI enforces access", () => {
    render(<ForbiddenState workspace="Admin" />);
    const text = (screen.getByTestId("forbidden-state").textContent ?? "").toLowerCase();
    expect(text).toContain("service declined");
    expect(text).not.toMatch(/enforc|protected by|blocked by the (ui|app)/);
  });
});
