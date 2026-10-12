import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { AppThemeProvider } from "./AppThemeProvider";
import { NODE_TYPES, NodeTypeIcon, nodeTypeLabel, nodeTypeShape } from "./icons";

afterEach(cleanup);

describe("NodeTypeIcon", () => {
  it("exposes an accessible name for every node type", () => {
    render(
      <AppThemeProvider>
        {NODE_TYPES.map((t) => (
          <NodeTypeIcon key={t} type={t} />
        ))}
      </AppThemeProvider>,
    );
    for (const t of NODE_TYPES) {
      expect(screen.getByRole("img", { name: `${nodeTypeLabel(t)} node` })).toBeTruthy();
    }
  });

  it("differs by shape and label per type, not color alone", () => {
    const shapes = NODE_TYPES.map(nodeTypeShape);
    const labels = NODE_TYPES.map(nodeTypeLabel);
    expect(new Set(shapes).size).toBe(NODE_TYPES.length);
    expect(new Set(labels).size).toBe(NODE_TYPES.length);
  });

  it("renders distinct glyph geometry per type", () => {
    const { container } = render(
      <AppThemeProvider>
        {NODE_TYPES.map((t) => (
          <NodeTypeIcon key={t} type={t} />
        ))}
      </AppThemeProvider>,
    );
    const glyphs = Array.from(container.querySelectorAll("svg")).map((s) => s.innerHTML);
    expect(new Set(glyphs).size).toBe(NODE_TYPES.length);
  });

  it("shows a visible text label when requested", () => {
    render(
      <AppThemeProvider>
        <NodeTypeIcon type="sub-agent" showLabel />
      </AppThemeProvider>,
    );
    expect(screen.getByText("Sub-agent")).toBeTruthy();
  });
});
