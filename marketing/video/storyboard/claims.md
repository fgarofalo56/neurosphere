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
---

# Explainer video claims list (source only)

Every factual claim in `storyboard.md` and `script.md`, mapped to the doc that supports it. Nothing here is reviewed. The reviewer column stays `UNREVIEWED (pending independent review)` until an independent pass signs it. Gate G09 (brand, legal, accessibility review) stays OPEN.

| ID | Claim | Doc path | Reviewer |
|---|---|---|---|
| C01 | NeuroSphere is customer-hosted AI governance for agents | docs/PRD.md | UNREVIEWED (pending independent review) |
| C02 | The walkthrough data is generated synthetic sandbox data | docs/walkthroughs/admin.md | UNREVIEWED (pending independent review) |
| C03 | The sandbox shows an isolation banner (sandbox mode banner is asserted in accessibility tests) | docs/accessibility/README.md | UNREVIEWED (pending independent review) |
| C04 | The Viewer is read only and sees a seeded cost spike (tokens 12x, volume 3x in a window) | docs/walkthroughs/viewer.md | UNREVIEWED (pending independent review) |
| C05 | The Analyst investigates a seeded latency regression, replays a trace and runs saved reports under their own scope | docs/walkthroughs/analyst.md | UNREVIEWED (pending independent review) |
| C06 | Consolidation candidates are labelled candidate and never auto-merged | docs/walkthroughs/steward.md | UNREVIEWED (pending independent review) |
| C07 | A decision shows exact target and diff, rechecks permission, honors approvals, audits and verifies the real change | docs/walkthroughs/steward.md | UNREVIEWED (pending independent review) |
| C08 | The generator injects duplicate, out-of-order and malformed events so quarantine and replay can be observed | docs/walkthroughs/admin.md | UNREVIEWED (pending independent review) |
| C09 | Admin is a scoped role with no unrestricted bypass | docs/walkthroughs/admin.md | UNREVIEWED (pending independent review) |
| C10 | Audit entries record who, the target and version, and the outcome | docs/walkthroughs/auditor.md | UNREVIEWED (pending independent review) |
| C11 | Seeded data is synthetic, so it is not evidence of compliance, authorization or ATO | docs/walkthroughs/auditor.md | UNREVIEWED (pending independent review) |
| C12 | Government support is gated by the capability matrix; availability, GA and authorization are separate; performance numbers are planning targets; unsupported combinations are disabled | docs/RESEARCH-AND-GATES.md | UNREVIEWED (pending independent review) |

Supporting docs for C12 also include `docs/PRD.md` (planning targets, section 3) and `docs/walkthroughs/admin.md` (capabilities page, unsupported combinations disabled).
