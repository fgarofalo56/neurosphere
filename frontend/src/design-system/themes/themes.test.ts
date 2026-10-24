import { describe, expect, it } from "vitest";
import { THEME_NAMES } from "../tokens";
import {
  ALLOWED_LOGO_MIME_TYPES,
  HC_MIN,
  LOGO_SLOT_NAMES,
  LogoRejectedError,
  MAX_LOGO_BYTES,
  MAX_LOGO_HEIGHT,
  MAX_LOGO_WIDTH,
  TEXT_MIN,
  TEXT_PAIRS,
  THEME_PACKS,
  UI_MIN,
  UI_PAIRS,
  defaultPack,
  getThemePack,
  pairRatio,
  resolveTheme,
  sampleAgencyPack,
  validateLogo,
} from "./index";
import type { LogoAsset, ThemePack } from "./index";
import { highContrastTheme, lightTheme, darkTheme } from "../tokens";

const packs = Object.values(THEME_PACKS);

describe("shipped packs meet WCAG 2.2 AA in every mode", () => {
  for (const pack of packs) {
    for (const mode of THEME_NAMES) {
      const theme = resolveTheme(pack, mode);
      for (const [fg, bg] of TEXT_PAIRS) {
        it(`${pack.id} ${mode}: ${fg} on ${bg} >= 4.5`, () => {
          expect(pairRatio(theme, fg, bg)).toBeGreaterThanOrEqual(TEXT_MIN);
        });
      }
      for (const [fg, bg] of UI_PAIRS) {
        it(`${pack.id} ${mode}: ${fg} vs ${bg} >= 3`, () => {
          expect(pairRatio(theme, fg, bg)).toBeGreaterThanOrEqual(UI_MIN);
        });
      }
    }
  }
});

describe("resolveTheme", () => {
  it("default pack equals the PRP-04 neutral themes", () => {
    expect(resolveTheme(defaultPack, "light")).toEqual(lightTheme);
    expect(resolveTheme(defaultPack, "dark")).toEqual(darkTheme);
    expect(resolveTheme(defaultPack, "high-contrast")).toEqual(highContrastTheme);
  });

  it("sample pack changes brand colours in light mode", () => {
    expect(resolveTheme(sampleAgencyPack, "light").colorBrandBackground).not.toBe(
      lightTheme.colorBrandBackground,
    );
  });

  it("keeps the HC tokens regardless of pack ramp", () => {
    expect(resolveTheme(sampleAgencyPack, "high-contrast")).toEqual(highContrastTheme);
  });

  it("ignores a high-contrast override that weakens contrast", () => {
    const weak: ThemePack = {
      ...defaultPack,
      id: "weak",
      overrides: { "high-contrast": { colorNeutralForeground1: "#777777" } },
    };
    expect(resolveTheme(weak, "high-contrast")).toEqual(highContrastTheme);
  });

  it("applies a safe high-contrast override", () => {
    const safe: ThemePack = {
      ...defaultPack,
      id: "safe",
      overrides: { "high-contrast": { colorBrandForegroundLink: "#ffffff" } },
    };
    const t = resolveTheme(safe, "high-contrast");
    expect(t.colorBrandForegroundLink).toBe("#ffffff");
    for (const [fg, bg] of TEXT_PAIRS) {
      expect(pairRatio(t, fg, bg)).toBeGreaterThanOrEqual(HC_MIN);
    }
  });
});

describe("logo validator", () => {
  const ok: LogoAsset = {
    src: "/logos/sample.png",
    mimeType: "image/png",
    byteSize: 1024,
    width: 200,
    height: 80,
  };
  const reasonOf = (asset: LogoAsset) => {
    try {
      validateLogo(asset);
    } catch (e) {
      expect(e).toBeInstanceOf(LogoRejectedError);
      return (e as LogoRejectedError).reason;
    }
    return "accepted";
  };

  it("accepts every allowlisted type", () => {
    for (const mimeType of ALLOWED_LOGO_MIME_TYPES) {
      expect(reasonOf({ ...ok, mimeType })).toBe("accepted");
    }
  });
  it("rejects SVG and other types", () => {
    expect(reasonOf({ ...ok, mimeType: "image/svg+xml" })).toBe("type");
    expect(reasonOf({ ...ok, mimeType: "text/html" })).toBe("type");
  });
  it("rejects oversize and empty files", () => {
    expect(reasonOf({ ...ok, byteSize: MAX_LOGO_BYTES + 1 })).toBe("size");
    expect(reasonOf({ ...ok, byteSize: 0 })).toBe("size");
  });
  it("rejects bad dimensions", () => {
    expect(reasonOf({ ...ok, width: MAX_LOGO_WIDTH + 1 })).toBe("dimensions");
    expect(reasonOf({ ...ok, height: MAX_LOGO_HEIGHT + 1 })).toBe("dimensions");
    expect(reasonOf({ ...ok, width: 0 })).toBe("dimensions");
    expect(reasonOf({ ...ok, height: 10.5 })).toBe("dimensions");
  });
});

describe("registry", () => {
  it("returns known packs", () => {
    expect(getThemePack("sample-agency")).toBe(sampleAgencyPack);
  });
  it("falls back to default for unknown, empty, null and prototype ids", () => {
    for (const id of ["nope", "", null, undefined, "__proto__", "constructor"]) {
      expect(getThemePack(id)).toBe(defaultPack);
    }
  });
  it("registry keys match pack ids", () => {
    for (const [key, pack] of Object.entries(THEME_PACKS)) expect(pack.id).toBe(key);
  });
});

describe("shipped pack data", () => {
  const MARKS = /microsoft|azure|windows|fluent logo|powered by/i;
  it("has empty logo slots and no vendor marks", () => {
    for (const pack of packs) {
      expect(pack.id).not.toMatch(MARKS);
      expect(pack.displayName).not.toMatch(MARKS);
      for (const slot of LOGO_SLOT_NAMES) {
        const spec = pack.logos[slot];
        expect(spec.asset).toBeNull();
        expect(spec.altText).not.toMatch(MARKS);
      }
    }
  });
});
