import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { MetricText, metricValueText } from "../components";
import { STRINGS } from "../strings";
import { ResizeObserverStub, known, unknownMetric } from "./fixtures";

beforeAll(() => {
  vi.stubGlobal("ResizeObserver", ResizeObserverStub);
});
afterEach(cleanup);

describe("unknown vs zero", () => {
  it("renders exactly 'unknown' for an unknown metric", () => {
    expect(metricValueText(unknownMetric())).toBe("unknown");
    expect(STRINGS.unknown).toBe("unknown");
    render(<MetricText metric={unknownMetric()} unit="USD" />);
    expect(screen.getByTestId("metric-value").textContent).toBe("unknown");
  });

  it("renders unknown for a null value even when status claims known", () => {
    expect(metricValueText({ ...known(1), value: null })).toBe("unknown");
  });

  it("renders '0' only for a real zero", () => {
    render(<MetricText metric={known(0)} />);
    expect(screen.getByTestId("metric-value").textContent).toBe("0");
  });

  it("does not show a unit next to unknown", () => {
    const { container } = render(<MetricText metric={unknownMetric()} unit="USD" />);
    expect(container.textContent).toBe("unknown");
  });

  it("marks an incomplete total explicitly", () => {
    render(<MetricText metric={{ ...known(5), complete: false }} unit="USD" />);
    const marker = screen.getByTestId("incomplete-marker");
    expect(marker.textContent).toBe(STRINGS.incompleteTotal);
    expect(within(marker.parentElement as HTMLElement).getByText("5")).toBeTruthy();
  });

  it("shows no incomplete marker on a complete total", () => {
    render(<MetricText metric={known(5)} />);
    expect(screen.queryByTestId("incomplete-marker")).toBeNull();
  });
});
