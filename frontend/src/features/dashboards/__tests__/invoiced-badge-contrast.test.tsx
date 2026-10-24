import { FluentProvider } from "@fluentui/react-components";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { highContrastTheme } from "../../../design-system/tokens";
import { INVOICED_BADGE_APPEARANCE, KindBadge } from "../components";

describe("invoiced kind badge contrast wiring (A11Y-003)", () => {
  it("uses the tint appearance, not filled success (black on #107c10)", () => {
    expect(INVOICED_BADGE_APPEARANCE).toBe("tint");
    render(
      <FluentProvider theme={highContrastTheme}>
        <KindBadge kind="invoiced" />
      </FluentProvider>,
    );
    const badge = screen.getByTestId("kind-badge");
    expect(badge.className).toContain("fui-Badge");
    expect(badge.textContent).toBeTruthy();
  });
});
