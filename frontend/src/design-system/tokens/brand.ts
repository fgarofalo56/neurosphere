import type { BrandVariants } from "@fluentui/react-components";

/**
 * Neutral, Fluent-inspired brand ramp (blue). Original values; no vendor marks.
 * Agency theme packs (PRP-24) replace this ramp via design-system/themes/.
 * Hex literals are allowed only inside this tokens/ directory.
 */
export const neutralBrandRamp: BrandVariants = {
  10: "#030a14",
  20: "#071a30",
  30: "#0a2a4d",
  40: "#0c3a69",
  50: "#0e4a86",
  60: "#105aa3",
  70: "#1269c0",
  80: "#1a77d4",
  90: "#3a89dc",
  100: "#5a9be2",
  110: "#78adea",
  120: "#94bff0",
  130: "#afd0f5",
  140: "#c8e0f9",
  150: "#e0eefc",
  160: "#f3f8fe",
};

/** High-contrast palette: a small fixed set, used only by the custom HC token set. */
export const highContrastPalette = {
  black: "#000000",
  white: "#ffffff",
  yellow: "#ffff00",
  cyan: "#00ffff",
  green: "#00ff7f",
  red: "#ff6b6b",
  gray: "#1a1a1a",
} as const;
