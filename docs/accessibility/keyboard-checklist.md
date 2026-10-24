# Keyboard checklist

Manual keyboard test for NeuroSphere. Automated axe results are in `axe-results-2026-10-23.json` and prove nothing about operability by themselves. Test in light, dark and high-contrast; record deviations in the Notes column and log defects in `remediation-log.md`.

An automated pre-check of these rows (not a human test, does not replace this checklist) is in [`automated-precheck-2026-10-24.md`](automated-precheck-2026-10-24.md).

## Key flows

Status: OPEN (unsigned)

| Item | Expected behaviour | Result | Notes |
|---|---|---|---|
| Skip link | First Tab stop is 'Skip to main content'; Enter moves focus to the main landmark. | | |
| Primary navigation | Groups are reachable by Tab; links activate with Enter; current page is indicated. | | |
| User menu: theme picker | Menu opens with Enter or Space; light, dark and high-contrast are selectable; Escape closes and returns focus to the trigger. | | |
| User menu: theme pack picker | Packs are selectable by keyboard; the choice persists after reload; Escape closes and returns focus. | | |
| Sandbox toggle | Toggle is operable with Space; state is exposed; turning it on shows the banner without moving focus unexpectedly. | | |
| Sandbox banner | Banner is a labelled region reachable in reading order; it is not a focus trap. | | |
| Map table (treegrid) | Tab enters the grid once (roving tabindex); arrow keys move rows; Enter expands; Home and End work; Tab leaves the grid. | | |
| Map page (WebGL) | The canvas is not the only way to the data: 'View as table' is reachable; reduced-motion toggle works from the keyboard. | | |
| Chart (sandboxed iframe) | Chart/Table tabs work with arrow keys; the table is reachable without entering the iframe; focus is never trapped in the frame. | | |
| Reports | List, view, run, save dialog and share controls are operable; dialog focus is trapped while open and restored on close. | | |
| Copilot panel | Panel opens and closes by keyboard; answers and citations are reachable; focus is managed when a turn arrives. | | |
| Actions confirm dialogs | 'Review and confirm' opens the dialog; target, version and diff are reachable; Escape cancels; focus returns to the trigger. | | |

## Routes (from `frontend/src/app/route-manifest.json`)

Status: OPEN (unsigned)

| Item | Expected behaviour | Result | Notes |
|---|---|---|---|
| `/` | Reachable by URL; every control operable by keyboard alone; logical focus order; visible focus; no trap; heading structure present. | | |
| `/actions` | Reachable by URL; every control operable by keyboard alone; logical focus order; visible focus; no trap; heading structure present. | | |
| `/actions/detail` | Reachable by URL; every control operable by keyboard alone; logical focus order; visible focus; no trap; heading structure present. | | |
| `/actions/propose` | Reachable by URL; every control operable by keyboard alone; logical focus order; visible focus; no trap; heading structure present. | | |
| `/dashboards/cost` | Reachable by URL; every control operable by keyboard alone; logical focus order; visible focus; no trap; heading structure present. | | |
| `/dashboards/coverage` | Reachable by URL; every control operable by keyboard alone; logical focus order; visible focus; no trap; heading structure present. | | |
| `/dashboards/latency` | Reachable by URL; every control operable by keyboard alone; logical focus order; visible focus; no trap; heading structure present. | | |
| `/map` | Reachable by URL; every control operable by keyboard alone; logical focus order; visible focus; no trap; heading structure present. | | |
| `/map/table` | Reachable by URL; every control operable by keyboard alone; logical focus order; visible focus; no trap; heading structure present. | | |
| `/mcp-admin` | Reachable by URL; every control operable by keyboard alone; logical focus order; visible focus; no trap; heading structure present. | | |
| `/mcp-admin/server` | Reachable by URL; every control operable by keyboard alone; logical focus order; visible focus; no trap; heading structure present. | | |
| `/quality` | Reachable by URL; every control operable by keyboard alone; logical focus order; visible focus; no trap; heading structure present. | | |
| `/recommendations` | Reachable by URL; every control operable by keyboard alone; logical focus order; visible focus; no trap; heading structure present. | | |
| `/recommendations/detail` | Reachable by URL; every control operable by keyboard alone; logical focus order; visible focus; no trap; heading structure present. | | |
| `/reconciliation` | Reachable by URL; every control operable by keyboard alone; logical focus order; visible focus; no trap; heading structure present. | | |
| `/replay/traces` | Reachable by URL; every control operable by keyboard alone; logical focus order; visible focus; no trap; heading structure present. | | |
| `/reports` | Reachable by URL; every control operable by keyboard alone; logical focus order; visible focus; no trap; heading structure present. | | |
| `/reports/view` | Reachable by URL; every control operable by keyboard alone; logical focus order; visible focus; no trap; heading structure present. | | |
| `/review` | Reachable by URL; every control operable by keyboard alone; logical focus order; visible focus; no trap; heading structure present. | | |
| `/review/item` | Reachable by URL; every control operable by keyboard alone; logical focus order; visible focus; no trap; heading structure present. | | |
| `/sandbox` | Reachable by URL; every control operable by keyboard alone; logical focus order; visible focus; no trap; heading structure present. | | |
| `/workspaces/admin` | Reachable by URL; every control operable by keyboard alone; logical focus order; visible focus; no trap; heading structure present. | | |
| `/workspaces/analyst` | Reachable by URL; every control operable by keyboard alone; logical focus order; visible focus; no trap; heading structure present. | | |
| `/workspaces/auditor` | Reachable by URL; every control operable by keyboard alone; logical focus order; visible focus; no trap; heading structure present. | | |
| `/workspaces/steward` | Reachable by URL; every control operable by keyboard alone; logical focus order; visible focus; no trap; heading structure present. | | |
| `/workspaces/viewer` | Reachable by URL; every control operable by keyboard alone; logical focus order; visible focus; no trap; heading structure present. | | |

## Sign-off

Status: OPEN (unsigned)

This block is completed by a human tester only. An agent never fills it in or marks a row passed.

| Field | Value |
|---|---|
| Tester | |
| Date | |
| Assistive technology | |
| AT version | |
| Browser + version | |
| OS | |
