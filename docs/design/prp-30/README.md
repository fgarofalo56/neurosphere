# PRP-30 mockups: operator approval checkpoint

Twelve static mockups: 3 pages (home, cost dashboard, map) x 2 UI styles (Ops console,
Enterprise Fluent) x 2 modes (light, dark). They are built from the real design-system
primitives (KpiCard, Sparkline, TimeSeriesChart, DataTable, StatusPill, HealthIndicator,
Timestamp, NeuroSphereWordmark) with fixed synthetic data, inside a static mock of the app chrome
(header with the wordmark, navigation rail with the real navigation group names). Pick one style
(and its default mode) per the Clarifications in the PRP; items 5 to 9 then restyle the real app.

The map mockup is a hand-placed static SVG that shows the intended look (node shapes, health
halos, provenance edges, legend, node detail card). It is not the WebGL map and does not use
sigma or real layout.

## What to judge

| PNG | Judge |
|---|---|
| `mockups/home-ops-console-dark.png` | Dense dark-first console. Density, KPI treatment (uppercase captions, sparkline per currency), long wrapping status pill, header and logo. |
| `mockups/home-ops-console-light.png` | Same layout in light: does the console still read as a console, are card edges and tables legible. |
| `mockups/home-enterprise-fluent-light.png` | Light-first portal. Spacing, raised cards, brand accent under the header, KPI readability, logo size. |
| `mockups/home-enterprise-fluent-dark.png` | Enterprise style in dark: colour balance, card separation, health colours. |
| `mockups/cost-dashboard-ops-console-dark.png` | Chart legibility: estimated (dashed) vs invoiced (solid) per currency, unknown gaps, incomplete markers, legend, absolute dates in the table. |
| `mockups/cost-dashboard-ops-console-light.png` | Same charts on a light console surface. |
| `mockups/cost-dashboard-enterprise-fluent-light.png` | Same charts in the roomier enterprise layout; KPI strip with freshness and analytics state. |
| `mockups/cost-dashboard-enterprise-fluent-dark.png` | Chart colours and gap markers on the dark enterprise surface. |
| `mockups/map-ops-console-dark.png` | Map look: node shapes by type, health halos, edge weight, legend card, node detail card. |
| `mockups/map-ops-console-light.png` | Same map on the light console surface. |
| `mockups/map-enterprise-fluent-light.png` | Map on the light enterprise surface; label readability. |
| `mockups/map-enterprise-fluent-dark.png` | Map on the dark enterprise surface; halo contrast. |

Things to compare across all twelve: overall density, colour and contrast, the KPI card
treatment, chart legibility, the header and logo, and whether the two styles feel clearly
different from each other.

## Re-render

From the repo root (after `pnpm install`):

```
node frontend/scripts/render-mockups.mjs
```

The script starts Vite in demo mode on port 5290 (override with `NS_MOCKUP_PORT`), drives
Chromium at 1440x900 with UTC, en-US, a fixed clock and reduced motion, and writes the PNGs to
`docs/design/prp-30/mockups/`. It stops Vite on exit. If Chromium is missing, run
`pnpm --filter @neurosphere/frontend exec playwright install chromium` once.

To look at one live, run `pnpm demo` and open
`http://127.0.0.1:5180/__mockups/<page>/<style>/<mode>`, for example
`/__mockups/home/ops-console/dark`. Pages are `home`, `cost-dashboard`, `map`; styles are
`ops-console`, `enterprise-fluent`; modes are `light`, `dark`. The route exists only in demo mode
and is not in the route manifest or any production build.

## Rework round 1

The operator reviewed the first twelve mockups and asked for five changes. All twelve PNGs were
re-rendered.

1. **Ops console is a different personality.** It is now a NOC console: near-black canvas
   (`#080a0d`) with panels lifted one step (`#12161b`) and 1px hairline borders instead of
   shadows, a slim 40px header with a "LIVE, data 38s old" freshness indicator, a compact
   184px nav, KPI values in tabular monospace numerals, and a slim status edge strip on each KPI
   card coloured by health. Charts use a cyan, teal and violet family with a subtle grid; the
   map canvas is darker with a faint grid and glowing health halos. Light mode keeps the same
   density and hairlines on a cool grey canvas. Composition differs too: Ops home is one dense
   6-across KPI row plus a 2/3 - 1/3 split; Enterprise home is a 3x2 KPI card grid, a full
   width table and two panels. Enterprise Fluent keeps its light-first, soft-elevation,
   sentence-case direction. New additive treatment fields: `panelSurface`, `kpiAccent`,
   `numerals`, `monoNumerals`, `kpiMaxAcross`, `liveIndicator`.
2. **No orphan KPI card.** `PageTemplate` now picks the KPI column count from the card count
   and the style (`kpiColumns`): 6 across in Ops console, 3x2 in Enterprise Fluent. Odd counts
   fall back to the fewest balanced rows.
3. **Uppercase only for short labels.** `StatusPill` is never uppercased. Uppercase remains only
   for KPI captions, table column headers and card section titles (Ops console).
4. **Lighter cost charts.** The mockups use the line variant. Invoiced fill opacity dropped to
   about 0.12 and estimated to about 0.03; estimated is now a dashed, clearly different colour
   (violet in Ops console, magenta in Enterprise Fluent) from the solid invoiced line, with the
   legend and the gap and incomplete markers kept. Fixture estimates sit about 12% above invoiced
   so the lines separate. In the area variant, an estimated series next to another series no
   longer gets a fill.
5. **Polish.** The activity table's Item column has a width (`DataTable` columns gained optional
   `width` and `minWidth`) so it no longer wraps to three lines. The "flat" KPI delta is a thin
   dash icon instead of a solid block.

Smaller fixes folded in: `UiStyleContext` and `StyleOverrides` are exported from the design
system root; charts treat NaN and Infinity as unknown; `Sparkline` formats its text alternative
with optional `unit` and `currency`; the mockup path prefix has a single definition
(`mockups/paths.ts`); chart input errors use the design-system `ErrorState`.
