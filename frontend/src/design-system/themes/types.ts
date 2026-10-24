import type { BrandVariants, Theme } from "@fluentui/react-components";
import type { ThemeName } from "../tokens";

/**
 * A theme pack is presentation DATA only (NS-10): colours, logos and labels.
 * It must never carry roles, permissions, routes or API behaviour; the
 * no-api-import test enforces that for both imports and this type's fields.
 */

export type LogoSlotName = "header" | "login" | "reportFooter";

export const LOGO_SLOT_NAMES: readonly LogoSlotName[] = ["header", "login", "reportFooter"];

/** Metadata describing a logo asset an agency supplies. Validated by validateLogo. */
export interface LogoAsset {
  /** Same-origin or data: URL of the asset. Never an external host. */
  src: string;
  mimeType: string;
  byteSize: number;
  width: number;
  height: number;
}

export interface LogoSlotSpec {
  /** Null means the slot renders the neutral empty LogoSlot. */
  asset: LogoAsset | null;
  /** Accessible text for the asset; empty string for decorative. */
  altText: string;
}

export type LogoSlots = Readonly<Record<LogoSlotName, LogoSlotSpec>>;

/** Per-mode token overrides. High-contrast overrides are applied only if they stay AA-safe. */
export type ThemeOverrides = Readonly<Partial<Record<ThemeName, Partial<Theme>>>>;

export interface ThemePack {
  id: string;
  displayName: string;
  brandRamp: BrandVariants;
  overrides?: ThemeOverrides;
  logos: LogoSlots;
}
