import type { LogoAsset } from "./types";

/**
 * Logo allowlist. SVG is deliberately EXCLUDED: an SVG can embed script, event
 * handlers and external references, and a client-side regex scan is not a safe
 * sanitiser. Raster formats only. Agencies wanting vector art export PNG/WebP.
 */
export const ALLOWED_LOGO_MIME_TYPES: readonly string[] = ["image/png", "image/webp"];
export const MAX_LOGO_BYTES = 256 * 1024;
export const MAX_LOGO_WIDTH = 1024;
export const MAX_LOGO_HEIGHT = 512;

export type LogoRejectReason = "type" | "size" | "dimensions";

export class LogoRejectedError extends Error {
  readonly reason: LogoRejectReason;
  constructor(reason: LogoRejectReason, message: string) {
    super(message);
    this.name = "LogoRejectedError";
    this.reason = reason;
  }
}

/** Throws LogoRejectedError unless the asset is within the allowlist. */
export function validateLogo(asset: LogoAsset): LogoAsset {
  if (!ALLOWED_LOGO_MIME_TYPES.includes(asset.mimeType.toLowerCase())) {
    throw new LogoRejectedError("type", `Logo type ${asset.mimeType} is not allowed`);
  }
  if (!Number.isFinite(asset.byteSize) || asset.byteSize <= 0 || asset.byteSize > MAX_LOGO_BYTES) {
    throw new LogoRejectedError("size", `Logo must be 1 to ${MAX_LOGO_BYTES} bytes`);
  }
  const okDim = (v: number, max: number) => Number.isInteger(v) && v > 0 && v <= max;
  if (!okDim(asset.width, MAX_LOGO_WIDTH) || !okDim(asset.height, MAX_LOGO_HEIGHT)) {
    throw new LogoRejectedError(
      "dimensions",
      `Logo must be at most ${MAX_LOGO_WIDTH}x${MAX_LOGO_HEIGHT} pixels`,
    );
  }
  return asset;
}
