# Accessibility testing

Scope: the NeuroSphere frontend (`frontend/`), every route in `frontend/src/app/route-manifest.json`, in light, dark and high-contrast modes, for each theme pack, and with sandbox mode on. This folder holds the evidence and the manual test sheets for PRP-24 item 3.

This is test evidence, not a conformance statement. NeuroSphere makes no claim of WCAG, Section 508 or any other accessibility conformance, and there is no VPAT or accessibility conformance report.

## Test basis

- WCAG 2.2 Level AA, using the axe tags `wcag2a`, `wcag2aa`, `wcag21a`, `wcag21aa`, `wcag22aa`.
- Section 508 rules that axe covers, using the tag `section508`.

## Automated suite

Location: `frontend/tests/e2e/a11y/`.

| File | What it does |
|---|---|
| `route-samples.ts` | Maps every manifest route pattern to a concrete URL the mock API serves, plus a ready selector. |
| `routes.a11y.spec.ts` | First test fails if a manifest route has no sample (or a sample is not in the manifest). Then every sample in light, dark and high-contrast, every sample with sandbox mode on (banner role and name asserted), the map table keyboard traversal, the map under `prefers-reduced-motion: reduce`, and the sandboxed chart iframe. |
| `themes.a11y.spec.ts` | Every theme pack in the three modes on home, a dashboard, the map table, a report view and the sandbox page, colour contrast included. |
| `axe-support.ts` | Shared axe configuration, preference seeding and result recording. |
| `keyboard-flows.a11y.spec.ts` | Automated keyboard pre-check: one test per key flow of `keyboard-checklist.md`, driven with real key presses. |
| `routes-keyboard.a11y.spec.ts` | Tab sweep of every manifest route in light and high-contrast: visible focus, focus indicator, no trap, an h1. |
| `aria-tree.a11y.spec.ts` | Accessibility-tree pre-check for the flows and routes of `screen-reader-checklist.md` (role, name, state). |
| `precheck-support.ts` | Shared recorder; writes `frontend/test-results/a11y/precheck-results.json`. |

The three pre-check specs are evidence for the human tester, not a substitute: see [`automated-precheck-2026-10-24.md`](automated-precheck-2026-10-24.md).

Any `serious` or `critical` violation fails a test and prints rule id, impact and target selectors. Minor and moderate findings are recorded, not failed. One narrow exclusion exists: Fluent UI's `[data-tabster-dummy]` focus sentinels (logged in `remediation-log.md`).

Run it from the repo root with unique ports so it does not reuse another checkout's servers:

```
NS_E2E_APP_PORT=4371 NS_MOCK_API_PORT=4271 pnpm --filter @neurosphere/frontend exec playwright test tests/e2e/a11y --reporter=line
```

Each run writes `frontend/test-results/a11y/axe-results.json` (routes by modes by packs, violation counts by impact, rule ids). `axe-results-2026-10-23.json` here is a committed copy of one run, kept as evidence. The set of failures in it is listed in `remediation-log.md`.

## What automated axe does and does not prove

Axe finds a subset of WCAG failures that a machine can detect, such as missing names, invalid ARIA, and colour contrast of rendered text. It is necessary and not sufficient. It does not show that:

- a task can be completed with the keyboard alone, in a sensible order, without traps;
- a screen reader announces content in a useful way;
- alt text, labels and error messages are meaningful;
- the WebGL map is usable. The canvas is not machine-auditable; the table view is the accessible alternative, and reduced motion is checked through the `data-edge-animation` signals and the toggle;
- the content of the sandboxed chart iframe reads well. Axe reached the frame in the last run (see the note on the iframe record in the results file); meaning still needs a human.

## Manual checks

- [`keyboard-checklist.md`](keyboard-checklist.md)
- [`screen-reader-checklist.md`](screen-reader-checklist.md) (NVDA on Windows plus Narrator or VoiceOver)
- [`tester-runbook.md`](tester-runbook.md): step-by-step instructions for the human tester
- [`remediation-log.md`](remediation-log.md)

Every manual section is marked `Status: OPEN (unsigned)`. Only a human tester fills in the sign-off blocks. No agent has signed or passed any row.

## Gate status

Gate G09 (theme, brand and media review) is tracked in [`docs/RESEARCH-AND-GATES.md`](../RESEARCH-AND-GATES.md) (row G09). It stays OPEN until Product plus legal and accessibility review complete, using the signed checklists and a cleared remediation log.

## UI styles and visual regression (PRP-30 item 10)

The automated suite now seeds the UI style as well: `themes.a11y.spec.ts` covers 2 styles x 3 modes x 2 packs and `routes.a11y.spec.ts` covers every manifest route x 2 styles x 3 modes. The latest committed run is `axe-results-2026-10-26.json`. The manual tester runbook must cover both styles; see the 2026-10-26 section of `remediation-log.md`. Pixel baselines (`frontend/tests/e2e/visual/`) are layout evidence only, not accessibility evidence, and are authoritative on Linux CI only.
