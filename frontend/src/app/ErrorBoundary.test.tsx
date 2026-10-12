import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ErrorBoundary } from "./ErrorBoundary";

class ApiLikeError extends Error {
  readonly correlationId = "corr-123";
}

let shouldThrow = true;
function Bomb({ error }: { readonly error: Error }) {
  if (shouldThrow) throw error;
  return <p>recovered</p>;
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  shouldThrow = true;
});

describe("ErrorBoundary", () => {
  it("shows a recoverable message instead of a blank page", () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    render(
      <ErrorBoundary>
        <Bomb error={new Error("boom")} />
      </ErrorBoundary>,
    );
    expect(screen.getByRole("alert").textContent).toContain("Something went wrong");
    expect(screen.queryByText(/Correlation ID/)).toBeNull();
  });

  it("shows the correlation ID when present", () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    render(
      <ErrorBoundary>
        <Bomb error={new ApiLikeError("boom")} />
      </ErrorBoundary>,
    );
    expect(screen.getByText("corr-123")).toBeTruthy();
  });

  it("recovers on retry once the cause is gone", () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    render(
      <ErrorBoundary>
        <Bomb error={new Error("boom")} />
      </ErrorBoundary>,
    );
    shouldThrow = false;
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(screen.getByText("recovered")).toBeTruthy();
  });
});
