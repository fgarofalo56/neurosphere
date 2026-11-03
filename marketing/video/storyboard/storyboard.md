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

# NeuroSphere explainer video: storyboard (source text)

**This is source text. It is not a rendered video.** No audio, video, image or caption file exists for it. Rendering, narration audio and caption files are the budget-gated follow-up PRP-27. Every claim below is unreviewed (see `claims.md`) and the brand, legal and accessibility review (gate G09) stays OPEN.

## Production rules for every scene

- Visuals come from the synthetic sandbox, never production data, with the isolation banner visible in every frame. No production data, no real names, no customers.
- Neutral visual identity. No Microsoft logo, badge or partner implication. Third-party names appear as plain text, never as logos.
- Performance is stated as a PRD planning target and is labelled a target.
- Government support is described as gated by the capability matrix. Availability, GA and authorization are separate gates. No FedRAMP, ATO or parity statement.

## Timing (estimates)

Narration length and scene timing are ESTIMATES, computed as words divided by 150 words per minute, plus a one second pause per scene. They are not measured from a recording. The estimated total is stated in the last section of this file.

## Scenes

### Scene S01 Opening

- Visual: Title card on a plain neutral background, then the sandbox landing view with the isolation banner visible. Synthetic sandbox data, never production data.
- Narration: NeuroSphere is a customer-hosted governance layer for AI agents. This video walks through it using a synthetic sandbox, so everything you see is generated data.
- On-screen text: NeuroSphere | Synthetic sandbox | Source draft, not a rendered video
- Caption: NeuroSphere is a customer-hosted governance layer for AI agents. This video uses a synthetic sandbox, so everything you see is generated data.
- Claims: C01, C02
- Sources: docs/PRD.md, docs/walkthroughs/admin.md
- Duration estimate: 11 s

### Scene S02 Sandbox isolation

- Visual: The sandbox page (`/sandbox`) with the isolation banner highlighted. Synthetic sandbox data, never production data.
- Narration: The sandbox is isolated from real data. The banner stays on screen so you always know you are looking at synthetic content. Real ingestion needs approved connectors, and the demo never uses production data.
- On-screen text: Isolation banner | Synthetic sandbox data
- Caption: The sandbox is isolated from real data. The banner stays visible so you know the content is synthetic.
- Claims: C02, C03
- Sources: docs/walkthroughs/admin.md, docs/accessibility/README.md
- Duration estimate: 15 s

### Scene S03 Viewer and a cost spike

- Visual: Viewer workspace, then the cost dashboard at `/dashboards/cost` showing the seeded cost spike window. Isolation banner visible.
- Narration: A viewer opens the cost dashboard and finds a seeded spike. In the synthetic data, token use was raised twelve times and volume three times inside a known window. The viewer can read, but there is no action, export or edit path.
- On-screen text: Viewer | Seeded cost spike | Read access
- Caption: A viewer finds a seeded cost spike on the dashboard. The viewer can read, but cannot act or edit.
- Claims: C04
- Sources: docs/walkthroughs/viewer.md
- Duration estimate: 18 s

### Scene S04 Analyst and replay

- Visual: Analyst workspace, latency dashboard at `/dashboards/latency`, a trace opened at `/replay/traces`, then `/reports`. Isolation banner visible.
- Narration: An analyst investigates a seeded latency regression, replays a trace through an affected agent, and runs a saved report. Reports run under the analyst's own scope on every run.
- On-screen text: Analyst | Latency regression | Trace replay | Saved reports
- Caption: An analyst investigates a seeded latency regression, replays a trace and runs a saved report under their own scope.
- Claims: C05
- Sources: docs/walkthroughs/analyst.md
- Duration estimate: 13 s

### Scene S05 Steward review

- Visual: Steward workspace, stale agents list, then the review queue with a duplicate candidate. Isolation banner visible.
- Narration: A steward reviews consolidation candidates and unused agents. Candidates are always labelled as candidates and are never merged automatically. When the steward decides, the system shows the exact target and diff, rechecks permission, honors approvals, records an audit entry and verifies the real change.
- On-screen text: Steward | Candidates, never auto-merged | Diff, permission recheck, audit
- Caption: A steward reviews candidates that are never merged automatically. The system shows the exact diff, rechecks permission and audits the change.
- Claims: C06, C07
- Sources: docs/walkthroughs/steward.md
- Duration estimate: 19 s

### Scene S06 Admin and messy input

- Visual: Admin workspace, execution control, then the comparison of the bad-event manifest against what the pipeline accepted and quarantined. Isolation banner visible.
- Narration: An admin works with deliberately messy synthetic input: duplicate, out of order and malformed events. Quarantine and replay let the admin compare what was injected with what the pipeline accepted. Admin is a scoped role, with no unrestricted bypass.
- On-screen text: Admin | Bad events: quarantine and replay | Scoped role
- Caption: An admin compares injected bad events with what the pipeline accepted and quarantined. Admin is a scoped role.
- Claims: C08, C09
- Sources: docs/walkthroughs/admin.md
- Duration estimate: 17 s

### Scene S07 Auditor and the audit trail

- Visual: Auditor workspace, `/audit`, then `/actions/detail` comparing a proposed change with the verified result. Isolation banner visible.
- Narration: An auditor reads the audit trail. Each action records who acted, the target and version, and the outcome. The auditor can compare a proposed change with the verified result. The data is synthetic, so none of this is evidence of compliance or authorization.
- On-screen text: Auditor | Who, target, version, outcome | Synthetic: not compliance evidence
- Caption: An auditor reads who acted, on what target and version, and the outcome. The data is synthetic and is not compliance evidence.
- Claims: C10, C11
- Sources: docs/walkthroughs/auditor.md
- Duration estimate: 18 s

### Scene S08 Government and closing

- Visual: Admin view of `/deploy/capabilities` showing a feature disabled with a reason, then a closing card. Isolation banner visible in the opening scenes.
- Narration: Support for Azure Government is gated by a capability matrix, and unsupported combinations are disabled rather than hidden. Availability, general availability and authorization are separate questions, and this video makes no claim about any of them. Dashboard and map speeds in the product documents are planning targets, not measured promises.
- On-screen text: Capability matrix | Availability, GA and authorization are separate | Performance figures are targets
- Caption: Government support is gated by a capability matrix. Availability, GA and authorization are separate. Speeds in the documents are planning targets.
- Claims: C12
- Sources: docs/walkthroughs/admin.md, docs/RESEARCH-AND-GATES.md, docs/PRD.md
- Duration estimate: 21 s

## Totals (estimates)

See the computed figures in the estimates section below; they are checked by the storyboard test against the narration word count.

### Estimates

- Scenes: 8
- Narration words: 306
- Estimated narration time at 150 words per minute: about 122 s (2.0 min)
- Estimated total runtime including pauses: 132 s (sum of the scene estimates, about 2.2 min)
