# Agency theme packs (PRP-24)

A theme pack is typed presentation data layered on the PRP-04 token layer in `../tokens/`. Packs change colour and logo placement. They never change what a user is allowed to do.

## Rule: theme is presentation, never permission enforcement (NS-10)

Nothing in this directory may import from `src/api`, `src/auth`, role hooks or any authorization helper, and `ThemePack` has no role, permission, scope or route field. Authorization stays server-side and in the shared action executor. `no-api-import.test.ts` enforces the import boundary and the type shape. The app-level test that the recorded API request set is identical across themes belongs to the wiring item.

## Schema

`ThemePack` (see `types.ts`):

- `id`: stable registry key.
- `displayName`: label shown in the picker. Must be neutral or the agency's own name, never a vendor mark.
- `brandRamp`: a Fluent `BrandVariants` ramp (16 steps).
- `overrides` (optional): per-mode partial Fluent tokens for `light`, `dark`, `high-contrast`.
- `logos`: slots `header`, `login`, `reportFooter`, each `{ asset: LogoAsset | null, altText }`. Defaults are empty (`null`).

`resolveTheme(pack, mode)` returns a Fluent `Theme`. Light and dark are built from the pack ramp. High-contrast always starts from the PRP-04 high-contrast set, ignores the ramp, and applies pack overrides only if every guarded token pair keeps at least 7:1. A pack cannot weaken high-contrast.

## Colours without hex literals

Hex literals are allowed only under `design-system/tokens/` (enforced by `tokens.test.ts`). Express a pack colour as data with `rampFromHue(hue, saturation)` from `ramp.ts`, or add a ramp in `tokens/`. The ramp must still pass the contrast tests below.

## Logo allowlist

`validateLogo(asset)` throws `LogoRejectedError` with `reason` of `type`, `size` or `dimensions`.

- Types: `image/png`, `image/webp`.
- Size: 1 byte to 256 KiB.
- Dimensions: at most 1024 x 512 pixels, positive integers.

SVG is excluded on purpose. An SVG can carry script, event handlers and external references, and a client-side scan is not a safe sanitiser. Agencies export raster art instead. Logo `src` values must be same-origin or `data:` URLs. No Microsoft, Azure, partner or "powered by" marks ship in any pack.

## Adding a pack

1. Add a `ThemePack` object in `packs.ts` with a unique `id`, a neutral `displayName`, a ramp and empty or validated logos.
2. Register it in `THEME_PACKS`.
3. Run `pnpm --filter @neurosphere/frontend exec vitest run src/design-system`. Every pack is checked in light, dark and high-contrast for 4.5:1 text and 3:1 UI contrast, so a failing ramp is caught automatically.
4. Run any logo through `validateLogo` before adding it.

Unknown ids resolve to the default pack through `getThemePack`.
