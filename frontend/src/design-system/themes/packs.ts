import { neutralBrandRamp } from "../tokens";
import { rampFromHue } from "./ramp";
import type { LogoSlots, ThemePack } from "./types";

const EMPTY_LOGOS: LogoSlots = {
  header: { asset: null, altText: "" },
  login: { asset: null, altText: "" },
  reportFooter: { asset: null, altText: "" },
};

export const DEFAULT_THEME_PACK_ID = "default";

/** Equal to the PRP-04 neutral theme. */
export const defaultPack: ThemePack = {
  id: DEFAULT_THEME_PACK_ID,
  displayName: "Neutral",
  brandRamp: neutralBrandRamp,
  logos: EMPTY_LOGOS,
};

/** Fictional sample agency. No real marks, no vendor or partner branding. */
export const sampleAgencyPack: ThemePack = {
  id: "sample-agency",
  displayName: "Sample Agency",
  brandRamp: rampFromHue(262, 55),
  logos: EMPTY_LOGOS,
};

export const THEME_PACKS: Readonly<Record<string, ThemePack>> = {
  [defaultPack.id]: defaultPack,
  [sampleAgencyPack.id]: sampleAgencyPack,
};

/** Unknown or missing ids fall back to the default pack. */
export function getThemePack(id: string | null | undefined): ThemePack {
  if (id && Object.prototype.hasOwnProperty.call(THEME_PACKS, id)) {
    return THEME_PACKS[id] as ThemePack;
  }
  return defaultPack;
}
