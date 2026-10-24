# Screen reader checklist

Manual screen reader test for NeuroSphere. Automated axe results prove nothing about how content is announced. Record AT name and version at test time.

An automated pre-check of the accessibility tree behind these rows (not a human test, does not replace this checklist) is in [`automated-precheck-2026-10-24.md`](automated-precheck-2026-10-24.md).

## Assistive technology matrix

Status: OPEN (unsigned)

| Assistive technology | Platform | Browser | AT version (tester fills) | Tester | Date |
|---|---|---|---|---|---|
| NVDA | Windows | | | | |
| Narrator | Windows | | | | |
| VoiceOver | macOS | | | | |

Minimum: NVDA on Windows plus one of Narrator or VoiceOver.

## Key flows

Status: OPEN (unsigned)

| Item | Expected behaviour | Result | Notes |
|---|---|---|---|
| Skip link | Announced as a link named 'Skip to main content'; activating it lands in the main landmark. | | |
| Primary navigation | Navigation landmark named 'Primary' (an ARIA landmark, not a `nav` element; landmark navigation still finds it); groups announced; current page announced. | | |
| User menu: theme picker | Menu button, menu items and the selected state are announced; selection changes are conveyed. | | |
| User menu: theme pack picker | Pack names and the selected pack are announced; no logo is announced as meaningless text. | | |
| Sandbox toggle | Announced as a switch named 'Sandbox mode' with its state ('on' / 'off', or 'checked' / 'not checked', depending on the reader). | | |
| Sandbox banner | Region named 'Sandbox mode: synthetic data only' is announced and found by landmark navigation. | | |
| Map table (treegrid) | Grid name, row labels, expanded state and level are announced; the detail live region (polite) announces the selection. | | |
| Map page (WebGL) | Region named 'Agent topology map (WebGL graphic). The table view is the accessible equivalent.' plus coverage, truncation and live-status text are announced; the table link is found. | | |
| Chart (sandboxed iframe) | Iframe has a meaningful title; the data table is announced with its name (an `aria-label`, not a caption) and headers; sources text is read. | | |
| Reports | Table headers (Title, Publication, Updated; the owner is read inside the title cell), status and approval states are announced; dialogs announce their title on open. | | |
| Copilot panel | Turns, citations, refusals and tool notices are announced in a sensible order. | | |
| Actions confirm dialogs | Alert dialog titled 'Confirm this change' (opened by 'Review and confirm'); title, target and version are announced on open; state badges are read as text. | | |

## Routes (from `frontend/src/app/route-manifest.json`)

Status: OPEN (unsigned)

| Item | Expected behaviour | Result | Notes |
|---|---|---|---|
| `/` | Page title and main heading announced on load; landmarks present; controls have names and roles; status and error text announced; no unlabeled content. | | |
| `/actions` | Page title and main heading announced on load; landmarks present; controls have names and roles; status and error text announced; no unlabeled content. | | |
| `/actions/detail` | Page title and main heading announced on load; landmarks present; controls have names and roles; status and error text announced; no unlabeled content. | | |
| `/actions/propose` | Page title and main heading announced on load; landmarks present; controls have names and roles; status and error text announced; no unlabeled content. | | |
| `/dashboards/cost` | Page title and main heading announced on load; landmarks present; controls have names and roles; status and error text announced; no unlabeled content. | | |
| `/dashboards/coverage` | Page title and main heading announced on load; landmarks present; controls have names and roles; status and error text announced; no unlabeled content. | | |
| `/dashboards/latency` | Page title and main heading announced on load; landmarks present; controls have names and roles; status and error text announced; no unlabeled content. | | |
| `/map` | Page title and main heading announced on load; landmarks present; controls have names and roles; status and error text announced; no unlabeled content. | | |
| `/map/table` | Page title and main heading announced on load; landmarks present; controls have names and roles; status and error text announced; no unlabeled content. | | |
| `/mcp-admin` | Page title and main heading announced on load; landmarks present; controls have names and roles; status and error text announced; no unlabeled content. | | |
| `/mcp-admin/server` | Page title and main heading announced on load; landmarks present; controls have names and roles; status and error text announced; no unlabeled content. | | |
| `/quality` | Page title and main heading announced on load; landmarks present; controls have names and roles; status and error text announced; no unlabeled content. | | |
| `/recommendations` | Page title and main heading announced on load; landmarks present; controls have names and roles; status and error text announced; no unlabeled content. | | |
| `/recommendations/detail` | Page title and main heading announced on load; landmarks present; controls have names and roles; status and error text announced; no unlabeled content. | | |
| `/reconciliation` | Page title and main heading announced on load; landmarks present; controls have names and roles; status and error text announced; no unlabeled content. | | |
| `/replay/traces` | Page title and main heading announced on load; landmarks present; controls have names and roles; status and error text announced; no unlabeled content. | | |
| `/reports` | Page title and main heading announced on load; landmarks present; controls have names and roles; status and error text announced; no unlabeled content. | | |
| `/reports/view` | Page title and main heading announced on load; landmarks present; controls have names and roles; status and error text announced; no unlabeled content. | | |
| `/review` | Page title and main heading announced on load; landmarks present; controls have names and roles; status and error text announced; no unlabeled content. | | |
| `/review/item` | Page title and main heading announced on load; landmarks present; controls have names and roles; status and error text announced; no unlabeled content. | | |
| `/sandbox` | Page title and main heading announced on load; landmarks present; controls have names and roles; status and error text announced; no unlabeled content. | | |
| `/workspaces/admin` | Page title and main heading announced on load; landmarks present; controls have names and roles; status and error text announced; no unlabeled content. | | |
| `/workspaces/analyst` | Page title and main heading announced on load; landmarks present; controls have names and roles; status and error text announced; no unlabeled content. | | |
| `/workspaces/auditor` | Page title and main heading announced on load; landmarks present; controls have names and roles; status and error text announced; no unlabeled content. | | |
| `/workspaces/steward` | Page title and main heading announced on load; landmarks present; controls have names and roles; status and error text announced; no unlabeled content. | | |
| `/workspaces/viewer` | Page title and main heading announced on load; landmarks present; controls have names and roles; status and error text announced; no unlabeled content. | | |

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
