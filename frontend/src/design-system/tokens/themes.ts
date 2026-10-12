import { createDarkTheme, createLightTheme } from "@fluentui/react-components";
import type { Theme } from "@fluentui/react-components";
import { highContrastPalette as hc, neutralBrandRamp } from "./brand";

export type ThemeName = "light" | "dark" | "high-contrast";

export const THEME_NAMES: readonly ThemeName[] = ["light", "dark", "high-contrast"];

export const lightTheme: Theme = createLightTheme(neutralBrandRamp);

export const darkTheme: Theme = createDarkTheme(neutralBrandRamp);

/**
 * High-contrast is a custom Fluent v9 token set (not a legacy v8 theme):
 * black surfaces, white text, yellow accents, cyan links, strong borders.
 */
export const highContrastTheme: Theme = {
  ...darkTheme,
  colorNeutralForeground1: hc.white,
  colorNeutralForeground1Hover: hc.white,
  colorNeutralForeground1Pressed: hc.white,
  colorNeutralForeground1Selected: hc.white,
  colorNeutralForeground2: hc.white,
  colorNeutralForeground2Hover: hc.white,
  colorNeutralForeground2Pressed: hc.white,
  colorNeutralForeground2Selected: hc.white,
  colorNeutralForeground3: hc.white,
  colorNeutralForeground4: hc.white,
  colorNeutralForegroundDisabled: hc.green,
  colorNeutralForegroundInverted: hc.black,
  colorNeutralForegroundOnBrand: hc.black,
  colorBrandForeground1: hc.yellow,
  colorBrandForeground2: hc.yellow,
  colorBrandForegroundLink: hc.cyan,
  colorBrandForegroundLinkHover: hc.cyan,
  colorBrandForegroundLinkPressed: hc.cyan,
  colorNeutralBackground1: hc.black,
  colorNeutralBackground1Hover: hc.gray,
  colorNeutralBackground1Pressed: hc.gray,
  colorNeutralBackground1Selected: hc.gray,
  colorNeutralBackground2: hc.black,
  colorNeutralBackground3: hc.black,
  colorNeutralBackground4: hc.black,
  colorNeutralBackground5: hc.black,
  colorNeutralBackground6: hc.black,
  colorSubtleBackground: hc.black,
  colorSubtleBackgroundHover: hc.gray,
  colorSubtleBackgroundPressed: hc.gray,
  colorBrandBackground: hc.yellow,
  colorBrandBackgroundHover: hc.cyan,
  colorBrandBackgroundPressed: hc.cyan,
  colorBrandBackgroundSelected: hc.yellow,
  colorNeutralStroke1: hc.white,
  colorNeutralStroke1Hover: hc.yellow,
  colorNeutralStroke1Pressed: hc.yellow,
  colorNeutralStroke2: hc.white,
  colorNeutralStroke3: hc.white,
  colorNeutralStrokeAccessible: hc.white,
  colorStrokeFocus1: hc.black,
  colorStrokeFocus2: hc.yellow,
  colorBrandStroke1: hc.yellow,
  colorPaletteRedForeground1: hc.red,
  colorPaletteRedBackground3: hc.red,
};

export const themesByName: Readonly<Record<ThemeName, Theme>> = {
  light: lightTheme,
  dark: darkTheme,
  "high-contrast": highContrastTheme,
};
