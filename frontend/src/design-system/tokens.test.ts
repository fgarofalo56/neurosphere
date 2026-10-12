/// <reference types="vite/client" />
import { describe, expect, it } from "vitest";
import type { Theme } from "@fluentui/react-components";
import { themesByName } from "./tokens";
import type { ThemeName } from "./tokens";

const HEX = /#[0-9a-fA-F]{3,8}\b/;

describe("hex literals", () => {
  it("appear only inside design-system/tokens/", () => {
    const sources = import.meta.glob(
      ["./**/*.ts", "./**/*.tsx", "!./tokens/**", "!./**/*.test.*"],
      {
        query: "?raw",
        import: "default",
        eager: true,
      },
    ) as Record<string, string>;
    const paths = Object.keys(sources);
    expect(paths.length).toBeGreaterThan(0);
    const offenders = paths.filter((p) => HEX.test(sources[p] ?? ""));
    expect(offenders).toEqual([]);
  });

  it("leaves design-system/themes/ to PRP-24 (nothing created here)", () => {
    const themes = import.meta.glob("./themes/**", { eager: true });
    expect(Object.keys(themes)).toEqual([]);
  });
});

function channel(hex: string, start: number): number {
  const c = parseInt(hex.slice(start, start + 2), 16) / 255;
  return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
}

function luminance(hex: string): number {
  const h = hex.length === 4 ? "#" + [1, 2, 3].map((i) => hex.charAt(i).repeat(2)).join("") : hex;
  expect(h).toMatch(/^#[0-9a-fA-F]{6}$/);
  return 0.2126 * channel(h, 1) + 0.7152 * channel(h, 3) + 0.0722 * channel(h, 5);
}

function contrastRatio(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x) as [number, number];
  return (hi + 0.05) / (lo + 0.05);
}

type ColorKey = keyof Theme;

const PAIRS: readonly (readonly [ColorKey, ColorKey])[] = [
  ["colorNeutralForeground1", "colorNeutralBackground1"],
  ["colorNeutralForeground1", "colorNeutralBackground2"],
  ["colorNeutralForeground1", "colorNeutralBackground3"],
  ["colorNeutralForeground2", "colorNeutralBackground1"],
  ["colorNeutralForeground3", "colorNeutralBackground1"],
  ["colorBrandForeground1", "colorNeutralBackground1"],
  ["colorBrandForegroundLink", "colorNeutralBackground1"],
  ["colorNeutralForegroundOnBrand", "colorBrandBackground"],
  ["colorNeutralForeground1", "colorSubtleBackgroundHover"],
];

// This computed-ratio test is the real contrast guard. jsdom cannot resolve CSS custom
// properties or layout, so the axe color-contrast rule is inconclusive there (see theme tests).
describe("foreground/background token pairs meet WCAG AA 4.5:1", () => {
  const names = Object.keys(themesByName) as ThemeName[];
  for (const name of names) {
    for (const [fg, bg] of PAIRS) {
      it(`${name}: ${fg} on ${bg}`, () => {
        const theme = themesByName[name];
        const ratio = contrastRatio(String(theme[fg]), String(theme[bg]));
        expect(ratio, `${String(theme[fg])} on ${String(theme[bg])}`).toBeGreaterThanOrEqual(4.5);
      });
    }
  }
});
