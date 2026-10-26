import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { axe } from "vitest-axe";
import { AppThemeProvider } from "../AppThemeProvider";
import { useThemeStore } from "../theme-store";
import { THEME_NAMES } from "../tokens";
import {
  DataTable,
  EmptyState,
  ErrorState,
  HealthIndicator,
  KpiCard,
  LoadingState,
  StatusPill,
  Timestamp,
} from "./index";

afterEach(() => {
  cleanup();
  useThemeStore.setState({ themeName: "light" });
});

function wrap(ui: React.ReactElement): ReturnType<typeof render> {
  return render(<AppThemeProvider>{ui}</AppThemeProvider>);
}

describe("StatusPill", () => {
  it("wraps and its accessible text equals its label", () => {
    const { container } = wrap(
      <StatusPill label="Pending approval from two reviewers" tone="warning" />,
    );
    const pill = container.querySelector<HTMLElement>("[data-slot='status-pill']");
    expect(pill?.textContent).toBe("Pending approval from two reviewers");
    expect(pill?.getAttribute("aria-label")).toBeNull();
    expect(pill?.style.height).toBe("");
    expect(pill?.className).toBeTruthy();
  });
});

describe("HealthIndicator", () => {
  it("always renders an icon plus text for every state", () => {
    for (const state of ["ok", "degraded", "failing", "unknown"] as const) {
      const { container, unmount } = wrap(<HealthIndicator state={state} />);
      expect(container.querySelector("[data-slot='health-icon'] svg")).not.toBeNull();
      expect((container.textContent ?? "").trim().length).toBeGreaterThan(0);
      unmount();
    }
    wrap(<HealthIndicator state="degraded" label="Lagging" />);
    expect(screen.getByText("Lagging")).toBeTruthy();
  });
});

describe("Timestamp", () => {
  const now = "2026-03-04T12:00:00Z";

  it("renders time[datetime], relative text and absolute value in name and title", () => {
    const { container } = wrap(<Timestamp value="2026-03-04T09:00:00Z" now={now} />);
    const el = container.querySelector("time");
    expect(el?.getAttribute("datetime")).toBe("2026-03-04T09:00:00.000Z");
    expect(el?.textContent).toContain("3 hours ago");
    expect(el?.textContent).toContain("2026-03-04 09:00 UTC");
    expect(el?.getAttribute("title")).toBe("2026-03-04 09:00 UTC");
  });

  it("formats day grain in UTC even under a western time zone", () => {
    vi.stubEnv("TZ", "America/Los_Angeles");
    try {
      const { container } = wrap(<Timestamp value="2026-03-04T00:00:00Z" grain="day" />);
      const el = container.querySelector("time");
      expect(el?.getAttribute("datetime")).toBe("2026-03-04");
      expect(el?.textContent).toContain("2026-03-04");
      expect(el?.textContent).not.toContain("2026-03-03");
    } finally {
      vi.unstubAllEnvs();
    }
  });

  it("renders null and invalid as unknown, with no time element", () => {
    for (const v of [null, undefined, "garbage"]) {
      const { container, unmount } = wrap(<Timestamp value={v} />);
      expect(container.textContent).toBe("unknown");
      expect(container.querySelector("time")).toBeNull();
      unmount();
    }
  });
});

describe("KpiCard", () => {
  it("shows label, value, delta, status and sparkline slot without headings", () => {
    wrap(
      <KpiCard
        label="Spend"
        value="$12.00"
        delta={{ text: "+4%", direction: "up" }}
        status="ok"
        sparkline={<svg aria-hidden="true" data-testid="spark" />}
      />,
    );
    expect(screen.getByRole("group", { name: "Spend" })).toBeTruthy();
    expect(screen.getByText("$12.00")).toBeTruthy();
    expect(screen.getByText(/\+4%/)).toBeTruthy();
    expect(screen.getByText("Healthy")).toBeTruthy();
    expect(screen.getByTestId("spark")).toBeTruthy();
    expect(screen.queryAllByRole("heading")).toHaveLength(0);
  });
});

describe("DataTable", () => {
  it("renders headers and rows", () => {
    wrap(
      <DataTable
        label="Agents"
        columns={[{ key: "n", header: "Name", render: (r: { n: string }) => r.n }]}
        rows={[{ n: "alpha" }, { n: "beta" }]}
        getRowId={(r) => r.n}
      />,
    );
    expect(screen.getByRole("table", { name: "Agents" })).toBeTruthy();
    expect(screen.getByText("alpha")).toBeTruthy();
    expect(screen.getAllByRole("row")).toHaveLength(3);
  });
});

describe("states", () => {
  it("empty, loading and error render without headings", () => {
    wrap(
      <>
        <EmptyState title="Nothing yet" description="Add one" />
        <LoadingState label="Loading agents" />
        <ErrorState title="Failed" message="Try later" onRetry={() => undefined} />
      </>,
    );
    expect(screen.getByText("Nothing yet")).toBeTruthy();
    expect(screen.getByRole("alert").textContent).toContain("Failed");
    expect(screen.getByRole("button", { name: "Try again" })).toBeTruthy();
    expect(screen.queryAllByRole("heading")).toHaveLength(0);
  });
});

describe("axe on every primitive", () => {
  for (const name of THEME_NAMES) {
    it(`has no serious or critical violations in ${name}`, async () => {
      useThemeStore.setState({ themeName: name });
      const { container } = wrap(
        <div>
          <StatusPill label="Active" tone="success" />
          <HealthIndicator state="failing" />
          <Timestamp value="2026-03-04T09:00:00Z" now="2026-03-04T12:00:00Z" />
          <Timestamp value={null} />
          <KpiCard
            label="Spend"
            value="unknown"
            delta={{ text: "-1%", direction: "down" }}
            status="unknown"
          />
          <DataTable
            label="Rows"
            columns={[{ key: "a", header: "A", render: (r: { a: string }) => r.a }]}
            rows={[{ a: "x" }]}
            getRowId={(r) => r.a}
          />
          <EmptyState title="Empty" />
          <LoadingState />
          <ErrorState title="Bad" onRetry={() => undefined} />
        </div>,
      );
      const blocking = (await axe(container)).violations.filter(
        (v) => v.impact === "serious" || v.impact === "critical",
      );
      expect(blocking.map((v) => `${v.id}: ${v.help}`)).toEqual([]);
    });
  }
});
