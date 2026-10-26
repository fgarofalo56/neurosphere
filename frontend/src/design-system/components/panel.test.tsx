import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { AppThemeProvider } from "../AppThemeProvider";
import { ErrorState, Panel } from "./index";

afterEach(cleanup);

function wrap(ui: React.ReactElement): ReturnType<typeof render> {
  return render(<AppThemeProvider>{ui}</AppThemeProvider>);
}

describe("Panel", () => {
  it("renders the title as an h2 by default and h3 on request, with testId and actions", () => {
    wrap(
      <>
        <Panel title="Section" testId="p1" actions={<button type="button">Act</button>}>
          body
        </Panel>
        <Panel title="Nested" level={3} note="USD">
          body
        </Panel>
      </>,
    );
    expect(screen.getByRole("heading", { level: 2, name: "Section" })).toBeTruthy();
    expect(screen.getByRole("heading", { level: 3, name: "Nested" })).toBeTruthy();
    const root = screen.getByTestId("p1");
    expect(root.getAttribute("data-slot")).toBe("panel");
    expect(root.tagName).toBe("SECTION");
    expect(screen.getByRole("button", { name: "Act" })).toBeTruthy();
    expect(screen.getByText("USD")).toBeTruthy();
  });

  it("is only a named landmark when asked, and labels an untitled card", () => {
    wrap(
      <>
        <Panel title="Plain">x</Panel>
        <Panel title="Region" landmark="region">
          x
        </Panel>
        <Panel title="Series" level={3} landmark="group">
          x
        </Panel>
        <Panel label="Report details">x</Panel>
      </>,
    );
    expect(screen.getAllByRole("region").map((e) => e.getAttribute("aria-label") ?? "")).toContain(
      "Report details",
    );
    expect(screen.getByRole("region", { name: "Region" })).toBeTruthy();
    expect(screen.getByRole("group", { name: "Series" })).toBeTruthy();
    expect(screen.queryByRole("region", { name: "Plain" })).toBeNull();
  });
});

describe("ErrorState tone and action", () => {
  it("keeps role=alert, shows the custom action and supports the warning tone", () => {
    wrap(
      <ErrorState
        title="Denied"
        tone="warning"
        testId="e"
        action={<button type="button">Custom retry</button>}
      />,
    );
    const alert = screen.getByRole("alert");
    expect(alert.getAttribute("data-testid")).toBe("e");
    expect(screen.getByRole("button", { name: "Custom retry" })).toBeTruthy();
  });
});
