---
status: draft
rendered: false
---

# NeuroSphere explainer video: narration script (source text)

This is source text, not a rendered video. It is not a rendered video and no audio exists for it. Each section is the narration of the scene with the same id in `storyboard.md`; edit narration there and keep this file identical. The word count is 306 and the read time is an estimate at 150 words per minute.

## S01 Opening

NeuroSphere is a customer-hosted governance layer for AI agents. This video walks through it using a synthetic sandbox, so everything you see is generated data.

## S02 Sandbox isolation

The sandbox is isolated from real data. The banner stays on screen so you always know you are looking at synthetic content. Real ingestion needs approved connectors, and the demo never uses production data.

## S03 Viewer and a cost spike

A viewer opens the cost dashboard and finds a seeded spike. In the synthetic data, token use was raised twelve times and volume three times inside a known window. The viewer can read, but there is no action, export or edit path.

## S04 Analyst and replay

An analyst investigates a seeded latency regression, replays a trace through an affected agent, and runs a saved report. Reports run under the analyst's own scope on every run.

## S05 Steward review

A steward reviews consolidation candidates and unused agents. Candidates are always labelled as candidates and are never merged automatically. When the steward decides, the system shows the exact target and diff, rechecks permission, honors approvals, records an audit entry and verifies the real change.

## S06 Admin and messy input

An admin works with deliberately messy synthetic input: duplicate, out of order and malformed events. Quarantine and replay let the admin compare what was injected with what the pipeline accepted. Admin is a scoped role, with no unrestricted bypass.

## S07 Auditor and the audit trail

An auditor reads the audit trail. Each action records who acted, the target and version, and the outcome. The auditor can compare a proposed change with the verified result. The data is synthetic, so none of this is evidence of compliance or authorization.

## S08 Government and closing

Support for Azure Government is gated by a capability matrix, and unsupported combinations are disabled rather than hidden. Availability, general availability and authorization are separate questions, and this video makes no claim about any of them. Dashboard and map speeds in the product documents are planning targets, not measured promises.

