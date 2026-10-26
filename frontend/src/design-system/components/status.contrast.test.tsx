import { describe, expect, it } from "vitest";
import { TEXT_MIN, THEME_PACKS, defaultPack, contrastRatio, resolveTheme } from "../themes";
import { UI_STYLE_IDS, getUiStyle, resolveStyledTheme } from "../styles";
import { THEME_NAMES } from "../tokens";
import { STATUS_TONE_TOKENS } from "./status";
import type { StatusTone } from "./status";

const tones = Object.keys(STATUS_TONE_TOKENS) as StatusTone[];

describe("StatusPill text contrast", () => {
  for (const pack of Object.values(THEME_PACKS)) {
    for (const styleId of UI_STYLE_IDS) {
      for (const mode of THEME_NAMES) {
        const theme = resolveStyledTheme(pack, mode, getUiStyle(styleId));
        for (const tone of tones) {
          const [fg, bg] = STATUS_TONE_TOKENS[tone];
          it(`${pack.id} / ${styleId} / ${mode}: ${tone} >= 4.5`, () => {
            expect(contrastRatio(String(theme[fg]), String(theme[bg]))).toBeGreaterThanOrEqual(
              TEXT_MIN,
            );
          });
        }
      }
    }
  }

  it("the info tone no longer uses brand foreground on brand background 2", () => {
    expect(STATUS_TONE_TOKENS.info[0]).not.toBe("colorBrandForeground1");
    const theme = resolveTheme(defaultPack, "light");
    expect(
      contrastRatio(String(theme.colorBrandForeground1), String(theme.colorBrandBackground2)),
    ).toBeLessThan(
      contrastRatio(String(theme.colorNeutralForeground1), String(theme.colorBrandBackground2)),
    );
  });
});
