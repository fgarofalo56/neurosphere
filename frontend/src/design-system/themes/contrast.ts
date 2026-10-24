import type { Theme } from "@fluentui/react-components";

function channel(hex: string, start: number): number {
  const c = parseInt(hex.slice(start, start + 2), 16) / 255;
  return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
}

function luminance(hex: string): number {
  const h =
    hex.length === 4
      ? "#" +
        [1, 2, 3]
          .map((i) => hex.charAt(i))
          .map((c) => c + c)
          .join("")
      : hex;
  return 0.2126 * channel(h, 1) + 0.7152 * channel(h, 3) + 0.0722 * channel(h, 5);
}

/** WCAG 2.x contrast ratio between two 6-digit (or 3-digit) hex colours. */
export function contrastRatio(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x) as [number, number];
  return (hi + 0.05) / (lo + 0.05);
}

type ColorKey = keyof Theme;

/** Text pairs: 4.5:1 required (same set as tokens.test.ts). */
export const TEXT_PAIRS: readonly (readonly [ColorKey, ColorKey])[] = [
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

/** UI component pairs: 3:1 required (borders and focus indicators against the surface). */
export const UI_PAIRS: readonly (readonly [ColorKey, ColorKey])[] = [
  ["colorNeutralStrokeAccessible", "colorNeutralBackground1"],
  ["colorBrandStroke1", "colorNeutralBackground1"],
];

export const TEXT_MIN = 4.5;
export const UI_MIN = 3;
/** High-contrast overrides must keep at least this ratio on every guarded pair. */
export const HC_MIN = 7;

export function pairRatio(theme: Theme, fg: ColorKey, bg: ColorKey): number {
  return contrastRatio(String(theme[fg]), String(theme[bg]));
}

/** True when every guarded pair meets `min` (hex-valued tokens only). */
export function meetsContrast(theme: Theme, min: number): boolean {
  return [...TEXT_PAIRS, ...UI_PAIRS].every(([fg, bg]) => pairRatio(theme, fg, bg) >= min);
}
