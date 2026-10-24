# Manual accessibility test runbook

How a human tester completes `keyboard-checklist.md` and `screen-reader-checklist.md`. Allow 45 to 60 minutes. An agent may prepare this runbook and record results the tester reports, but it never performs the test or signs (PRP-24 Clarification 6). Every check here has an automated pre-check in `automated-precheck-2026-10-24.md`; this pass confirms what a machine cannot: what is actually heard, and whether the experience makes sense.

## 1. Set up (5 minutes)

1. From the repo root: `git checkout main && git pull`, then `pnpm install` and `pnpm demo`. Open the URL it prints. The demo uses a mock API and synthetic data, with no Azure and no sign-in.
2. Screen readers. The matrix needs NVDA plus one other:
   - NVDA (Windows): start it from the Start menu. The NVDA key is Insert by default.
   - Narrator (Windows, built in): Win+Ctrl+Enter toggles it.
   - VoiceOver (macOS, built in): Cmd+F5 toggles it.
3. Record the environment for the sign-off block:
   - Browser and version: `edge://version` or `chrome://version`.
   - OS build: run `winver`.
   - NVDA version: NVDA menu (Insert+N), Help, About.
   - Narrator version: the same as the Windows build.

## 2. Keyboard pass (about 20 minutes, mouse put away)

Work through every row of `keyboard-checklist.md` in light mode, then repeat the key flows in high-contrast. Switch mode in the user menu.

- Reload the page. The first Tab shows 'Skip to main content'. Enter moves focus into the main content.
- On every page, check three things: you can always see where focus is, you never get stuck, and the focus order makes sense.
- User menu: open it with Enter or Space. Use the arrow keys to change the theme mode and the theme pack. Escape closes the menu and returns focus to the trigger. Reload the page and confirm the pack you chose is still selected.
- Sandbox: Space on the 'Sandbox mode' switch shows the banner. Focus must not jump.
- `/map/table`: Tab enters the grid once. Up and Down move between rows, Enter expands a row, Home and End jump to the ends, and Tab leaves the grid.
- Charts: the Chart and Table tabs use manual activation. Arrow keys move between tabs and Enter selects one.
- Actions: 'Review and confirm' opens 'Confirm this change'. Escape closes it and returns focus to 'Review and confirm'.

## 3. Screen reader pass (about 20 minutes per reader)

Work through every row of `screen-reader-checklist.md` with NVDA, then the key flows with the second reader. Useful NVDA keys:

| Key | Does |
|---|---|
| D / Shift+D | Next / previous landmark |
| H / Shift+H | Next / previous heading |
| T | Next table; Ctrl+Alt+arrows move between cells |
| Insert+F7 | Elements list (links, headings, landmarks) |
| Insert+Space | Toggle browse and focus mode |
| Ctrl | Stop speech |

For each row, listen for three things: the right role (button, switch, dialog, table), a meaningful name, and the state (checked, expanded, selected). Note anything that is announced twice, read out of order, or missing.

## 4. Report the results

Send the results in this shape, or fill the tables directly:

```
Tester: <name>   Date: <yyyy-mm-dd>
Browser: <name version>   OS: <Windows build>
NVDA <version> | <second reader and version>
Keyboard: <row> PASS | <row> FAIL - <what happened> | ...
NVDA: <row> PASS | ...
<second reader>: <row> PASS | ...
```

Each FAIL goes into `remediation-log.md` with an owner. A signed checklist is evidence for gate G09. It is not a conformance claim, and G09 also needs Product plus legal/accessibility review (`docs/RESEARCH-AND-GATES.md`).
