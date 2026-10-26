import { FluentProvider } from "@fluentui/react-components";
import { cleanup, render, screen } from "@testing-library/react";
import type { ReactElement } from "react";
import { afterEach, describe, expect, it } from "vitest";
import { PageTemplate, countKpis, kpiColumns } from "../page";
import { UiStyleContext, getUiStyle, resolveStyledTheme, resolveUiStyle } from "../styles";
import { getThemePack } from "../themes";
import type { UiStyleId } from "../styles";
import { DataTable, KpiCard, StatusPill } from "./index";

afterEach(cleanup);

function inStyle(styleId: UiStyleId, ui: ReactElement): ReturnType<typeof render> {
  const style = getUiStyle(styleId);
  return render(
    <FluentProvider theme={resolveStyledTheme(getThemePack("default"), "dark", style)}>
      <UiStyleContext.Provider value={resolveUiStyle(style, "dark")}>{ui}</UiStyleContext.Provider>
    </FluentProvider>,
  );
}

function computed(el: Element | null, prop: string): string {
  return el === null ? "" : window.getComputedStyle(el).getPropertyValue(prop);
}

describe("treatment fields per style", () => {
  it("ops console is edge-accented, tabular, mono, lifted and live", () => {
    const t = resolveUiStyle(getUiStyle("ops-console"), "dark").treatment;
    expect(t).toMatchObject({
      kpiAccent: "edge",
      numerals: "tabular",
      monoNumerals: true,
      panelSurface: "lifted",
      liveIndicator: true,
      kpiMaxAcross: 6,
    });
  });
  it("enterprise fluent keeps cards plain and proportional", () => {
    const t = resolveUiStyle(getUiStyle("enterprise-fluent"), "light").treatment;
    expect(t).toMatchObject({
      kpiAccent: "none",
      numerals: "proportional",
      monoNumerals: false,
      panelSurface: "base",
      liveIndicator: false,
    });
  });
});

describe("StatusPill never uppercases", () => {
  for (const id of ["ops-console", "enterprise-fluent"] as const) {
    it(`${id}: no text-transform, even for sentences`, () => {
      const { container } = inStyle(
        id,
        <StatusPill tone="warning" label="Incomplete total: 3 of 14 billing days are missing" />,
      );
      const pill = container.querySelector("[data-slot='status-pill']");
      expect(computed(pill, "text-transform")).not.toBe("uppercase");
    });
  }
});

describe("KpiCard", () => {
  it("renders a flat delta as an icon, not a block glyph", () => {
    inStyle(
      "enterprise-fluent",
      <KpiCard label="Queue" value="3" delta={{ text: "same", direction: "flat" }} />,
    );
    const delta = document.querySelector("[data-slot='kpi-delta']");
    expect(delta?.querySelector("svg[data-slot='kpi-delta-icon']")).not.toBeNull();
    expect(delta?.textContent).not.toContain("▬");
  });
  it("ops console draws a status edge and tabular mono values", () => {
    const { container } = inStyle(
      "ops-console",
      <KpiCard label="Cost" value="$1" accent="failing" />,
    );
    const card = container.querySelector<HTMLElement>("[data-slot='kpi-card']");
    expect(card?.getAttribute("data-accent")).toBe("failing");
    expect(card?.style.boxShadow).toContain("inset 3px 0 0");
    const value = container.querySelector("[data-slot='kpi-value']");
    expect(computed(value, "font-variant-numeric")).toContain("tabular-nums");
    expect(screen.queryByText("Failing")).toBeNull();
  });
  it("enterprise fluent draws no edge", () => {
    const { container } = inStyle(
      "enterprise-fluent",
      <KpiCard label="Cost" value="$1" accent="ok" />,
    );
    const card = container.querySelector<HTMLElement>("[data-slot='kpi-card']");
    expect(card?.getAttribute("data-accent")).toBeNull();
    expect(card?.style.boxShadow).toBe("");
  });
});

describe("DataTable column width", () => {
  it("applies width and minWidth to header and body cells", () => {
    inStyle(
      "enterprise-fluent",
      <DataTable
        label="Rows"
        columns={[
          {
            key: "a",
            header: "Item",
            width: "45%",
            minWidth: "220px",
            render: (r: { a: string }) => r.a,
          },
          { key: "b", header: "Other", render: () => "x" },
        ]}
        rows={[{ a: "one" }]}
        getRowId={(r) => r.a}
      />,
    );
    const th = screen.getByRole("columnheader", { name: "Item" });
    expect(th.style.width).toBe("45%");
    expect(th.style.minWidth).toBe("220px");
    expect(screen.getByRole("cell", { name: "one" }).style.width).toBe("45%");
    expect(screen.getByRole("columnheader", { name: "Other" }).style.width).toBe("");
  });
});

describe("KPI grid never leaves an orphan", () => {
  it("lays out N cards in even rows", () => {
    expect(kpiColumns(6, 6)).toBe(6);
    expect(kpiColumns(6, 5)).toBe(3);
    expect(kpiColumns(4, 5)).toBe(4);
    expect(kpiColumns(5, 5)).toBe(5);
    expect(kpiColumns(8, 5)).toBe(4);
    expect(kpiColumns(7, 5)).toBe(4);
    expect(kpiColumns(1, 5)).toBe(1);
    expect(kpiColumns(0, 5)).toBe(1);
  });
  it("counts through fragments and ignores empty children", () => {
    expect(
      countKpis(
        <>
          <KpiCard label="a" value="1" />
          {false}
          <>
            <KpiCard label="b" value="2" />
            <KpiCard label="c" value="3" />
          </>
        </>,
      ),
    ).toBe(3);
  });
  it("PageTemplate sets the column count per style", () => {
    const kpis = (
      <>
        {[1, 2, 3, 4, 5, 6].map((n) => (
          <KpiCard key={n} label={`K${n}`} value={String(n)} />
        ))}
      </>
    );
    const ops = inStyle(
      "ops-console",
      <PageTemplate title="Ops" kpis={kpis}>
        x
      </PageTemplate>,
    );
    expect(
      ops.container.querySelector("[data-slot='page-kpis']")?.getAttribute("data-kpi-columns"),
    ).toBe("6");
    cleanup();
    const ent = inStyle(
      "enterprise-fluent",
      <PageTemplate title="Ent" kpis={kpis}>
        x
      </PageTemplate>,
    );
    expect(
      ent.container.querySelector("[data-slot='page-kpis']")?.getAttribute("data-kpi-columns"),
    ).toBe("3");
  });
});
