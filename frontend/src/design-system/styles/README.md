# UI styles (PRP-30)

A UI style is typed presentation data layered on the mode and pack tokens. It changes density, component treatment, chart theme, health palette and a few neutral surface tokens. It never changes what a user is allowed to do.

## Rule: style is presentation, never permission enforcement (NS-10)

Nothing in this directory may import from `src/api`, `src/auth`, role hooks or any authorization helper. `no-api-import.test.ts` enforces it. A style never adds or removes a request or a route.

## Composition: mode x pack x style

- The mode (`light`, `dark`, `high-contrast`) picks the base token set.
- The pack (`../themes/`) supplies the brand ramp and logos.
- The style supplies `density`, `treatment`, `chart`, `health` and optional neutral `overrides`.

`resolveStyledTheme(pack, mode, style)` resolves mode x pack first, then layers the style overrides:

1. Only keys in `STYLE_OVERRIDE_ALLOWLIST` (neutral backgrounds 2-6, neutral strokes 1-3, shadows, radii) are kept.
2. The result is used only if every PRP-24 `TEXT_PAIRS` (4.5:1) and `UI_PAIRS` (3:1) pair still passes. Otherwise all overrides are dropped.
3. In high-contrast, style colours never apply. Density and treatment still do, and chart and health use the high-contrast variants built from `highContrastPalette`.

`resolveUiStyle(style, mode)` returns what `useUiStyle()` exposes: `{ id, density, chart, health, treatment }`.

## Colours

Hex literals live only in `../tokens/styles.ts` (enforced by `tokens.test.ts`). Health `fg` and `icon` are at least 3:1 against `colorNeutralBackground1` in every style x mode. Health is always shown with an icon and text as well as colour.

## Precedence (see `../theme-store.ts`)

- Style: user choice, then deployment default, then `enterprise-fluent`.
- Mode: user choice, then deployment default, then the style's `preferredMode`.
- The style is stored as optional `styleId` in the `ns.theme` record. A record without it is never rewritten until the user picks a style.

## Adding a style

1. Add palettes to `../tokens/styles.ts` and extend `StyleKey`.
2. Add a `UiStyle` in `registry.ts` and register it in `UI_STYLES` and `UI_STYLE_IDS`.
3. Run `pnpm --filter @neurosphere/frontend exec vitest run src/design-system`. Every style x mode x pack is checked.
