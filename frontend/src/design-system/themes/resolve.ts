import { createDarkTheme, createLightTheme } from "@fluentui/react-components";
import type { Theme } from "@fluentui/react-components";
import { highContrastTheme } from "../tokens";
import type { ThemeName } from "../tokens";
import { HC_MIN, meetsContrast } from "./contrast";
import type { ThemePack } from "./types";

/**
 * Resolves a pack to a Fluent theme for a mode, layered on the PRP-04 tokens.
 * High-contrast always starts from the PRP-04 HC set (the pack ramp is ignored);
 * pack HC overrides are applied only if every guarded pair stays at 7:1 or better.
 */
export function resolveTheme(pack: ThemePack, mode: ThemeName): Theme {
  const overrides = pack.overrides?.[mode];
  if (mode === "high-contrast") {
    if (!overrides) return highContrastTheme;
    const candidate: Theme = { ...highContrastTheme, ...overrides };
    return meetsContrast(candidate, HC_MIN) ? candidate : highContrastTheme;
  }
  const base =
    mode === "light" ? createLightTheme(pack.brandRamp) : createDarkTheme(pack.brandRamp);
  return overrides ? { ...base, ...overrides } : base;
}
