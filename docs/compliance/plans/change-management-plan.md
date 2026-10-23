# Change management plan

> **Scope:** How changes to NeuroSphere source, infrastructure, configuration and managed targets are proposed, gated, released and rolled back.
> **Status vocabulary:** `designed`, `implemented_tested`, `inherited`, `customer`, `planned`, `not_applicable`.
> **Statement:** NeuroSphere is not FedRAMP authorized; the authorizing official decides. This document supports the customer security team and the authorizing official. It is not an assessment, makes no authorization, ATO, parity or certification claim, and carries no authorization date or compliance score.
> **Provenance:** PRP-23 item 4. Customer-owned inputs are recorded as `customer` and OPEN; they are never guessed here.

Links: release gates in the [Definition-of-Done checklist](../../release/dod-checklist.md) (PRP-13), [release process](../../release/release-process.md), [versioning](../../release/versioning.md), [verify](../../release/verify.md). Secret handling: [pre-push checklist](../../security/runbooks/pre-push-checklist.md). Responsibility split: [responsibility matrix](../responsibility-matrix.md). Related plans: [continuous monitoring](continuous-monitoring-plan.md), [incident response](incident-response-plan.md).

## 1. Two kinds of change

1. **Product changes** (code, schemas, infrastructure-as-code, dependencies, documents). Owned by the NeuroSphere maintainers.
2. **Deployment and runtime changes** (configuration, model swaps, connector writes, policy edits) in a customer-hosted instance. Owned by the customer's change authority; NeuroSphere supplies the mechanism.

## 2. Product change flow

| Step | Control | Status |
|---|---|---|
| Plan | Work is scoped as a PRP with owned files, acceptance criteria and gates; shared files are sequenced, not edited in parallel | `implemented_tested` as repository practice |
| Local gates | Targeted tests, schema, adapter and authorization tests, lint; the planning validator `scripts/validate_planning.py` | `implemented_tested` |
| Secret and PII guard | `.githooks/` pre-commit and pre-push locally; the secret-scan workflow over full history in CI is the backstop (local hooks can be bypassed) | `implemented_tested` |
| CI | Tests, CodeQL, dependency and licence checks, SBOM and scans; CI may not suppress failures (the planning validator rejects failure-suppressing shell fallbacks) | `implemented_tested` |
| Review | Items marked `review: required` get one independent review pass; blocking defects only | `designed` |
| Merge | Scoped commits; no force push; push and deployment need operator approval | `designed` |
| Release | Version, release notes naming every OPEN gate, DoD checklist copied and ticked per release with evidence filed under `docs/evidence/release/<version>/` | `designed`; per-release evidence `planned` |

Contract changes (OpenAPI, event schemas) follow the versioning policy; migrations ship with a rollback and are tested on the emulator. Migrations and rollback against a live account are OPEN (G12).

## 3. Deployment and runtime change flow

- **One executor.** Buttons, chat and MCP use the same durable action executor. A change shows the exact target, version and diff, rechecks permission and target version at execution, honors approvals, audits intent and result, and verifies the actual change. Catalog-only "pretend" swaps are not a change and are not permitted. `implemented_tested` for the action types built to date.
- **Approvals.** Whether a change needs reviewer approval, who the approvers are and any emergency path are `customer` inputs, OPEN.
- **Deployment plans.** The deployment-intelligence flow produces a reuse, create or skip plan, requires operator approval, disables unavailable options with the reason, and finishes with smoke tests and an evidence manifest. Live deployment needs operator approval and `NS_LIVE_APPROVED=1`; no paid or cloud deployment runs without it.
- **Cloud boundary.** A change never introduces a data path between Government and Commercial deployments ([boundary diagram](boundary-and-data-flow.md)). Profile or region changes are re-checked against the capability matrix and the G02 register.
- **Retention and policy changes.** Retention, hold and deletion policy changes are audited. With no valid policy the lifecycle engine deletes nothing.

## 4. Rollback

Product: revert through version control; no history rewriting of shared branches. Runtime: the executor records rollback evidence for each change. Data: the [contingency plan](contingency-plan.md) and DR runbook. A rollback that was not tested is reported as untested.

## 5. Security impact analysis

Each product change that touches identity, audit, the action executor, MCP, data egress or the boundary needs the threat model reviewed for the affected boundary ([threat-model.md](../../security/threat-model.md)); the reviewer notes the outcome in the PRP or pull request. A change to the audit store, the conflict rules in the lifecycle engine or the disclaimer enforcement is `review: required`.

## 6. Customer inputs (OPEN)

| Input | Status |
|---|---|
| Change advisory board or authority, approval matrix, emergency change path | `customer`, OPEN |
| Maintenance windows, freeze periods | `customer`, OPEN |
| Configuration baseline selection (agency baseline) | `customer`, OPEN |
| Significant-change criteria that trigger reassessment by the authorizing official | `customer`, OPEN; decided by the authorizing official |
