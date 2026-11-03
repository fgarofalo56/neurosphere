---
status: draft
rendered: false
claims:
  - C01
  - C02
  - C03
  - C04
  - C05
  - C06
  - C07
  - C08
  - C09
  - C10
  - C11
  - C12
  - C13
---

# Explainer video claims list (source text)

Every factual claim in `storyboard.md` and `script.md`, mapped to the doc that supports it. No row has had an independent human review. The reviewer column records an automated Claude reviewer agent pass, accepted by the owner without independent review on 2026-11-03. G09 waived by the owner (Frank Garofalo) on 2026-11-03 for demo scope; no independent brand, legal or accessibility review was performed.

| ID | Claim | Doc path | Reviewer |
|---|---|---|---|
| C01 | NeuroSphere is customer-hosted AI governance for agents | docs/PRD.md | Claude reviewer agent, automated, 2026-11-03; accepted by owner without independent review 2026-11-03 |
| C02 | The walkthrough data is generated synthetic sandbox data | docs/walkthroughs/admin.md | Claude reviewer agent, automated, 2026-11-03; accepted by owner without independent review 2026-11-03 |
| C03 | A sandbox-mode banner appears when sandbox mode is switched on, from the sandbox toggle in the user menu (the banner is asserted in accessibility tests) | docs/accessibility/README.md | Claude reviewer agent flagged, fixed 2026-11-03, accepted by owner without independent review 2026-11-03 |
| C04 | The Viewer has read-only access and sees a seeded cost spike (tokens 12x, volume 3x in a window) | docs/walkthroughs/viewer.md | Claude reviewer agent, automated, 2026-11-03; accepted by owner without independent review 2026-11-03 |
| C05 | The Analyst investigates a seeded latency regression, replays a trace and runs saved reports under their own scope | docs/walkthroughs/analyst.md | Claude reviewer agent, automated, 2026-11-03; accepted by owner without independent review 2026-11-03 |
| C06 | Consolidation candidates are labelled candidate and never auto-merged | docs/walkthroughs/steward.md | Claude reviewer agent flagged, fixed 2026-11-03, accepted by owner without independent review 2026-11-03 |
| C07 | The action executor rechecks permission, honors approvals, audits and verifies the real change; seeded demo intents stop before execution | docs/walkthroughs/steward.md | Claude reviewer agent flagged, fixed 2026-11-03, accepted by owner without independent review 2026-11-03 |
| C08 | The generator injects duplicate, out-of-order and malformed events so quarantine and replay can be observed | docs/walkthroughs/admin.md | Claude reviewer agent flagged, fixed 2026-11-03, accepted by owner without independent review 2026-11-03 |
| C09 | Admin is a scoped role with no unrestricted bypass | docs/walkthroughs/admin.md | Claude reviewer agent, automated, 2026-11-03; accepted by owner without independent review 2026-11-03 |
| C10 | Audit entries record who, the target and version, and the outcome | docs/walkthroughs/auditor.md | Claude reviewer agent flagged, fixed 2026-11-03, accepted by owner without independent review 2026-11-03 |
| C11 | Seeded data is synthetic, so it is not evidence of ATO, compliance or authorization | docs/walkthroughs/auditor.md | Claude reviewer agent, automated, 2026-11-03; accepted by owner without independent review 2026-11-03 |
| C12 | Government support is gated by the capability matrix; availability, GA and authorization are separate; performance numbers are planning targets; unsupported combinations are disabled | docs/RESEARCH-AND-GATES.md | Claude reviewer agent, automated, 2026-11-03; accepted by owner without independent review 2026-11-03 |
| C13 | Real ingestion is a supported path separate from the synthetic sandbox | docs/RESEARCH-AND-GATES.md | Added 2026-11-03 after a Claude reviewer agent finding; accepted by owner without independent review 2026-11-03 |

Supporting docs for C12 also include `docs/PRD.md` (planning targets, section 3) and `docs/walkthroughs/admin.md` (capabilities page, unsupported combinations disabled).
